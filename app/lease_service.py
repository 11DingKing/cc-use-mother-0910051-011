"""线索认领租约服务。

设计要点：
- 同一线索至多一条 ACTIVE 租约，由 clue_leases 上的部分唯一索引兜底，
  并发认领在数据库层决胜负，应用层捕获 IntegrityError 返回 409。
- 续租 / 释放 / 回收 / 转派均使用带版本与状态谓词的条件 UPDATE（CAS），
  以 rowcount 判断是否真正发生状态迁移；状态迁移与审计事件在同一事务内落库，
  因此恢复任务重复执行至多产生一次回收/转派事件。
- 提交核查记录、结案必须出示与当前 ACTIVE 租约一致的 holder + version；
  租约过期或被转派后，原持有人的迟到请求一律 409，无法覆盖新承办人。
- 证据哈希始终基于服务端完整证据（含举报人明文）做规范化哈希，
  与调用方角色无关，故字段裁剪后哈希仍保持稳定。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ViolationClue, ClueLease, ClueLeaseEvent,
    LeaseStatus, LeaseEventType, UserRole, ClueStatus,
)

# 默认认领期限（分钟）
DEFAULT_LEASE_TTL_MINUTES = 120
# 单次续租允许的最大期限
MAX_RENEW_TTL_MINUTES = 60 * 24 * 7


class LeaseError(Exception):
    """租约业务错误，携带建议的 HTTP 状态码。"""

    def __init__(self, detail: str, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


# 各角色在认领时固定下来的办理权限快照
ROLE_PERMISSIONS = {
    UserRole.INSPECTOR: [
        "view_evidence",
        "submit_inspection",
        "renew_lease",
        "release_lease",
        "conclude",
    ],
    UserRole.SUPERVISOR: [
        "view_evidence",
        "view_informant",
        "submit_inspection",
        "renew_lease",
        "release_lease",
        "conclude",
        "force_reassign",
    ],
    UserRole.ADMIN: [
        "view_evidence",
        "view_informant",
        "submit_inspection",
        "renew_lease",
        "release_lease",
        "conclude",
        "force_reassign",
    ],
}

# 参与证据哈希的举报人敏感字段（哈希用完整明文，接口按角色裁剪）
_INFORMANT_FIELDS = (
    "informant_name", "informant_phone",
    "informant_id_card", "informant_contact_detail",
)


def _canonical(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def compute_evidence_hash(clue: ViolationClue) -> str:
    """对线索的实质证据做稳定哈希。

    输入字段固定、键序固定、空值归一，结果与查看者角色无关；
    证据未变则续租/转派后重新认领得到的哈希一致。
    """
    payload = {
        "clue_type": _canonical(clue.clue_type),
        "title": _canonical(clue.title),
        "description": _canonical(clue.description),
        "institution_id": _canonical(clue.institution_id),
        "practitioner_id": _canonical(clue.practitioner_id),
        "procedure_id": _canonical(clue.procedure_id),
        "source": _canonical(clue.source),
    }
    for field in _INFORMANT_FIELDS:
        payload[field] = _canonical(getattr(clue, field, None))
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_evidence_summary(clue: ViolationClue, db: Session) -> str:
    """认领时固定的可见证据摘要（不含举报人身份明文）。"""
    from .models import Institution, Practitioner, Procedure

    institution = db.get(Institution, clue.institution_id) if clue.institution_id else None
    practitioner = db.get(Practitioner, clue.practitioner_id) if clue.practitioner_id else None
    procedure = db.get(Procedure, clue.procedure_id) if clue.procedure_id else None

    lines = [
        f"线索编号: {clue.id}",
        f"线索类型: {_enum_value(clue.clue_type)}",
        f"标题: {clue.title}",
        f"优先级: {_enum_value(clue.priority)}",
        f"来源: {clue.source or '无'}",
        f"涉及机构: {institution.name if institution else '无'}",
        f"涉及人员: {practitioner.name if practitioner else '无'}",
        f"涉及项目: {procedure.name if procedure else '无'}",
        f"线索描述: {clue.description}",
    ]
    # 已有的现场核查记录条数也是证据的一部分，认领时一并冻结
    existing = len(clue.inspection_records or [])
    lines.append(f"认领时已有核查记录: {existing} 条")
    return "\n".join(lines)


def _enum_value(value) -> str:
    return getattr(value, "value", str(value))


def permissions_for_role(role: UserRole) -> list[str]:
    return list(ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS[UserRole.INSPECTOR]))


def get_active_lease(db: Session, clue_id: int) -> Optional[ClueLease]:
    return db.execute(
        select(ClueLease).where(
            ClueLease.clue_id == clue_id,
            ClueLease.status == LeaseStatus.ACTIVE,
        )
    ).scalar_one_or_none()


def _add_event(
    db: Session, *, lease: ClueLease, event_type: LeaseEventType,
    actor: str, reason: str = "",
    from_holder: Optional[str] = None, to_holder: Optional[str] = None,
    version_before: Optional[int] = None, version_after: Optional[int] = None,
    clue_id: Optional[int] = None,
) -> ClueLeaseEvent:
    event = ClueLeaseEvent(
        lease_id=lease.id,
        clue_id=clue_id if clue_id is not None else lease.clue_id,
        event_type=event_type,
        actor=actor,
        reason=reason or "",
        from_holder=from_holder,
        to_holder=to_holder,
        version_before=version_before if version_before is not None else lease.version,
        version_after=version_after if version_after is not None else lease.version,
    )
    db.add(event)
    return event


def claim_lease(
    db: Session, clue: ViolationClue, *,
    holder: str, holder_role: UserRole = UserRole.INSPECTOR,
    ttl_minutes: int = DEFAULT_LEASE_TTL_MINUTES, reason: str = "",
) -> ClueLease:
    if clue.status in (ClueStatus.VERIFIED, ClueStatus.DISMISSED):
        raise LeaseError("线索已结案，不能再认领", status_code=400)

    now = datetime.utcnow()
    lease = ClueLease(
        clue_id=clue.id,
        holder=holder,
        holder_role=holder_role,
        status=LeaseStatus.ACTIVE,
        version=1,
        leased_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
        evidence_summary=build_evidence_summary(clue, db),
        evidence_hash=compute_evidence_hash(clue),
        permissions=json.dumps(permissions_for_role(holder_role), ensure_ascii=False),
    )
    db.add(lease)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        current = get_active_lease(db, clue.id)
        holder_desc = f"，当前持有人：{current.holder}" if current else ""
        raise LeaseError(f"线索已被他人认领租约{holder_desc}")

    clue.status = ClueStatus.ASSIGNED
    clue.assignee = holder
    clue.assigned_at = now
    _add_event(
        db, lease=lease, event_type=LeaseEventType.CLAIM,
        actor=holder, reason=reason or "核查人员认领线索",
        version_before=0, version_after=1,
    )
    db.commit()
    db.refresh(lease)
    return lease


def renew_lease(
    db: Session, clue_id: int, lease_id: int, *,
    holder: str, expected_version: int,
    ttl_minutes: int = DEFAULT_LEASE_TTL_MINUTES, reason: str,
) -> ClueLease:
    if not reason or not reason.strip():
        raise LeaseError("续租必须填写原因", status_code=400)
    ttl_minutes = min(max(1, ttl_minutes), MAX_RENEW_TTL_MINUTES)
    now = datetime.utcnow()

    result = db.execute(
        update(ClueLease)
        .where(
            ClueLease.id == lease_id,
            ClueLease.clue_id == clue_id,
            ClueLease.holder == holder,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == expected_version,
            ClueLease.expires_at > now,
        )
        .values(
            expires_at=now + timedelta(minutes=ttl_minutes),
            version=ClueLease.version + 1,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise _guard_failure(db, clue_id, lease_id, holder, expected_version, now,
                             action="续租")

    lease = db.get(ClueLease, lease_id)
    _add_event(
        db, lease=lease, event_type=LeaseEventType.RENEW,
        actor=holder, reason=reason,
        version_before=expected_version, version_after=lease.version,
    )
    db.commit()
    db.refresh(lease)
    return lease


def release_lease(
    db: Session, clue_id: int, lease_id: int, *,
    holder: str, expected_version: int, reason: str,
) -> ClueLease:
    if not reason or not reason.strip():
        raise LeaseError("主动释放必须填写原因", status_code=400)
    now = datetime.utcnow()

    result = db.execute(
        update(ClueLease)
        .where(
            ClueLease.id == lease_id,
            ClueLease.clue_id == clue_id,
            ClueLease.holder == holder,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == expected_version,
        )
        .values(
            status=LeaseStatus.RELEASED,
            released_at=now,
            version=ClueLease.version + 1,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise _guard_failure(db, clue_id, lease_id, holder, expected_version, now,
                             action="释放")

    lease = db.get(ClueLease, lease_id)
    _add_event(
        db, lease=lease, event_type=LeaseEventType.RELEASE,
        actor=holder, reason=reason,
        version_before=expected_version, version_after=lease.version,
    )
    # 释放后线索回到待分派池，等待他人认领
    clue = db.get(ViolationClue, clue_id)
    if clue and clue.status == ClueStatus.ASSIGNED:
        clue.status = ClueStatus.PENDING
        clue.assignee = None
        clue.assigned_at = None
    db.commit()
    db.refresh(lease)
    return lease


def expire_lease_if_due(db: Session, lease: ClueLease, now: datetime,
                        reason: str = "租约超过有效期未续租，系统自动回收") -> bool:
    """条件回收单条租约。仅当状态确由 ACTIVE 迁移为 EXPIRED 时返回 True 并落事件。

    恢复任务可安全重复调用：第二次调用谓词不再匹配，rowcount=0，不产生新事件。
    """
    result = db.execute(
        update(ClueLease)
        .where(
            ClueLease.id == lease.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.expires_at <= now,
        )
        .values(
            status=LeaseStatus.EXPIRED,
            released_at=now,
            version=ClueLease.version + 1,
        )
    )
    if result.rowcount != 1:
        return False

    db.refresh(lease)
    old_version = lease.version - 1
    _add_event(
        db, lease=lease, event_type=LeaseEventType.EXPIRE,
        actor="system", reason=reason,
        from_holder=lease.holder,
        version_before=old_version, version_after=lease.version,
    )
    clue = db.get(ViolationClue, lease.clue_id)
    if clue and clue.status == ClueStatus.ASSIGNED and clue.assignee == lease.holder:
        clue.status = ClueStatus.PENDING
        clue.assignee = None
        clue.assigned_at = None
    return True


def recover_expired_leases(db: Session, *, now: Optional[datetime] = None,
                           auto_reassign_to: Optional[str] = None,
                           reason: Optional[str] = None) -> dict:
    """启动恢复 / 定时任务：回收所有到期租约。

    分两阶段提交：第一阶段只做条件 UPDATE 回收并提交；第二阶段再对成功回收
    且仍待分派的线索尝试转派并提交。每个阶段的条件 UPDATE 都以 rowcount 判定
    是否发生真实状态迁移，故恢复任务重复执行（含服务重启后）不会产生第二次
    回收事件，转派也至多一次。
    """
    now = now or datetime.utcnow()
    expire_reason = reason or "租约超过有效期未续租，系统自动回收"

    candidates = db.execute(
        select(ClueLease).where(
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.expires_at <= now,
        ).with_for_update()  # PG 下行锁；SQLite 下被忽略，幂等由 rowcount 与唯一索引保证
    ).scalars().all()

    expired = []
    for lease in candidates:
        if expire_lease_if_due(db, lease, now, reason=expire_reason):
            expired.append(lease.id)
    db.commit()

    reassigned = []
    if auto_reassign_to and expired:
        for lease_id in expired:
            lease = db.get(ClueLease, lease_id)
            clue = db.get(ViolationClue, lease.clue_id) if lease else None
            # 仅当回收后线索仍待分派（未被他人抢先认领）时才转派
            if clue is None or clue.status != ClueStatus.PENDING:
                continue
            try:
                new_lease = claim_lease(
                    db, clue, holder=auto_reassign_to,
                    holder_role=UserRole.SUPERVISOR,
                    reason=f"原持有人 {lease.holder} 租约超时，系统转派值班主管",
                )
                reassigned.append(new_lease.id)
            except LeaseError:
                # 已被他人抢先认领则不重复转派
                db.rollback()

    return {"expired_lease_ids": expired, "reassigned_lease_ids": reassigned,
            "expired_count": len(expired), "reassigned_count": len(reassigned)}


def reassign_lease(
    db: Session, clue: ViolationClue, *,
    supervisor: str, to_holder: str,
    to_role: UserRole = UserRole.INSPECTOR, reason: str,
) -> ClueLease:
    """主管强制转派：终结原租约并为新承办人立约，全程留原因。

    幂等：若目标人已持有该线索的当前租约，直接返回现状，不重复产生事件。
    """
    if not reason or not reason.strip():
        raise LeaseError("强制转派必须填写原因", status_code=400)
    if not to_holder or not to_holder.strip():
        raise LeaseError("必须指定新承办人", status_code=400)

    current = get_active_lease(db, clue.id)
    now = datetime.utcnow()
    if current is None:
        raise LeaseError("线索当前没有有效租约，可直接认领", status_code=409)
    if current.holder == to_holder:
        # 重复转派同一承办人：无新状态迁移，不得再造事件
        return current

    result = db.execute(
        update(ClueLease)
        .where(
            ClueLease.id == current.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == current.version,
        )
        .values(
            status=LeaseStatus.REASSIGNED,
            released_at=now,
            version=ClueLease.version + 1,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise LeaseError("租约状态已变化，请刷新后重试")

    old = db.get(ClueLease, current.id)
    _add_event(
        db, lease=old, event_type=LeaseEventType.REASSIGN,
        actor=supervisor, reason=reason,
        from_holder=old.holder, to_holder=to_holder,
        version_before=current.version, version_after=old.version,
    )

    new_lease = ClueLease(
        clue_id=clue.id,
        holder=to_holder,
        holder_role=to_role,
        status=LeaseStatus.ACTIVE,
        version=1,
        leased_at=now,
        expires_at=now + timedelta(minutes=DEFAULT_LEASE_TTL_MINUTES),
        evidence_summary=build_evidence_summary(clue, db),
        evidence_hash=compute_evidence_hash(clue),
        permissions=json.dumps(permissions_for_role(to_role), ensure_ascii=False),
    )
    db.add(new_lease)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise LeaseError("线索已存在有效租约，转派失败")

    clue.status = ClueStatus.ASSIGNED
    clue.assignee = to_holder
    clue.assigned_at = now
    _add_event(
        db, lease=new_lease, event_type=LeaseEventType.CLAIM,
        actor=supervisor, reason=f"主管强制转派：{reason}",
        from_holder=old.holder, to_holder=to_holder,
        version_before=0, version_after=1,
    )
    db.commit()
    db.refresh(new_lease)
    return new_lease


def require_active_lease(
    db: Session, clue_id: int, lease_id: int, *,
    holder: str, expected_version: int, now: Optional[datetime] = None,
) -> ClueLease:
    """提交核查记录 / 结案前的闸门：必须持有当前版本的有效租约。"""
    now = now or datetime.utcnow()
    lease = db.get(ClueLease, lease_id)
    if lease is None or lease.clue_id != clue_id:
        raise LeaseError("租约不存在", status_code=404)
    if lease.status != LeaseStatus.ACTIVE:
        raise LeaseError(
            f"租约已失效（{_enum_value(lease.status)}），当前承办人可能已变更，禁止提交",
        )
    if lease.holder != holder:
        current = get_active_lease(db, clue_id)
        who = current.holder if current else "无"
        raise LeaseError(f"租约当前持有人为 {who}，{holder} 的迟到请求被拒绝")
    if lease.expires_at <= now:
        # 惰性回收：条件 UPDATE 保证与恢复任务合计只落一次 EXPIRE 事件
        if expire_lease_if_due(db, lease, now):
            db.commit()
        raise LeaseError("租约已过期并被回收，请重新认领后再提交")
    if lease.version != expected_version:
        raise LeaseError(
            f"租约版本不匹配：请求基于版本 {expected_version}，当前版本为 {lease.version}",
        )
    return lease


def complete_lease(db: Session, lease: ClueLease, *, actor: str, reason: str) -> None:
    now = datetime.utcnow()
    result = db.execute(
        update(ClueLease)
        .where(
            ClueLease.id == lease.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == lease.version,
        )
        .values(status=LeaseStatus.COMPLETED, released_at=now,
                version=ClueLease.version + 1)
    )
    if result.rowcount != 1:
        db.rollback()
        raise LeaseError("租约状态已变化，结案失败")
    db.refresh(lease)
    _add_event(
        db, lease=lease, event_type=LeaseEventType.COMPLETE,
        actor=actor, reason=reason or "线索结案，租约终结",
        version_before=lease.version - 1, version_after=lease.version,
    )


def _guard_failure(db: Session, clue_id: int, lease_id: int, holder: str,
                   expected_version: int, now: datetime, *, action: str) -> LeaseError:
    lease = db.get(ClueLease, lease_id)
    if lease is None or lease.clue_id != clue_id:
        return LeaseError("租约不存在", status_code=404)
    if lease.status != LeaseStatus.ACTIVE:
        return LeaseError(f"租约已失效（{_enum_value(lease.status)}），无法{action}")
    if lease.holder != holder:
        current = get_active_lease(db, clue_id)
        who = current.holder if current else "无"
        return LeaseError(f"非租约持有人（当前：{who}），无法{action}")
    if lease.expires_at <= now:
        return LeaseError(f"租约已过期并被回收，无法{action}，请重新认领")
    return LeaseError(
        f"租约版本不匹配：请求基于版本 {expected_version}，当前版本为 {lease.version}，无法{action}",
    )


# —— 举报人敏感字段裁剪 ——

def _mask_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return name
    if len(name) == 1:
        return name + "*"
    return name[0] + "*" * (len(name) - 1)


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return phone
    tail = phone[-4:]
    return "*" * max(0, len(phone) - 4) + tail


def _mask_id_card(id_card: Optional[str]) -> Optional[str]:
    if not id_card:
        return id_card
    if len(id_card) <= 6:
        return "*" * len(id_card)
    return id_card[:3] + "*" * (len(id_card) - 6) + id_card[-3:]


def can_view_informant(role: UserRole) -> bool:
    return role in (UserRole.SUPERVISOR, UserRole.ADMIN)


def informant_view(clue: ViolationClue, role: UserRole) -> Optional[dict]:
    """按角色裁剪举报人字段：主管/管理员见明文，核查员见脱敏值，无信息则不返回。"""
    raw = {
        "name": clue.informant_name,
        "phone": clue.informant_phone,
        "id_card": clue.informant_id_card,
        "contact_detail": clue.informant_contact_detail,
    }
    if not any(v for v in raw.values()):
        return None
    if can_view_informant(role):
        return {**raw, "masked": False}
    return {
        "name": _mask_name(raw["name"]),
        "phone": _mask_phone(raw["phone"]),
        "id_card": _mask_id_card(raw["id_card"]),
        "contact_detail": None,
        "masked": True,
    }
