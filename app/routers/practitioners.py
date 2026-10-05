from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import Practitioner, PractitionerQualification, QualificationType
from .. import schemas

router = APIRouter()


@router.post("/", response_model=schemas.Practitioner)
def create_practitioner(practitioner: schemas.PractitionerCreate, db: Session = Depends(get_db)):
    existing = db.query(Practitioner).filter(
        Practitioner.id_card == practitioner.id_card
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="身份证号已存在")
    db_practitioner = Practitioner(**practitioner.model_dump())
    db.add(db_practitioner)
    db.commit()
    db.refresh(db_practitioner)
    return db_practitioner


@router.get("/", response_model=List[schemas.Practitioner])
def list_practitioners(
    skip: int = 0,
    limit: int = 100,
    institution_id: Optional[int] = None,
    keyword: Optional[str] = Query(None, description="姓名关键词"),
    db: Session = Depends(get_db)
):
    query = db.query(Practitioner)
    if institution_id:
        query = query.filter(Practitioner.institution_id == institution_id)
    if keyword:
        query = query.filter(Practitioner.name.like(f"%{keyword}%"))
    return query.offset(skip).limit(limit).all()


@router.get("/{practitioner_id}", response_model=schemas.PractitionerWithQualifications)
def get_practitioner(practitioner_id: int, db: Session = Depends(get_db)):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    return practitioner


@router.put("/{practitioner_id}", response_model=schemas.Practitioner)
def update_practitioner(
    practitioner_id: int,
    practitioner_update: schemas.PractitionerUpdate,
    db: Session = Depends(get_db)
):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    update_data = practitioner_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(practitioner, key, value)
    db.commit()
    db.refresh(practitioner)
    return practitioner


@router.delete("/{practitioner_id}")
def delete_practitioner(practitioner_id: int, db: Session = Depends(get_db)):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    db.delete(practitioner)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{practitioner_id}/qualifications", response_model=schemas.PractitionerQualification)
def add_qualification(
    practitioner_id: int,
    qual_data: schemas.PractitionerQualificationCreate,
    db: Session = Depends(get_db)
):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    existing = db.query(PractitionerQualification).filter(
        PractitionerQualification.certificate_number == qual_data.certificate_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="证书编号已存在")
    db_qual = PractitionerQualification(**qual_data.model_dump())
    db.add(db_qual)
    db.commit()
    db.refresh(db_qual)
    return db_qual


@router.get("/{practitioner_id}/qualifications", response_model=List[schemas.PractitionerQualification])
def list_qualifications(practitioner_id: int, db: Session = Depends(get_db)):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    return practitioner.qualifications


@router.post("/{practitioner_id}/authorized-procedures", response_model=schemas.PractitionerAuthorizedProcedure)
def authorize_procedure_for_practitioner(
    practitioner_id: int,
    auth_data: schemas.PractitionerAuthorizedProcedureCreate,
    db: Session = Depends(get_db)
):
    from ..models import PractitionerAuthorizedProcedure, Procedure
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    procedure = db.query(Procedure).filter(Procedure.id == auth_data.procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")
    existing = db.query(PractitionerAuthorizedProcedure).filter(
        PractitionerAuthorizedProcedure.practitioner_id == practitioner_id,
        PractitionerAuthorizedProcedure.procedure_id == auth_data.procedure_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该项目已授权")
    db_auth = PractitionerAuthorizedProcedure(**auth_data.model_dump())
    db.add(db_auth)
    db.commit()
    db.refresh(db_auth)
    db_auth.procedure = procedure
    return db_auth


@router.get("/{practitioner_id}/authorized-procedures", response_model=List[schemas.PractitionerAuthorizedProcedure])
def list_practitioner_authorized_procedures(practitioner_id: int, db: Session = Depends(get_db)):
    from ..models import PractitionerAuthorizedProcedure
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    auths = db.query(PractitionerAuthorizedProcedure).filter(
        PractitionerAuthorizedProcedure.practitioner_id == practitioner_id
    ).all()
    return auths
