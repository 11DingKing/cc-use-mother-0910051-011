from sqlalchemy.orm import Session
from datetime import date
from typing import List, Tuple, Optional

from .models import (
    InstitutionLicense, PractitionerQualification, QualificationType,
    InstitutionAuthorizedProcedure, PractitionerAuthorizedProcedure,
    Procedure, ActualProcedureRecord, ViolationClue, ClueType,
    CluePriority, Institution, Practitioner
)


def _is_date_valid(valid_until: Optional[date], check_date: Optional[date] = None) -> bool:
    if check_date is None:
        check_date = date.today()
    if valid_until is None:
        return True
    return valid_until >= check_date


def check_institution_license_valid(
    db: Session,
    institution_id: int,
    check_date: Optional[date] = None
) -> Tuple[bool, Optional[str], Optional[InstitutionLicense]]:
    if check_date is None:
        check_date = date.today()

    license_record = db.query(InstitutionLicense).filter(
        InstitutionLicense.institution_id == institution_id,
        InstitutionLicense.is_valid == True
    ).first()

    if not license_record:
        return False, "机构无有效医疗机构执业许可证", None

    if not _is_date_valid(license_record.valid_until, check_date):
        detail = f"机构执业许可证已过期（有效期至 {license_record.valid_until}）"
        return False, detail, license_record

    detail = f"许可证号: {license_record.license_number}, 有效期至: {license_record.valid_until}"
    return True, detail, license_record


def check_practitioner_qualification_valid(
    db: Session,
    practitioner_id: int,
    qualification_type: QualificationType,
    check_date: Optional[date] = None
) -> Tuple[bool, Optional[str]]:
    if check_date is None:
        check_date = date.today()

    qual = db.query(PractitionerQualification).filter(
        PractitionerQualification.practitioner_id == practitioner_id,
        PractitionerQualification.qualification_type == qualification_type,
        PractitionerQualification.is_valid == True
    ).first()

    q_name = qualification_type.value
    if not qual:
        return False, f"人员无有效{q_name}"

    if not _is_date_valid(qual.valid_until, check_date):
        return False, f"人员{q_name}已过期（有效期至 {qual.valid_until}）"

    return True, None


def check_practitioner_core_qualifications(
    db: Session,
    practitioner_id: int,
    check_date: Optional[date] = None
) -> List[str]:
    issues = []

    ok, msg = check_practitioner_qualification_valid(
        db, practitioner_id, QualificationType.DOCTOR, check_date
    )
    if not ok:
        issues.append(msg)

    ok, msg = check_practitioner_qualification_valid(
        db, practitioner_id, QualificationType.PRACTICE, check_date
    )
    if not ok:
        issues.append(msg)

    return issues


def check_institution_procedure_authorized(
    db: Session,
    institution_id: int,
    procedure_id: int
) -> Tuple[bool, Optional[str]]:
    auth = db.query(InstitutionAuthorizedProcedure).filter(
        InstitutionAuthorizedProcedure.institution_id == institution_id,
        InstitutionAuthorizedProcedure.procedure_id == procedure_id
    ).first()
    if not auth:
        return False, "机构未获得该项目执业授权"
    return True, None


def check_practitioner_procedure_authorized(
    db: Session,
    practitioner_id: int,
    procedure_id: int
) -> Tuple[bool, Optional[str]]:
    auth = db.query(PractitionerAuthorizedProcedure).filter(
        PractitionerAuthorizedProcedure.practitioner_id == practitioner_id,
        PractitionerAuthorizedProcedure.procedure_id == procedure_id
    ).first()
    if not auth:
        return False, "人员未获得该项目操作授权"
    return True, None


def judge_over_range_practice(
    db: Session,
    institution_id: int,
    practitioner_id: int,
    procedure_id: int,
    procedure_date: Optional[date] = None
) -> Tuple[bool, List[str]]:
    if procedure_date is None:
        procedure_date = date.today()

    issues: List[str] = []

    license_ok, license_msg, _ = check_institution_license_valid(
        db, institution_id, procedure_date
    )
    if not license_ok:
        issues.append(license_msg)

    inst_auth_ok, inst_auth_msg = check_institution_procedure_authorized(
        db, institution_id, procedure_id
    )
    if not inst_auth_ok:
        issues.append(inst_auth_msg)

    prac_core_issues = check_practitioner_core_qualifications(
        db, practitioner_id, procedure_date
    )
    issues.extend(prac_core_issues)

    prac_auth_ok, prac_auth_msg = check_practitioner_procedure_authorized(
        db, practitioner_id, procedure_id
    )
    if not prac_auth_ok:
        issues.append(prac_auth_msg)

    is_over_range = len(issues) > 0
    return is_over_range, issues


