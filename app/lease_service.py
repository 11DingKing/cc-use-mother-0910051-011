"""线索认领租约领域服务。

核心保证：
- 认领时固定证据摘要（内容冻结）与办理权限，证据摘要哈希仅由证据内容决定，
  与观看角色无关，因而保持稳定；
- 续租 / 主动释放 / 超时回收 / 主管强制转派都会写入带原因的审计事件；
- 提交核查记录、结案必须携带当前租约版本号，过期持有者的迟到请求会被版本校验拒绝；
- 回收与转派采用带状态条件的更新，恢复任务重复执行至多产生一次结果。
"""
import json
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .models import (
    ViolationClue, InspectionRecord, ClueLease, LeaseEvent,
    UserRole, LeaseStatus, LeaseEventType, ClueStatus,
)

DEFAULT_TTL_MINUTES = 30
MAX_TTL_MINUTES = 480

INVESTIGATOR_PERMISSIONS = [
    "查看证据摘要", "提交核查记录", "续租", "主动释放", "提交结案",
]
SUPERVISOR_PERMISSIONS = INVESTIGATOR_PERMISSIONS + [
    "查看举报人完整信息", "强制转派", "回收超时租约", "查看租约审计记录",
]
ADMIN_PERMISSIONS = SUPERVISOR_PERMISSIONS + ["全部管理权限"]

ROLE_PERMISSIONS = {
    UserRole.INVESTIGATOR: INVESTIGATOR_PERMISSIONS,
    UserRole.SUPERVISOR: SUPERVISOR_PERMISSIONS,
    UserRole.ADMIN: ADMIN_PERMISSIONS,
}

# 举报人敏感字段：核查员不可见完整内容，仅主管/管理员可见
REPORTER_FIELDS = ("reporter_name", "reporter_phone", "reporter_id_card", "reporter_address")


class LeaseError(Exception):
    """租约业务错误，http_status 给出建议 HTTP 状态码。"""

    def __init__(self, message: str, http_status: int = 409):
        super().__init__(message)
        self.http_status = http_status


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _permissions_for_role(role: UserRole) -> List[str]:
    return list(ROLE_PERMISSIONS.get(role, INVESTIGATOR_PERMISSIONS))


def _mask_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    if len(name) == 1:
        return name + "**"
    return name[0] + "*" * (len(name) - 1)


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    if len(phone) <= 4:
        return "****"
    if len(phone) < 7:
        return phone[0] + "****" + phone[-1]
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def trim_reporter(clue: ViolationClue, role: UserRole) -> Optional[Dict[str, Any]]:
    """按角色裁剪举报人字段。主管/管理员可见完整信息，核查员只见脱敏摘要。"""
    has_reporter = any(getattr(clue, f, None) for f in REPORTER_FIELDS)
    if not has_reporter:
        return None
    if role in (UserRole.SUPERVISOR, UserRole.ADMIN):
        return {
            "name": clue.reporter_name,
            "phone": clue.reporter_phone,
            "id_card": clue.reporter_id_card,
            "address": clue.reporter_address,
        }
    return {
        "name": _mask_name(clue.reporter_name),
        "phone": _mask_phone(clue.reporter_phone),
        # 身份证号与住址对核查员完全裁剪
        "id_card": None,
        "address": None,
    }


def build_evidence_core(clue: ViolationClue, db: Session) -> Dict[str, Any]:
    """构造证据摘要的稳定内核（不含举报人敏感字段、不含时间戳与持有人信息）。"""
    institution_name = clue.institution.name if clue.institution else None
    practitioner_name = None
    if clue.practitioner_id is not None:
        from .models import Practitioner
        prac = db.query(Practitioner).filter(Practitioner.id == clue.practitioner_id).first()
        practitioner_name = prac.name if prac else None
    procedure_name = clue.procedure.name if clue.procedure else None

    evidence_items = []
    records = (
        db.query(InspectionRecord)
        .filter(InspectionRecord.clue_id == clue.id)
        .order_by(InspectionRecord.inspection_date, InspectionRecord.id)
        .all()
    )
    for r in records:
        evidence_items.append({
            "inspection_id": r.id,
            "inspection_date": r.inspection_date.isoformat() if r.inspection_date else None,
            "inspector": r.inspector,
            "content": r.content,
            "finding": r.finding,
        })

    return {
        "clue_id": clue.id,
        "clue_type": clue.clue_type.value if clue.clue_type else None,
        "title": clue.title,
        "description": clue.description,
        "source": clue.source,
        "priority": clue.priority.value if clue.priority else None,
        "institution_name": institution_name,
        "practitioner_name": practitioner_name,
        "procedure_name": procedure_name,
        "evidence_items": evidence_items,
    }


