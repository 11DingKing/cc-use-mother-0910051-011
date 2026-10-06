from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime

from ..database import get_db
from ..models import (
    ViolationClue, InspectionRecord, ClueType, ClueStatus, CluePriority,
    Institution, Practitioner, Procedure, UserRole,
)
from .. import schemas
from .. import lease_service
from ..lease_service import LeaseError

router = APIRouter()


# ---------------------------------------------------------------------------
# 角色与序列化辅助
# ---------------------------------------------------------------------------

def _parse_role(role_value: Optional[str]) -> UserRole:
    """优先按枚举中文值解析，其次按成员名解析；缺省为最小权限的核查员。"""
    if not role_value:
        return UserRole.INVESTIGATOR
    for role in UserRole:
        if role.value == role_value or role.name == role_value.upper():
            return role
    raise HTTPException(status_code=400, detail=f"未知角色：{role_value}")


_CLUE_FIELDS = [
    "id", "clue_type", "title", "description",
    "institution_id", "practitioner_id", "procedure_id",
    "source", "priority", "status", "assignee", "assigned_at",
    "conclusion", "verified_at", "created_at", "updated_at",
]


def _clue_out(clue: ViolationClue, db: Session, role: UserRole) -> Dict[str, Any]:
    payload = {f: getattr(clue, f) for f in _CLUE_FIELDS}
    # 举报人敏感字段按角色裁剪后随线索返回，原始列不下发
    payload["reporter"] = lease_service.trim_reporter(clue, role)
    return payload


def _lease_error(exc: LeaseError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=str(exc))


def _get_clue_or_404(db: Session, clue_id: int) -> ViolationClue:
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    return clue


def _enforce_lease_or_legacy(db: Session, clue: ViolationClue,
                             holder: Optional[str], lease_version: Optional[int]):
    """新流程必须持有当前租约版本；旧的直接分派流程（无租约）保持兼容。"""
    if holder is None and lease_version is None:
        if lease_service.current_lease(db, clue.id) is not None:
            raise HTTPException(
                status_code=409,
                detail="该线索已启用认领租约，提交时必须携带 holder 与 lease_version",
            )
        return None
    if holder is None or lease_version is None:
        raise HTTPException(status_code=400, detail="必须同时提交 holder 与 lease_version")
    try:
        return lease_service.verify_holder_version(db, clue.id, holder, lease_version)
    except LeaseError as e:
        raise _lease_error(e)


# ---------------------------------------------------------------------------
# 线索基础接口
# ---------------------------------------------------------------------------

@router.post("/", response_model=schemas.ViolationClue)
def create_clue(clue: schemas.ViolationClueCreate, db: Session = Depends(get_db),
                x_user_role: Optional[str] = Header(None)):
    role = _parse_role(x_user_role)
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
    return _clue_out(db_clue, db, role)