def count_unlicensed_practitioners(
    db: Session,
    institution_id: Optional[int] = None,
    check_date: Optional[date] = None
) -> Tuple[int, int]:
    if check_date is None:
        check_date = date.today()

    query = db.query(Practitioner)
    if institution_id is not None:
        query = query.filter(Practitioner.institution_id == institution_id)
    practitioners = query.all()

    total = len(practitioners)
    unlicensed = 0

    for p in practitioners:
        core_issues = check_practitioner_core_qualifications(db, p.id, check_date)
        if core_issues:
            unlicensed += 1

    return unlicensed, total


def create_over_range_clue(
    db: Session,
    institution_id: int,
    practitioner_id: int,
    procedure_id: int,
    procedure_record_id: int,
    over_range_details: List[str]
) -> ViolationClue:
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    practitioner = db.query(Practitioner).filter(Practitioner.id == practitioner_id).first()
    procedure = db.query(Procedure).filter(Procedure.id == procedure_id).first()

    inst_name = institution.name if institution else f"机构#{institution_id}"
    prac_name = practitioner.name if practitioner else f"人员#{practitioner_id}"
    proc_name = procedure.name if procedure else f"项目#{procedure_id}"

    detail_str = "；".join(over_range_details)
    title = f"超范围执业：{inst_name} - {prac_name} 开展 {proc_name}"
    description = (
        f"经系统判定，机构「{inst_name}」的操作人员「{prac_name}」"
        f"开展项目「{proc_name}」存在超范围执业问题。\n"
        f"具体问题：{detail_str}\n"
        f"关联执业记录ID：{procedure_record_id}"
    )

    clue = ViolationClue(
        clue_type=ClueType.OVER_RANGE_PRACTICE,
        title=title,
        description=description,
        institution_id=institution_id,
        practitioner_id=practitioner_id,
        procedure_id=procedure_id,
        source="系统自动判定",
        priority=CluePriority.HIGH
    )
    db.add(clue)
    db.commit()
    db.refresh(clue)
    return clue


def recalculate_all_over_range_records(db: Session) -> dict:
    records = db.query(ActualProcedureRecord).all()
    total = len(records)
    updated = 0
    newly_marked = 0
    newly_cleared = 0
    clues_created = 0

    for r in records:
        old_flag = r.is_over_range
        is_over_range, issues = judge_over_range_practice(
            db,
            r.institution_id,
            r.practitioner_id,
            r.procedure_id,
            r.procedure_date
        )

        detail_str = "; ".join(issues) if issues else None

        if old_flag != is_over_range or r.over_range_detail != detail_str:
            r.is_over_range = is_over_range
            r.over_range_detail = detail_str
            updated += 1

            if is_over_range and not old_flag:
                newly_marked += 1
            if not is_over_range and old_flag:
                newly_cleared += 1

            if is_over_range:
                existing_clue = db.query(ViolationClue).filter(
                    ViolationClue.institution_id == r.institution_id,
                    ViolationClue.practitioner_id == r.practitioner_id,
                    ViolationClue.procedure_id == r.procedure_id,
                    ViolationClue.clue_type == ClueType.OVER_RANGE_PRACTICE
                ).first()
                if not existing_clue:
                    try:
                        create_over_range_clue(
                            db,
                            r.institution_id,
                            r.practitioner_id,
                            r.procedure_id,
                            r.id,
                            issues
                        )
                        clues_created += 1
                    except Exception:
                        db.rollback()

    db.commit()
    return {
        "total_records": total,
        "updated_records": updated,
        "newly_marked_over_range": newly_marked,
        "newly_cleared": newly_cleared,
        "clues_created": clues_created
    }