def compute_evidence_hash(core: Dict[str, Any]) -> str:
    """证据摘要哈希：规范化 JSON 后取 SHA-256。仅由证据内容决定，角色裁剪不影响哈希。"""
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_evidence_summary(clue: ViolationClue, db: Session, role: UserRole,
                           core: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if core is None:
        core = build_evidence_core(clue, db)
    summary = dict(core)
    summary["generated_for_role"] = role.value
    # 举报人信息按角色裁剪后再放入可见摘要，且不参与哈希
    summary["reporter"] = trim_reporter(clue, role)
    return summary


def _next_version(db: Session, clue_id: int) -> int:
    last = (
        db.query(ClueLease.version)
        .filter(ClueLease.clue_id == clue_id)
        .order_by(ClueLease.version.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


def current_lease(db: Session, clue_id: int) -> Optional[ClueLease]:
    """状态为 ACTIVE 的租约行（不判断是否已到期）。"""
    return (
        db.query(ClueLease)
        .filter(ClueLease.clue_id == clue_id, ClueLease.status == LeaseStatus.ACTIVE)
        .order_by(ClueLease.id.desc())
        .first()
    )


def valid_lease(db: Session, clue_id: int, now: Optional[datetime] = None) -> Optional[ClueLease]:
    """当前仍在有效期内的租约（状态 ACTIVE 且未过期）。"""
    now = now or datetime.utcnow()
    lease = current_lease(db, clue_id)
    if lease and lease.expires_at > now:
        return lease
    return None


def _add_event(db: Session, lease: ClueLease, event_type: LeaseEventType,
               actor: str, actor_role: UserRole, reason: str,
               from_version: Optional[int], to_version: Optional[int]) -> LeaseEvent:
    event = LeaseEvent(
        lease_id=lease.id,
        clue_id=lease.clue_id,
        event_type=event_type,
        actor=actor,
        actor_role=actor_role,
        from_version=from_version,
        to_version=to_version,
        reason=reason,
    )
    db.add(event)
    return event


def _expire_if_needed(db: Session, clue_id: int, now: datetime,
                      autocommit: bool, reason: str) -> Optional[ClueLease]:
    """若线索存在已到期但状态仍为 ACTIVE 的租约，原子地将其回收。

    UPDATE 带状态与到期时间条件，行锁保证并发/重复执行时只有一次状态迁移。
    """
    stale = (
        db.query(ClueLease)
        .filter(
            ClueLease.clue_id == clue_id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.expires_at <= now,
        )
        .order_by(ClueLease.id.desc())
        .first()
    )
    if stale is None:
        return None
    updated = (
        db.query(ClueLease)
        .filter(
            ClueLease.id == stale.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.expires_at <= now,
        )
        .update(
            {
                "status": LeaseStatus.EXPIRED,
                "released_at": now,
                "close_reason": reason,
            },
            synchronize_session=False,
        )
    )
    if updated == 0:
        # 已被其他执行者回收（并发恢复任务/其他线程抢先提交）
        return None
    db.add(LeaseEvent(
        lease_id=stale.id,
        clue_id=clue_id,
        event_type=LeaseEventType.EXPIRE,
        actor="系统回收任务",
        actor_role=UserRole.ADMIN,
        from_version=stale.version,
        to_version=stale.version,
        reason=reason,
    ))
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if clue is not None:
        clue.status = ClueStatus.PENDING
        clue.assignee = None
        clue.assigned_at = None
    if autocommit:
        db.commit()
    else:
        db.flush()
    return stale


# ---------------------------------------------------------------------------
# 租约操作
# ---------------------------------------------------------------------------

def acquire_lease(db: Session, clue_id: int, holder: str, role: UserRole,
                  ttl_minutes: Optional[int] = None, reason: Optional[str] = None,
                  now: Optional[datetime] = None, autocommit: bool = True) -> Tuple[ClueLease, Dict[str, Any]]:
    now = now or datetime.utcnow()
    ttl_minutes = ttl_minutes or DEFAULT_TTL_MINUTES
    if ttl_minutes <= 0 or ttl_minutes > MAX_TTL_MINUTES:
        raise LeaseError(f"租约时长需在 1~{MAX_TTL_MINUTES} 分钟之间", 400)

    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if clue is None:
        raise LeaseError("线索不存在", 404)
    if clue.status in (ClueStatus.VERIFIED, ClueStatus.DISMISSED):
        raise LeaseError("线索已结案，不能再认领", 409)

    # 已到期的租约先原子回收，再允许认领
    _expire_if_needed(
        db, clue_id, now, autocommit,
        reason="认领时发现租约已超时未续租，系统自动回收",
    )

    active = current_lease(db, clue_id)
    if active is not None and active.expires_at > now:
        if active.holder == holder:
            raise LeaseError("您已持有该线索的有效租约，请勿重复认领", 409)
        raise LeaseError(f"线索已被 {active.holder} 认领，租约到期前不可重复认领", 409)

    core = build_evidence_core(clue, db)
    evidence_hash = compute_evidence_hash(core)
    version = _next_version(db, clue_id)
    permissions = _permissions_for_role(role)

    lease = ClueLease(
        clue_id=clue_id,
        holder=holder,
        holder_role=role,
        status=LeaseStatus.ACTIVE,
        version=version,
        acquired_at=now,
        expires_at=now + timedelta(minutes=ttl_minutes),
        renewed_at=None,
        evidence_snapshot=json.dumps(core, ensure_ascii=False, sort_keys=True),
        evidence_hash=evidence_hash,
        permissions=json.dumps(permissions, ensure_ascii=False),
    )
    db.add(lease)
    try:
        db.flush()
    except IntegrityError:
        # 并发下另一位核查人员已抢先插入生效租约
        db.rollback()
        winner = current_lease(db, clue_id)
        winner_name = winner.holder if winner else "其他核查人员"
        raise LeaseError(f"线索刚被 {winner_name} 抢先认领，请选择其他线索", 409)
    _add_event(
        db, lease, LeaseEventType.ACQUIRE, holder, role,
        reason or f"{holder} 认领线索，租约 {ttl_minutes} 分钟",
        None, version,
    )

    clue.assignee = holder
    clue.assigned_at = now
    clue.status = ClueStatus.ASSIGNED
    if autocommit:
        db.commit()
        db.refresh(lease)
    else:
        db.flush()

    summary = build_evidence_summary(clue, db, role, core=core)
    return lease, summary


def renew_lease(db: Session, clue_id: int, holder: str, role: UserRole,
                lease_version: int, reason: str, ttl_minutes: Optional[int] = None,
                now: Optional[datetime] = None, autocommit: bool = True
                ) -> Tuple[ClueLease, Dict[str, Any]]:
    now = now or datetime.utcnow()
    ttl_minutes = ttl_minutes or DEFAULT_TTL_MINUTES
    if not reason or not reason.strip():
        raise LeaseError("续租必须填写原因", 400)
    if ttl_minutes <= 0 or ttl_minutes > MAX_TTL_MINUTES:
        raise LeaseError(f"租约时长需在 1~{MAX_TTL_MINUTES} 分钟之间", 400)

    lease = current_lease(db, clue_id)
    if lease is None:
        raise LeaseError("线索当前无生效租约，无法续租", 409)
    if lease.holder != holder:
        raise LeaseError("只有租约持有人本人可以续租", 403)
    if lease.version != lease_version:
        raise LeaseError(
            f"租约版本已过期（当前 v{lease.version}，提交 v{lease_version}），请刷新后重试", 409
        )
    if lease.expires_at <= now:
        raise LeaseError("租约已超时，请等待回收后重新认领", 409)

    old_version = lease.version
    updated = (
        db.query(ClueLease)
        .filter(
            ClueLease.id == lease.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == old_version,
            ClueLease.expires_at > now,
        )
        .update(
            {
                "version": old_version + 1,
                "expires_at": now + timedelta(minutes=ttl_minutes),
                "renewed_at": now,
            },
            synchronize_session=False,
        )
    )
    if updated == 0:
        raise LeaseError("租约状态已变化，续租失败，请刷新后重试", 409)
    db.refresh(lease)
    _add_event(db, lease, LeaseEventType.RENEW, holder, role, reason,
               old_version, lease.version)
    if autocommit:
        db.commit()
        db.refresh(lease)
    else:
        db.flush()

    core = json.loads(lease.evidence_snapshot)
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    summary = build_evidence_summary(clue, db, role, core=core)
    return lease, summary


def release_lease(db: Session, clue_id: int, holder: str, role: UserRole,
                  lease_version: int, reason: str,
                  now: Optional[datetime] = None, autocommit: bool = True) -> ClueLease:
    now = now or datetime.utcnow()
    if not reason or not reason.strip():
        raise LeaseError("主动释放必须填写原因", 400)

    lease = current_lease(db, clue_id)
    if lease is None:
        raise LeaseError("线索当前无生效租约", 409)
    if lease.holder != holder:
        raise LeaseError("只能释放自己持有的租约", 403)
    if lease.version != lease_version:
        raise LeaseError(
            f"租约版本已过期（当前 v{lease.version}，提交 v{lease_version}），不能释放旧版本", 409
        )

    old_version = lease.version
    updated = (
        db.query(ClueLease)
        .filter(
            ClueLease.id == lease.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == old_version,
        )
        .update(
            {
                "status": LeaseStatus.RELEASED,
                "released_at": now,
                "close_reason": reason,
            },
            synchronize_session=False,
        )
    )
    if updated == 0:
        raise LeaseError("租约状态已变化，释放失败，请刷新后重试", 409)
    db.refresh(lease)
    _add_event(db, lease, LeaseEventType.RELEASE, holder, role, reason,
               old_version, old_version)

    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    clue.status = ClueStatus.PENDING
    clue.assignee = None
    clue.assigned_at = None
    if autocommit:
        db.commit()
        db.refresh(lease)
    else:
        db.flush()
    return lease


def force_assign(db: Session, clue_id: int, supervisor: str, supervisor_role: UserRole,
                 new_holder: str, reason: str, new_holder_role: Optional[UserRole] = None,
                 expected_version: Optional[int] = None,
                 now: Optional[datetime] = None, autocommit: bool = True
                 ) -> Tuple[ClueLease, Dict[str, Any]]:
    """主管强制转派。重复请求携带同一版本只会成功一次（版本递增后第二次被拒）。"""
    now = now or datetime.utcnow()
    if supervisor_role not in (UserRole.SUPERVISOR, UserRole.ADMIN):
        raise LeaseError("只有主管可以强制转派", 403)
    if not reason or not reason.strip():
        raise LeaseError("强制转派必须填写原因", 400)
    if not new_holder or not new_holder.strip():
        raise LeaseError("必须指定新承办人", 400)

    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if clue is None:
        raise LeaseError("线索不存在", 404)
    if clue.status in (ClueStatus.VERIFIED, ClueStatus.DISMISSED):
        raise LeaseError("线索已结案，不能转派", 409)

    old_lease = current_lease(db, clue_id)
    if old_lease is not None and old_lease.expires_at <= now:
        _expire_if_needed(db, clue_id, now, autocommit,
                          reason="主管转派时发现租约已超时，系统自动回收")
        old_lease = None

    if old_lease is not None:
        if expected_version is not None and expected_version != old_lease.version:
            raise LeaseError(
                f"租约版本已变化（当前 v{old_lease.version}），请核实后再转派", 409
            )
        old_version = old_lease.version
        old_lease.status = LeaseStatus.FORCE_ASSIGNED
        old_lease.released_at = now
        old_lease.close_reason = f"主管 {supervisor} 强制转派给 {new_holder}：{reason}"
        _add_event(db, old_lease, LeaseEventType.FORCE_ASSIGN, supervisor,
                   supervisor_role, reason, old_version, old_version)
        # 显式落库旧租约的状态迁移，避免与新生效租约触发同一行的部分唯一索引冲突
        db.flush()
        base_version = old_version
    else:
        base_version = _next_version(db, clue_id) - 1

    new_role = new_holder_role or UserRole.INVESTIGATOR
    core = build_evidence_core(clue, db)
    new_lease = ClueLease(
        clue_id=clue_id,
        holder=new_holder,
        holder_role=new_role,
        status=LeaseStatus.ACTIVE,
        version=base_version + 1,
        acquired_at=now,
        expires_at=now + timedelta(minutes=DEFAULT_TTL_MINUTES),
        evidence_snapshot=json.dumps(core, ensure_ascii=False, sort_keys=True),
        evidence_hash=compute_evidence_hash(core),
        permissions=json.dumps(_permissions_for_role(new_role)),
    )
    db.add(new_lease)
    db.flush()
    _add_event(db, new_lease, LeaseEventType.ACQUIRE, new_holder, new_role,
               f"主管 {supervisor} 强制转派：{reason}", base_version, new_lease.version)

    clue.assignee = new_holder
    clue.assigned_at = now
    clue.status = ClueStatus.ASSIGNED
    if autocommit:
        db.commit()
        db.refresh(new_lease)
    else:
        db.flush()

    summary = build_evidence_summary(clue, db, new_role, core=core)
    return new_lease, summary


def verify_holder_version(db: Session, clue_id: int, holder: str,
                          lease_version: int, now: Optional[datetime] = None) -> ClueLease:
    """提交核查记录 / 结案前的统一校验：必须持有当前有效租约版本。"""
    now = now or datetime.utcnow()
    lease = current_lease(db, clue_id)
    if lease is None:
        raise LeaseError("线索当前无生效租约，请先认领", 409)
    if lease.holder != holder:
        raise LeaseError(
            f"租约当前由 {lease.holder} 持有，过期/旧版本请求不能覆盖新承办人的工作", 403
        )
    if lease.version != lease_version:
        raise LeaseError(
            f"租约版本不匹配（当前 v{lease.version}，提交 v{lease_version}），请基于最新版本操作", 409
        )
    if lease.expires_at <= now:
        raise LeaseError("租约已超时，提交被拒绝，请重新认领或等待转派", 409)
    return lease


def close_lease_with_conclusion(db: Session, lease: ClueLease, holder: str,
                                role: UserRole, reason: str,
                                autocommit: bool = True) -> None:
    old_version = lease.version
    updated = (
        db.query(ClueLease)
        .filter(
            ClueLease.id == lease.id,
            ClueLease.status == LeaseStatus.ACTIVE,
            ClueLease.version == old_version,
        )
        .update(
            {
                "status": LeaseStatus.CLOSED,
                "released_at": datetime.utcnow(),
                "close_reason": reason,
            },
            synchronize_session=False,
        )
    )
    if updated == 0:
        raise LeaseError("租约状态已变化，结案失败，请刷新后重试", 409)
    db.refresh(lease)
    _add_event(db, lease, LeaseEventType.CLOSE, holder, role, reason,
               old_version, old_version)
    if autocommit:
        db.commit()
    else:
        db.flush()


def recover_expired_leases(db: Optional[Session] = None,
                           now: Optional[datetime] = None,
                           autocommit: bool = True) -> Dict[str, int]:
    """扫描并回收所有到期未续租的租约。条件更新保证重复执行幂等。"""
    now = now or datetime.utcnow()
    own_session = db is None
    if own_session:
        from .database import SessionLocal
        db = SessionLocal()
    recovered = 0
    try:
        stale_rows = (
            db.query(ClueLease)
            .filter(ClueLease.status == LeaseStatus.ACTIVE, ClueLease.expires_at <= now)
            .order_by(ClueLease.id)
            .all()
        )
        for stale in stale_rows:
            result = _expire_if_needed(
                db, stale.clue_id, now, autocommit,
                reason="租约超时未续租，恢复任务自动回收",
            )
            if result is not None:
                recovered += 1
        return {"scanned": len(stale_rows), "recovered": recovered}
    finally:
        if own_session:
            db.close()


# ---------------------------------------------------------------------------
# 序列化辅助
# ---------------------------------------------------------------------------

def lease_to_dict(lease: ClueLease, summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {
        "lease_id": lease.id,
        "clue_id": lease.clue_id,
        "version": lease.version,
        "holder": lease.holder,
        "holder_role": lease.holder_role.value if lease.holder_role else None,
        "status": lease.status.value if lease.status else None,
        "acquired_at": lease.acquired_at,
        "expires_at": lease.expires_at,
        "renewed_at": lease.renewed_at,
        "released_at": lease.released_at,
        "evidence_hash": lease.evidence_hash,
        "permissions": json.loads(lease.permissions or "[]"),
        "close_reason": lease.close_reason,
    }
    if summary is not None:
        data["evidence_summary"] = summary
    return data


def event_to_dict(event: LeaseEvent) -> Dict[str, Any]:
    return {
        "event_id": event.id,
        "lease_id": event.lease_id,
        "clue_id": event.clue_id,
        "event_type": event.event_type.value if event.event_type else None,
        "actor": event.actor,
        "actor_role": event.actor_role.value if event.actor_role else None,
        "from_version": event.from_version,
        "to_version": event.to_version,
        "reason": event.reason,
        "created_at": event.created_at,
    }


def list_lease_events(db: Session, clue_id: int) -> List[LeaseEvent]:
    return (
        db.query(LeaseEvent)
        .filter(LeaseEvent.clue_id == clue_id)
        .order_by(LeaseEvent.id)
        .all()
    )


# ---------------------------------------------------------------------------
# 服务重启后的后台恢复
# ---------------------------------------------------------------------------

class LeaseReaper:
    """守护线程：周期性回收超时租约；单次扫描天然幂等。"""

    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        # 启动时先执行一次，覆盖服务停机期间超时的租约
        self.run_once()
        if self.interval_seconds > 0:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="lease-reaper")
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.run_once()

    def run_once(self) -> None:
        try:
            recover_expired_leases()
        except Exception:  # 回收失败不应影响主服务
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
