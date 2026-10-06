from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..models import (
    ViolationClue, InspectionRecord, ClueType, ClueStatus, CluePriority,
    Institution, Practitioner, Procedure,
    ClueLease, ClueLeaseEvent, UserRole, LeaseEventType,
)
from .. import schemas, lease_service
from ..lease_service import LeaseError

router = APIRouter()


def _role(x_user_role: Optional[str]) -> UserRole:
    if not x_user_role:
        return UserRole.INSPECTOR
    for role in UserRole:
        if x_user_role == role.value or x_user_role.upper() == role.name:
            return role
    raise HTTPException(status_code=400, detail=f"未知角色: {x_user_role}")


def _require_supervisor(role: UserRole) -> None:
    if role not in (UserRole.SUPERVISOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="仅主管或管理员可执行该操作")


def _lease_view(lease: ClueLease) -> schemas.ClueLeaseView:
    import json
    perms = json.loads(lease.permissions) if lease.permissions else []
    return schemas.ClueLeaseView(
        id=lease.id, clue_id=lease.clue_id, holder=lease.holder,
        holder_role=lease.holder_role, status=lease.status, version=lease.version,
        leased_at=lease.leased_at, expires_at=lease.expires_at,
        released_at=lease.released_at,
        evidence_summary=lease.evidence_summary, evidence_hash=lease.evidence_hash,
        permissions=perms,
    )


def _get_clue_or_404(db: Session, clue_id: int) -> ViolationClue:
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    return clue