@router.get("/", response_model=List[schemas.ViolationClue])
def list_clues(
    skip: int = 0,
    limit: int = 100,
    clue_type: Optional[ClueType] = None,
    status: Optional[ClueStatus] = None,
    priority: Optional[CluePriority] = None,
    institution_id: Optional[int] = None,
    assignee: Optional[str] = Query(None, description="分派给"),
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
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
    clues = query.order_by(ViolationClue.created_at.desc()).offset(skip).limit(limit).all()
    return [_clue_out(c, db, role) for c in clues]


@router.get("/types/list", tags=["线索类型枚举"])
def list_clue_types():
    return {
        "clue_types": [e.value for e in ClueType],
        "statuses": [e.value for e in ClueStatus],
        "priorities": [e.value for e in CluePriority],
        "roles": [e.value for e in UserRole],
    }


@router.post("/leases/recover", tags=["认领租约"])
def trigger_recover_expired_leases(db: Session = Depends(get_db)):
    """手动触发超时回收（恢复任务同样调用此逻辑），重复执行幂等。"""
    return lease_service.recover_expired_leases(db, autocommit=True)


@router.get("/{clue_id}", response_model=schemas.ViolationClue)
def get_clue(clue_id: int, db: Session = Depends(get_db),
             x_user_role: Optional[str] = Header(None)):
    role = _parse_role(x_user_role)
    clue = _get_clue_or_404(db, clue_id)
    return _clue_out(clue, db, role)


@router.put("/{clue_id}", response_model=schemas.ViolationClue)
def update_clue(
    clue_id: int,
    clue_update: schemas.ViolationClueUpdate,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
    clue = _get_clue_or_404(db, clue_id)
    update_data = clue_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(clue, key, value)
    db.commit()
    db.refresh(clue)
    return _clue_out(clue, db, role)


@router.delete("/{clue_id}")
def delete_clue(clue_id: int, db: Session = Depends(get_db)):
    clue = _get_clue_or_404(db, clue_id)
    db.delete(clue)
    db.commit()
    return {"message": "删除成功"}


# ---------------------------------------------------------------------------
# 旧版直接分派（保留兼容；新流程使用认领租约）
# ---------------------------------------------------------------------------

@router.post("/{clue_id}/assign", response_model=schemas.ViolationClue)
def assign_clue(
    clue_id: int,
    assign_data: schemas.ClueAssign,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
    clue = _get_clue_or_404(db, clue_id)
    clue.assignee = assign_data.assignee
    clue.assigned_at = datetime.utcnow()
    clue.status = ClueStatus.ASSIGNED
    db.commit()
    db.refresh(clue)
    return _clue_out(clue, db, role)


# ---------------------------------------------------------------------------
# 认领租约接口
# ---------------------------------------------------------------------------

@router.post("/{clue_id}/leases/acquire", response_model=schemas.LeaseView, tags=["认领租约"])
def acquire_clue_lease(
    clue_id: int,
    body: schemas.LeaseAcquire,
    db: Session = Depends(get_db)
):
    try:
        lease, summary = lease_service.acquire_lease(
            db, clue_id, body.holder, body.role,
            ttl_minutes=body.ttl_minutes, reason=body.reason,
        )
    except LeaseError as e:
        raise _lease_error(e)
    return lease_service.lease_to_dict(lease, summary)


@router.post("/{clue_id}/leases/renew", response_model=schemas.LeaseView, tags=["认领租约"])
def renew_clue_lease(
    clue_id: int,
    body: schemas.LeaseRenew,
    db: Session = Depends(get_db)
):
    try:
        lease, summary = lease_service.renew_lease(
            db, clue_id, body.holder, body.role,
            lease_version=body.version, reason=body.reason,
            ttl_minutes=body.ttl_minutes,
        )
    except LeaseError as e:
        raise _lease_error(e)
    return lease_service.lease_to_dict(lease, summary)


@router.post("/{clue_id}/leases/release", tags=["认领租约"])
def release_clue_lease(
    clue_id: int,
    body: schemas.LeaseRelease,
    db: Session = Depends(get_db)
):
    try:
        lease = lease_service.release_lease(
            db, clue_id, body.holder, body.role,
            lease_version=body.version, reason=body.reason,
        )
    except LeaseError as e:
        raise _lease_error(e)
    return {
        "message": "租约已释放，线索回到待分派池",
        "lease": lease_service.lease_to_dict(lease),
    }


@router.post("/{clue_id}/leases/force-assign", response_model=schemas.LeaseView, tags=["认领租约"])
def force_assign_clue_lease(
    clue_id: int,
    body: schemas.LeaseForceAssign,
    db: Session = Depends(get_db)
):
    try:
        lease, summary = lease_service.force_assign(
            db, clue_id, body.supervisor, body.supervisor_role,
            new_holder=body.new_holder, reason=body.reason,
            new_holder_role=body.new_holder_role,
            expected_version=body.expected_version,
        )
    except LeaseError as e:
        raise _lease_error(e)
    return lease_service.lease_to_dict(lease, summary)


@router.get("/{clue_id}/leases/current", response_model=Optional[schemas.LeaseView], tags=["认领租约"])
def get_current_lease(
    clue_id: int,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
    _get_clue_or_404(db, clue_id)
    lease = lease_service.current_lease(db, clue_id)
    if lease is None:
        return None
    view = lease_service.lease_to_dict(lease)
    # 证据摘要同样按角色裁剪举报人字段
    core = None
    try:
        import json as _json
        core = _json.loads(lease.evidence_snapshot)
    except (ValueError, TypeError):
        core = None
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if core is not None:
        view["evidence_summary"] = lease_service.build_evidence_summary(clue, db, role, core=core)
    return view


@router.get("/{clue_id}/leases/events", response_model=List[schemas.LeaseEventView], tags=["认领租约"])
def get_lease_events(
    clue_id: int,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
    if role not in (UserRole.SUPERVISOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="仅主管可查看租约审计记录")
    _get_clue_or_404(db, clue_id)
    events = lease_service.list_lease_events(db, clue_id)
    return [lease_service.event_to_dict(e) for e in events]


# ---------------------------------------------------------------------------
# 结案与核查记录（必须持有当前租约版本）
# ---------------------------------------------------------------------------

@router.post("/{clue_id}/conclude", response_model=schemas.ViolationClue)
def conclude_clue(
    clue_id: int,
    conclusion_data: schemas.ClueConclusion,
    db: Session = Depends(get_db),
    x_user_role: Optional[str] = Header(None)
):
    role = _parse_role(x_user_role)
    clue = _get_clue_or_404(db, clue_id)
    if conclusion_data.status not in [ClueStatus.VERIFIED, ClueStatus.DISMISSED]:
        raise HTTPException(status_code=400, detail="结论状态只能为已核实违规或已排除")

    lease = _enforce_lease_or_legacy(db, clue, conclusion_data.holder, conclusion_data.lease_version)

    clue.status = conclusion_data.status
    clue.conclusion = conclusion_data.conclusion
    clue.verified_at = datetime.utcnow()
    if lease is not None:
        try:
            lease_service.close_lease_with_conclusion(
                db, lease, conclusion_data.holder, role,
                reason=f"结案（{conclusion_data.status.value}）：{conclusion_data.conclusion}",
                autocommit=False,
            )
        except LeaseError as e:
            raise _lease_error(e)
    db.commit()
    db.refresh(clue)
    return _clue_out(clue, db, role)


@router.post("/{clue_id}/inspections", response_model=schemas.InspectionRecord)
def add_inspection_record(
    clue_id: int,
    inspection_data: schemas.InspectionRecordCreate,
    db: Session = Depends(get_db)
):
    clue = _get_clue_or_404(db, clue_id)
    lease = _enforce_lease_or_legacy(
        db, clue, inspection_data.holder, inspection_data.lease_version
    )
    if lease is not None and inspection_data.inspector != inspection_data.holder:
        raise HTTPException(status_code=403, detail="核查记录提交人必须与租约持有人一致")
    data = inspection_data.model_dump(exclude={"holder", "lease_version", "role"})
    db_inspection = InspectionRecord(**data)
    db.add(db_inspection)
    db.commit()
    db.refresh(db_inspection)
    return db_inspection


@router.get("/{clue_id}/inspections", response_model=List[schemas.InspectionRecord])
def list_inspection_records(clue_id: int, db: Session = Depends(get_db)):
    clue = _get_clue_or_404(db, clue_id)
    return clue.inspection_records
