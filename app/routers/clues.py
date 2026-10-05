from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..models import (
    ViolationClue, InspectionRecord, ClueType, ClueStatus, CluePriority,
    Institution, Practitioner, Procedure
)
from .. import schemas

router = APIRouter()


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


@router.get("/{clue_id}", response_model=schemas.ViolationClue)
def get_clue(clue_id: int, db: Session = Depends(get_db)):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    return clue


@router.put("/{clue_id}", response_model=schemas.ViolationClue)
def update_clue(
    clue_id: int,
    clue_update: schemas.ViolationClueUpdate,
    db: Session = Depends(get_db)
):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    update_data = clue_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(clue, key, value)
    db.commit()
    db.refresh(clue)
    return clue


@router.delete("/{clue_id}")
def delete_clue(clue_id: int, db: Session = Depends(get_db)):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    db.delete(clue)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{clue_id}/assign", response_model=schemas.ViolationClue)
def assign_clue(
    clue_id: int,
    assign_data: schemas.ClueAssign,
    db: Session = Depends(get_db)
):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    clue.assignee = assign_data.assignee
    clue.assigned_at = datetime.utcnow()
    clue.status = ClueStatus.ASSIGNED
    db.commit()
    db.refresh(clue)
    return clue


@router.post("/{clue_id}/conclude", response_model=schemas.ViolationClue)
def conclude_clue(
    clue_id: int,
    conclusion_data: schemas.ClueConclusion,
    db: Session = Depends(get_db)
):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    if conclusion_data.status not in [ClueStatus.VERIFIED, ClueStatus.DISMISSED]:
        raise HTTPException(status_code=400, detail="结论状态只能为已核实违规或已排除")
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
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    db_inspection = InspectionRecord(**inspection_data.model_dump())
    db.add(db_inspection)
    db.commit()
    db.refresh(db_inspection)
    return db_inspection


@router.get("/{clue_id}/inspections", response_model=List[schemas.InspectionRecord])
def list_inspection_records(clue_id: int, db: Session = Depends(get_db)):
    clue = db.query(ViolationClue).filter(ViolationClue.id == clue_id).first()
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    return clue.inspection_records


@router.get("/types/list", tags=["线索类型枚举"])
def list_clue_types():
    return {
        "clue_types": [e.value for e in ClueType],
        "statuses": [e.value for e in ClueStatus],
        "priorities": [e.value for e in CluePriority]
    }