def _raise_lease_error(exc: LeaseError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/", response_model=schemas.ViolationClue)
def create_clue(clue: schemas.ViolationClueCreate, db: Session = Depends(get_db)):
    if clue.institution_id:
        inst = db.query(Institution).filter(Institution.id == clue.institution_id).first()
        if not inst:
            raise HTTPException(status_code=404, detail="关联机构不存在")
    if clue.practitioner_id:
        prac = db.query(Practitioner).filter(Practitioner.id == clue.practitioner_id).first()
        if not prac:
            raise HTTPException(status_code=404, detail="关联人员不存在")
    if clue.procedure_id:
        proc = db.query(Procedure).filter(Procedure.id == clue.procedure_id).first()
        if not proc:
            raise HTTPException(status_code=404, detail="关联项目不存在")
    db_clue = ViolationClue(**clue.model_dump())
    db.add(db_clue)
    db.commit()
    db.refresh(db_clue)
    return db_clue


@router.get("/", response_model=List[schemas.ViolationClue])
def list_clues(
    skip: int = 0,
    limit: int = 100,
    clue_type: Optional[ClueType] = None,
    status: Optional[ClueStatus] = None,
    priority: Optional[CluePriority] = None,
    institution_id: Optional[int] = None,
    assignee: Optional[str] = Query(None, description="分派给"),
    db: Session = Depends(get_db)
):
    query = db.query(ViolationClue)
    if clue_type:
        query = query.filter(ViolationClue.clue_type == clue_type)
    if status:
        query = query.filter(ViolationClue.status == status)
    if priority:
        query = query.filter(ViolationClue.priority == priority)
    if institution_id:
        query = query.filter(ViolationClue.institution_id == institution_id)
    if assignee:
        query = query.filter(ViolationClue.assignee == assignee)
    return query.order_by(ViolationClue.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/types/list", tags=["线索类型枚举"])
def list_clue_types():
    return {
        "clue_types": [e.value for e in ClueType],
        "statuses": [e.value for e in ClueStatus],
        "priorities": [e.value for e in CluePriority]
    }


@router.get("/{clue_id}", response_model=schemas.ClueDetailView)
def get_clue(
    clue_id: int,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None),
):
    """线索详情：举报人字段按 X-User-Role 裁剪，并附当前租约与生命周期事件。"""
    role = _role(x_user_role)
    clue = _get_clue_or_404(db, clue_id)
    events = db.query(ClueLeaseEvent).filter(
        ClueLeaseEvent.clue_id == clue_id
    ).order_by(ClueLeaseEvent.created_at.desc(), ClueLeaseEvent.id.desc()).all()
    active = lease_service.get_active_lease(db, clue_id)
    detail = schemas.ClueDetailView.model_validate(clue)
    detail.informant = lease_service.informant_view(clue, role)
    detail.events = [schemas.ClueLeaseEventView.model_validate(e) for e in events]
    detail.current_lease = _lease_view(active) if active else None
    return detail


@router.put("/{clue_id}", response_model=schemas.ViolationClue)
def update_clue(
    clue_id: int,
    clue_update: schemas.ViolationClueUpdate,
    db: Session = Depends(get_db)
):
    clue = _get_clue_or_404(db, clue_id)
    update_data = clue_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(clue, key, value)
    db.commit()
    db.refresh(clue)
    return clue


@router.delete("/{clue_id}")
def delete_clue(clue_id: int, db: Session = Depends(get_db)):
    clue = _get_clue_or_404(db, clue_id)
    db.delete(clue)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{clue_id}/assign", response_model=schemas.ViolationClue)
def assign_clue(
    clue_id: int,
    assign_data: schemas.ClueAssign,
    db: Session = Depends(get_db)
):
    """旧分派接口（兼容）：分派同时建立一条认领租约。

    若该线索已存在他人有效租约则拒绝，避免分派覆盖正在进行的核查。
    """
    clue = _get_clue_or_404(db, clue_id)
    active = lease_service.get_active_lease(db, clue_id)
    if active and active.holder != assign_data.assignee:
        raise HTTPException(status_code=409,
                            detail=f"线索已被 {active.holder} 认领，不能重复分派")
    if not active:
        try:
            lease_service.claim_lease(
                db, clue,
                holder=assign_data.assignee,
                holder_role=assign_data.assignee_role,
                ttl_minutes=assign_data.ttl_minutes or lease_service.DEFAULT_LEASE_TTL_MINUTES,
                reason=assign_data.reason or "主管分派建立租约",
            )
        except LeaseError as exc:
            _raise_lease_error(exc)
    db.refresh(clue)
    return clue


@router.post("/{clue_id}/conclude", response_model=schemas.ViolationClue)
def conclude_clue(
    clue_id: int,
    conclusion_data: schemas.ClueConclusion,
    db: Session = Depends(get_db)
):
    clue = _get_clue_or_404(db, clue_id)
    if conclusion_data.status not in [ClueStatus.VERIFIED, ClueStatus.DISMISSED]:
        raise HTTPException(status_code=400, detail="结论状态只能为已核实违规或已排除")

    if conclusion_data.lease_id is not None and conclusion_data.lease_version is not None:
        # 严格模式：必须持有当前版本的有效租约，过期/被转派后的迟到请求一律拒绝
        holder = conclusion_data.holder or ""
        try:
            lease = lease_service.require_active_lease(
                db, clue_id, conclusion_data.lease_id,
                holder=holder, expected_version=conclusion_data.lease_version,
            )
            lease_service.complete_lease(db, lease, actor=holder,
                                        reason="提交核查结论，租约随结案终结")
        except LeaseError as exc:
            _raise_lease_error(exc)
    else:
        # 兼容旧调用：存在有效租约时随结案终结，租约失效则拒绝迟到结案
        active = lease_service.get_active_lease(db, clue_id)
        if active is not None:
            now = datetime.utcnow()
            if active.expires_at <= now:
                lease_service.expire_lease_if_due(db, active, now)
                db.commit()
                raise HTTPException(status_code=409,
                                    detail="当前租约已过期回收，请重新认领后再结案")
            actor = conclusion_data.holder or active.holder
            lease_service.complete_lease(db, active, actor=actor,
                                         reason="提交核查结论，租约随结案终结")

    clue.status = conclusion_data.status
    clue.conclusion = conclusion_data.conclusion
    clue.verified_at = datetime.utcnow()
    db.commit()
    db.refresh(clue)
    return clue


@router.post("/{clue_id}/inspections", response_model=schemas.InspectionRecord)
def add_inspection_record(
    clue_id: int,
    inspection_data: schemas.InspectionRecordCreate,
    db: Session = Depends(get_db)
):
    clue = _get_clue_or_404(db, clue_id)

    active = lease_service.get_active_lease(db, clue_id)
    if active is not None:
        # 线索已被认领：提交人必须是当前租约持有人，且租约未过期
        if active.holder != inspection_data.inspector:
            raise HTTPException(
                status_code=409,
                detail=f"线索当前由 {active.holder} 持有，{inspection_data.inspector} 不能提交核查记录",
            )
        if active.expires_at <= datetime.utcnow():
            lease_service.expire_lease_if_due(db, active, datetime.utcnow())
            db.commit()
            raise HTTPException(status_code=409, detail="租约已过期回收，请重新认领后再提交")
        if inspection_data.lease_id is not None:
            # 显式携带版本凭证时做版本闸门，挡住迟到请求覆盖新承办人的工作
            if inspection_data.lease_id != active.id:
                raise HTTPException(status_code=409, detail="租约编号不匹配，承办人可能已变更")
            if inspection_data.lease_version != active.version:
                raise HTTPException(
                    status_code=409,
                    detail=f"租约版本过期：请求版本 {inspection_data.lease_version}，"
                           f"当前版本 {active.version}",
                )

    payload = inspection_data.model_dump(exclude={"lease_id", "lease_version"})
    payload["clue_id"] = clue_id
    db_inspection = InspectionRecord(**payload)
    db.add(db_inspection)
    db.commit()
    db.refresh(db_inspection)
    return db_inspection


@router.get("/{clue_id}/inspections", response_model=List[schemas.InspectionRecord])
def list_inspection_records(clue_id: int, db: Session = Depends(get_db)):
    _get_clue_or_404(db, clue_id)
    return db.query(InspectionRecord).filter(
        InspectionRecord.clue_id == clue_id
    ).order_by(InspectionRecord.inspection_date.desc()).all()


# ===================== 认领租约 =====================

@router.post("/{clue_id}/leases/claim", response_model=schemas.ClueLeaseView)
def claim_clue_lease(
    clue_id: int,
    body: schemas.ClueLeaseRequest,
    db: Session = Depends(get_db),
):
    """认领线索，领取时固定可见证据摘要、证据哈希与办理权限。"""
    clue = _get_clue_or_404(db, clue_id)
    try:
        lease = lease_service.claim_lease(
            db, clue, holder=body.holder, holder_role=body.holder_role,
            ttl_minutes=body.ttl_minutes or lease_service.DEFAULT_LEASE_TTL_MINUTES,
            reason=body.reason or "",
        )
    except LeaseError as exc:
        _raise_lease_error(exc)
    return _lease_view(lease)


@router.get("/{clue_id}/leases/active", response_model=schemas.ClueLeaseView)
def get_active_clue_lease(clue_id: int, db: Session = Depends(get_db)):
    _get_clue_or_404(db, clue_id)
    lease = lease_service.get_active_lease(db, clue_id)
    if lease is None:
        raise HTTPException(status_code=404, detail="线索当前无有效租约")
    return _lease_view(lease)


@router.post("/{clue_id}/leases/renew", response_model=schemas.ClueLeaseView)
def renew_clue_lease(
    clue_id: int,
    body: schemas.ClueLeaseRenew,
    db: Session = Depends(get_db),
):
    _get_clue_or_404(db, clue_id)
    try:
        lease = lease_service.renew_lease(
            db, clue_id, body.lease_id,
            holder=body.holder, expected_version=body.version,
            ttl_minutes=body.ttl_minutes or lease_service.DEFAULT_LEASE_TTL_MINUTES,
            reason=body.reason,
        )
    except LeaseError as exc:
        _raise_lease_error(exc)
    return _lease_view(lease)


@router.post("/{clue_id}/leases/release", response_model=schemas.ClueLeaseView)
def release_clue_lease(
    clue_id: int,
    body: schemas.ClueLeaseRelease,
    db: Session = Depends(get_db),
):
    _get_clue_or_404(db, clue_id)
    try:
        lease = lease_service.release_lease(
            db, clue_id, body.lease_id,
            holder=body.holder, expected_version=body.version, reason=body.reason,
        )
    except LeaseError as exc:
        _raise_lease_error(exc)
    return _lease_view(lease)


@router.post("/{clue_id}/leases/reassign", response_model=schemas.ClueLeaseView)
def reassign_clue_lease(
    clue_id: int,
    body: schemas.ClueLeaseReassign,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None),
):
    """主管强制转派，必须填写原因；原租约与新租约均留痕。"""
    _require_supervisor(_role(x_user_role))
    clue = _get_clue_or_404(db, clue_id)
    try:
        lease = lease_service.reassign_lease(
            db, clue,
            supervisor=body.supervisor, to_holder=body.to_holder,
            to_role=body.to_role, reason=body.reason,
        )
    except LeaseError as exc:
        _raise_lease_error(exc)
    return _lease_view(lease)


@router.get("/{clue_id}/events", response_model=List[schemas.ClueLeaseEventView])
def list_clue_lease_events(clue_id: int, db: Session = Depends(get_db)):
    _get_clue_or_404(db, clue_id)
    return db.query(ClueLeaseEvent).filter(
        ClueLeaseEvent.clue_id == clue_id
    ).order_by(ClueLeaseEvent.created_at.desc(), ClueLeaseEvent.id.desc()).all()


@router.post("/leases/recover-expired", response_model=schemas.LeaseRecoverResult)
def recover_expired_leases(
    payload: schemas.LeaseRecoverRequest,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None),
):
    """超时回收（服务启动恢复 / 定时任务入口）。

    条件 UPDATE + 同事务事件保证幂等：重复执行、服务重启后再执行，
    同一条租约只产生一次回收、至多一次转派。
    """
    role = _role(x_user_role)
    # 系统恢复任务允许以主管/管理员身份调用
    _require_supervisor(role)
    result = lease_service.recover_expired_leases(
        db,
        auto_reassign_to=payload.auto_reassign_to,
        reason=payload.reason,
    )
    return result
