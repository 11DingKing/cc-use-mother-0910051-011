from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date

from ..database import get_db
from ..models import (
    Institution, InstitutionLicense, Practitioner, PractitionerQualification,
    QualificationType, InstitutionAuthorizedProcedure,
    PractitionerAuthorizedProcedure, Procedure, ActualProcedureRecord,
    ViolationClue, ClueStatus, ClueType
)
from .. import schemas
from ..compliance_utils import (
    check_institution_license_valid,
    check_practitioner_qualification_valid,
    check_practitioner_core_qualifications,
    judge_over_range_practice,
    count_unlicensed_practitioners,
    create_over_range_clue,
    recalculate_all_over_range_records
)

router = APIRouter()


@router.get("/institution/{institution_id}", response_model=schemas.InstitutionComplianceCheck)
def check_institution_compliance(institution_id: int, db: Session = Depends(get_db)):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")

    has_valid_license, license_detail, _ = check_institution_license_valid(db, institution_id)

    authorized_count = db.query(InstitutionAuthorizedProcedure).filter(
        InstitutionAuthorizedProcedure.institution_id == institution_id
    ).count()

    actual_records = db.query(ActualProcedureRecord).filter(
        ActualProcedureRecord.institution_id == institution_id
    ).all()

    over_range_count = sum(1 for r in actual_records if r.is_over_range)

    unlicensed_count, total_practitioners = count_unlicensed_practitioners(db, institution_id)

    clues_count = db.query(ViolationClue).filter(
        ViolationClue.institution_id == institution_id
    ).count()

    verified_count = db.query(ViolationClue).filter(
        ViolationClue.institution_id == institution_id,
        ViolationClue.status == ClueStatus.VERIFIED
    ).count()

    return schemas.InstitutionComplianceCheck(
        institution_id=institution.id,
        institution_name=institution.name,
        has_valid_license=has_valid_license,
        license_detail=license_detail,
        authorized_procedure_count=authorized_count,
        actual_procedure_count=len(actual_records),
        over_range_count=over_range_count,
        unlicensed_practitioners=unlicensed_count,
        total_practitioners=total_practitioners,
        clues_count=clues_count,
        verified_violations=verified_count
    )


@router.get("/practitioner/{practitioner_id}", response_model=schemas.PractitionerComplianceCheck)
def check_practitioner_compliance(practitioner_id: int, db: Session = Depends(get_db)):
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")

    has_doctor, _ = check_practitioner_qualification_valid(
        db, practitioner_id, QualificationType.DOCTOR
    )
    has_practice, _ = check_practitioner_qualification_valid(
        db, practitioner_id, QualificationType.PRACTICE
    )
    has_cosmetology, _ = check_practitioner_qualification_valid(
        db, practitioner_id, QualificationType.COSMETOLOGY
    )

    authorized_procs = db.query(PractitionerAuthorizedProcedure).filter(
        PractitionerAuthorizedProcedure.practitioner_id == practitioner_id
    ).all()
    authorized_names = [ap.procedure.name for ap in authorized_procs if ap.procedure]

    actual_records = db.query(ActualProcedureRecord).filter(
        ActualProcedureRecord.practitioner_id == practitioner_id
    ).all()
    actual_names = list(set([r.procedure.name for r in actual_records if r.procedure]))

    over_range_names = list(set([
        r.procedure.name for r in actual_records
        if r.is_over_range and r.procedure
    ]))

    core_issues = check_practitioner_core_qualifications(db, practitioner_id)
    is_unlicensed = len(core_issues) > 0

    return schemas.PractitionerComplianceCheck(
        practitioner_id=practitioner.id,
        name=practitioner.name,
        has_valid_doctor_license=has_doctor,
        has_valid_practice_license=has_practice,
        has_cosmetology_license=has_cosmetology,
        authorized_procedures=authorized_names,
        actual_procedures=actual_names,
        over_range_procedures=over_range_names,
        is_unlicensed=is_unlicensed
    )


@router.post("/actual-procedure", response_model=schemas.ActualProcedureRecord)
def record_actual_procedure(
    record_data: schemas.ActualProcedureRecordCreate,
    db: Session = Depends(get_db)
):
    institution = db.query(Institution).filter(
        Institution.id == record_data.institution_id
    ).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")

    practitioner = db.query(Practitioner).filter(
        Practitioner.id == record_data.practitioner_id
    ).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")

    procedure = db.query(Procedure).filter(
        Procedure.id == record_data.procedure_id
    ).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")

    is_over_range, over_range_issues = judge_over_range_practice(
        db,
        record_data.institution_id,
        record_data.practitioner_id,
        record_data.procedure_id,
        record_data.procedure_date
    )
    over_range_details = "; ".join(over_range_issues) if over_range_issues else None

    db_record = ActualProcedureRecord(
        **record_data.model_dump(),
        is_over_range=is_over_range,
        over_range_detail=over_range_details
    )
    db.add(db_record)
    db.commit()
    db.refresh(db_record)

    if is_over_range:
        try:
            create_over_range_clue(
                db,
                record_data.institution_id,
                record_data.practitioner_id,
                record_data.procedure_id,
                db_record.id,
                over_range_issues
            )
        except Exception:
            db.rollback()

    return db_record


@router.get("/actual-procedures", response_model=List[schemas.ActualProcedureRecord])
def list_actual_procedures(
    institution_id: int = None,
    only_over_range: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(ActualProcedureRecord)
    if institution_id:
        query = query.filter(ActualProcedureRecord.institution_id == institution_id)
    if only_over_range:
        query = query.filter(ActualProcedureRecord.is_over_range == True)
    return query.all()


@router.get("/institution/{institution_id}/over-range", response_model=List[schemas.ActualProcedureRecord])
def list_institution_over_range(institution_id: int, db: Session = Depends(get_db)):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    return db.query(ActualProcedureRecord).filter(
        ActualProcedureRecord.institution_id == institution_id,
        ActualProcedureRecord.is_over_range == True
    ).all()


@router.post("/recalculate", tags=["超范围执业重算"])
def recalculate_over_range(db: Session = Depends(get_db)):
    result = recalculate_all_over_range_records(db)
    return {
        "message": "超范围执业判定重算完成",
        "detail": result
    }


@router.get("/check/single", tags=["超范围执业校验"])
def check_single_over_range(
    institution_id: int,
    practitioner_id: int,
    procedure_id: int,
    procedure_date: date = None,
    db: Session = Depends(get_db)
):
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise HTTPException(status_code=404, detail="机构不存在")
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    if not practitioner:
        raise HTTPException(status_code=404, detail="人员不存在")
    procedure = db.query(Procedure).filter(Procedure.id == procedure_id).first()
    if not procedure:
        raise HTTPException(status_code=404, detail="项目不存在")

    is_over_range, issues = judge_over_range_practice(
        db, institution_id, practitioner_id, procedure_id, procedure_date
    )
    return {
        "institution_name": institution.name,
        "practitioner_name": practitioner.name,
        "procedure_name": procedure.name,
        "procedure_date": procedure_date or date.today(),
        "is_over_range": is_over_range,
        "issues": issues
    }
