from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import Institution, InstitutionLicense, InstitutionType
from .. import schemas

router = APIRouter()


@router.post("/", response_model=schemas.Institution)
def create_institution(institution: schemas.InstitutionCreate, db: Session = Depends(get_db)):
    existing = db.query(Institution).filter(
        Institution.unified_social_code == institution.unified_social_code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="统一社会信用代码已存在")
    db_institution = Institution(**institution.model_dump())
    db.add(db_institution)
    db.commit()
    db.refresh(db_institution)
    return db_institution


@router.get("/", response_model=List[schemas.Institution])
def list_institutions(
    skip: int = 0,
    limit: int = 100,
    institution_type: Optional[InstitutionType] = None,
    keyword: Optional[str] = Query(None, description="机构名称关键词"),
    db: Session = Depends(get_db)
):
    query = db.query(Institution)
    if institution_type:
        query = query.filter(Institution.institution_type == institution_type)
    if keyword:
        query = query.filter(Institution.name.like(f"%{keyword}%"))
    return query.offset(skip).limit(limit).all()


@router.get("/{institution_id}", response_model=schemas.Institution)
def get_institution(institution_id: int, db: Session = Depends(get_db)):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    return institution


@router.put("/{institution_id}", response_model=schemas.Institution)
def update_institution(
    institution_id: int,
    institution_update: schemas.InstitutionUpdate,
    db: Session = Depends(get_db)
):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    update_data = institution_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(institution, key, value)
    db.commit()
    db.refresh(institution)
    return institution


@router.delete("/{institution_id}")
def delete_institution(institution_id: int, db: Session = Depends(get_db)):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    db.delete(institution)
    db.commit()
    return {"message": "删除成功"}


@router.post("/{institution_id}/licenses", response_model=schemas.InstitutionLicense)
def add_institution_license(
    institution_id: int,
    license_data: schemas.InstitutionLicenseCreate,
    db: Session = Depends(get_db)
):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    existing = db.query(InstitutionLicense).filter(
        InstitutionLicense.license_number == license_data.license_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="许可证编号已存在")
    db_license = InstitutionLicense(**license_data.model_dump())
    db.add(db_license)
    db.commit()
    db.refresh(db_license)
    return db_license


@router.get("/{institution_id}/licenses", response_model=List[schemas.InstitutionLicense])
def list_institution_licenses(institution_id: int, db: Session = Depends(get_db)):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    return institution.licenses


@router.post("/{institution_id}/authorized-procedures", response_model=schemas.InstitutionAuthorizedProcedure)
def authorize_procedure_for_institution(
    institution_id: int,
    auth_data: schemas.InstitutionAuthorizedProcedureCreate,
    db: Session = Depends(get_db)
):
    from ..models import InstitutionAuthorizedProcedure, Procedure
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    procedure = db.query(Procedure).filter(Procedure.id == auth_data.procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")
    existing = db.query(InstitutionAuthorizedProcedure).filter(
        InstitutionAuthorizedProcedure.institution_id == institution_id,
        InstitutionAuthorizedProcedure.procedure_id == auth_data.procedure_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该项目已授权")
    db_auth = InstitutionAuthorizedProcedure(**auth_data.model_dump())
    db.add(db_auth)
    db.commit()
    db.refresh(db_auth)
    from ..schemas import Procedure as ProcedureSchema
    db_auth.procedure = procedure
    return db_auth


@router.get("/{institution_id}/authorized-procedures", response_model=List[schemas.InstitutionAuthorizedProcedure])
def list_institution_authorized_procedures(institution_id: int, db: Session = Depends(get_db)):
    from ..models import InstitutionAuthorizedProcedure
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    auths = db.query(InstitutionAuthorizedProcedure).filter(
        InstitutionAuthorizedProcedure.institution_id == institution_id
    ).all()
    return auths
