from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import Procedure, ProcedureCategory, SurgeryLevel
from .. import schemas

router = APIRouter()


@router.post("/", response_model=schemas.Procedure)
def create_procedure(procedure: schemas.ProcedureCreate, db: Session = Depends(get_db)):
    existing = db.query(Procedure).filter(Procedure.name == procedure.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="项目名称已存在")
    existing_code = db.query(Procedure).filter(
        Procedure.code == procedure.code
    ).first()
    if existing_code:
        raise HTTPException(status_code=400, detail="项目编码已存在")
    db_procedure = Procedure(**procedure.model_dump())
    db.add(db_procedure)
    db.commit()
    db.refresh(db_procedure)
    return db_procedure


@router.get("/", response_model=List[schemas.Procedure])
def list_procedures(
    skip: int = 0,
    limit: int = 100,
    category: Optional[ProcedureCategory] = None,
    surgery_level: Optional[SurgeryLevel] = None,
    keyword: Optional[str] = Query(None, description="项目名称关键词"),
    db: Session = Depends(get_db)
):
    query = db.query(Procedure)
    if category:
        query = query.filter(Procedure.category == category)
    if surgery_level:
        query = query.filter(Procedure.surgery_level == surgery_level)
    if keyword:
        query = query.filter(Procedure.name.like(f"%{keyword}%"))
    return query.offset(skip).limit(limit).all()


@router.get("/{procedure_id}", response_model=schemas.Procedure)
def get_procedure(procedure_id: int, db: Session = Depends(get_db)):
    procedure = db.query(Procedure).filter(Procedure.id == procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")
    return procedure


@router.put("/{procedure_id}", response_model=schemas.Procedure)
def update_procedure(
    procedure_id: int,
    procedure_update: schemas.ProcedureUpdate,
    db: Session = Depends(get_db)
):
    procedure = db.query(Procedure).filter(Procedure.id == procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")
    update_data = procedure_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(procedure, key, value)
    db.commit()
    db.refresh(procedure)
    return procedure


@router.delete("/{procedure_id}")
def delete_procedure(procedure_id: int, db: Session = Depends(get_db)):
    procedure = db.query(Procedure).filter(Procedure.id == procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(procedure)
    db.commit()
    return {"message": "删除成功"}


@router.get("/categories/list", tags=["项目分级枚举"])
def list_categories():
    return {
        "categories": [e.value for e in ProcedureCategory],
        "surgery_levels": [e.value for e in SurgeryLevel]
    }
