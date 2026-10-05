from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from ..database import get_db
from ..models import (
    Institution, Practitioner, PractitionerQualification, QualificationType,
    ActualProcedureRecord, Procedure, ProcedureCategory,
    ViolationClue, ClueStatus, ComplianceScore, ComplianceGrade
)
from .. import schemas
from ..compliance_utils import count_unlicensed_practitioners

router = APIRouter()


def get_latest_compliance_score(db: Session, institution_id: int):
    return db.query(ComplianceScore).filter(
        ComplianceScore.institution_id == institution_id
    ).order_by(ComplianceScore.scored_at.desc()).first()


@router.get("/by-institution", response_model=List[schemas.StatsByInstitutionWithGrade])
def stats_by_institution(
    min_risk_score: Optional[float] = Query(None, ge=0, le=100),
    grade: Optional[ComplianceGrade] = Query(None, description="按合规等级筛选"),
    include_compliance: bool = Query(True, description="是否包含合规评分信息"),
    db: Session = Depends(get_db)
):
    results = []
    institutions = db.query(Institution).all()

    for inst in institutions:
        total_clues = db.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id
        ).count()

        verified_violations = db.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id,
            ViolationClue.status == ClueStatus.VERIFIED
        ).count()

        pending_clues = db.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id,
            ViolationClue.status.in_([ClueStatus.PENDING, ClueStatus.ASSIGNED])
        ).count()

        over_range_count = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.institution_id == inst.id,
            ActualProcedureRecord.is_over_range == True
        ).count()

        total_practitioners = db.query(Practitioner).filter(
            Practitioner.institution_id == inst.id
        ).count()

        unlicensed_count, _ = count_unlicensed_practitioners(db, inst.id)

        unlicensed_ratio = round(unlicensed_count / total_practitioners, 4) if total_practitioners > 0 else 0.0

        risk_score = round(
            (verified_violations * 25) +
            (over_range_count * 15) +
            (unlicensed_ratio * 30) +
            (pending_clues * 10),
            2
        )
        risk_score = min(risk_score, 100)

        if min_risk_score is not None and risk_score < min_risk_score:
            continue

        compliance_grade = None
        compliance_score_val = None
        inspection_frequency = None

        if include_compliance:
            latest_score = get_latest_compliance_score(db, inst.id)
            if latest_score:
                compliance_grade = latest_score.grade
                compliance_score_val = latest_score.total_score
                inspection_frequency = latest_score.inspection_frequency

        if grade is not None and compliance_grade != grade:
            continue

        results.append(schemas.StatsByInstitutionWithGrade(
            institution_id=inst.id,
            institution_name=inst.name,
            total_clues=total_clues,
            verified_violations=verified_violations,
            pending_clues=pending_clues,
            over_range_count=over_range_count,
            unlicensed_ratio=unlicensed_ratio,
            risk_score=risk_score,
            compliance_grade=compliance_grade,
            compliance_score=compliance_score_val,
            inspection_frequency=inspection_frequency
        ))

    results.sort(key=lambda x: (
        0 if x.compliance_grade == ComplianceGrade.POOR else
        1 if x.compliance_grade == ComplianceGrade.FAIR else
        2 if x.compliance_grade == ComplianceGrade.GOOD else
        3 if x.compliance_grade == ComplianceGrade.EXCELLENT else 4,
        -x.risk_score
    ))
    return results


@router.get("/by-category", response_model=List[schemas.StatsByCategory])
def stats_by_category(db: Session = Depends(get_db)):
    results = []

    for category in ProcedureCategory:
        procs = db.query(Procedure).filter(Procedure.category == category).all()
        proc_ids = [p.id for p in procs]

        if not proc_ids:
            results.append(schemas.StatsByCategory(
                category=category,
                total_actual=0,
                over_range_count=0,
                over_range_ratio=0.0,
                clue_count=0
            ))
            continue

        total_actual = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.procedure_id.in_(proc_ids)
        ).count()

        over_range_count = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.procedure_id.in_(proc_ids),
            ActualProcedureRecord.is_over_range == True
        ).count()

        over_range_ratio = round(over_range_count / total_actual, 4) if total_actual > 0 else 0.0

        clue_count = db.query(ViolationClue).join(
            Procedure, ViolationClue.procedure_id == Procedure.id
        ).filter(
            Procedure.category == category,
            ViolationClue.status == ClueStatus.VERIFIED
        ).count()

        results.append(schemas.StatsByCategory(
            category=category,
            total_actual=total_actual,
            over_range_count=over_range_count,
            over_range_ratio=over_range_ratio,
            clue_count=clue_count
        ))

    return results


@router.get("/problem-institutions", response_model=List[schemas.ProblemInstitution])
def list_problem_institutions(
    threshold: float = Query(10.0, ge=0, le=100, description="风险分数阈值"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    results = []
    institutions = db.query(Institution).all()

    for inst in institutions:
        verified_violations = db.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id,
            ViolationClue.status == ClueStatus.VERIFIED
        ).count()

        over_range_count = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.institution_id == inst.id,
            ActualProcedureRecord.is_over_range == True
        ).count()

        total_practitioners = db.query(Practitioner).filter(
            Practitioner.institution_id == inst.id
        ).count()

        unlicensed_count, _ = count_unlicensed_practitioners(db, inst.id)

        unlicensed_ratio = round(unlicensed_count / total_practitioners, 4) if total_practitioners > 0 else 0.0

        risk_score = (
            (verified_violations * 25) +
            (over_range_count * 15) +
            (unlicensed_ratio * 30)
        )

        if risk_score >= threshold or verified_violations > 0 or over_range_count > 0:
            if risk_score >= 50:
                risk_level = "高风险"
            elif risk_score >= 25:
                risk_level = "中风险"
            else:
                risk_level = "低风险"

            results.append(schemas.ProblemInstitution(
                institution_id=inst.id,
                institution_name=inst.name,
                verified_violations=verified_violations,
                over_range_count=over_range_count,
                unlicensed_ratio=unlicensed_ratio,
                risk_level=risk_level
            ))

    results.sort(key=lambda x: (
        0 if x.risk_level == "高风险" else 1 if x.risk_level == "中风险" else 2,
        -x.verified_violations,
        -x.over_range_count
    ))
    return results[:limit]


@router.get("/summary")
def get_overall_summary(db: Session = Depends(get_db)):
    total_institutions = db.query(Institution).count()
    total_practitioners = db.query(Practitioner).count()
    total_procedures = db.query(Procedure).count()

    total_clues = db.query(ViolationClue).count()
    pending_clues = db.query(ViolationClue).filter(
        ViolationClue.status == ClueStatus.PENDING
    ).count()
    assigned_clues = db.query(ViolationClue).filter(
        ViolationClue.status == ClueStatus.ASSIGNED
    ).count()
    verified_violations = db.query(ViolationClue).filter(
        ViolationClue.status == ClueStatus.VERIFIED
    ).count()
    dismissed_clues = db.query(ViolationClue).filter(
        ViolationClue.status == ClueStatus.DISMISSED
    ).count()

    total_actual = db.query(ActualProcedureRecord).count()
    over_range_count = db.query(ActualProcedureRecord).filter(
        ActualProcedureRecord.is_over_range == True
    ).count()

    unlicensed_practitioners, total_practitioners_all = count_unlicensed_practitioners(db)

    total_practitioners = total_practitioners_all if total_practitioners_all > 0 else db.query(Practitioner).count()

    compliance_distribution = []
    compliance_summary = None

    latest_scores_subquery = db.query(
        ComplianceScore.institution_id,
        func.max(ComplianceScore.scored_at).label("max_scored_at")
    ).group_by(ComplianceScore.institution_id).subquery()

    latest_scores = db.query(ComplianceScore).join(
        latest_scores_subquery,
        (ComplianceScore.institution_id == latest_scores_subquery.c.institution_id) &
        (ComplianceScore.scored_at == latest_scores_subquery.c.max_scored_at)
    ).all()

    if latest_scores:
        total_scored = len(latest_scores)
        grade_names = {
            ComplianceGrade.EXCELLENT: "优秀",
            ComplianceGrade.GOOD: "良好",
            ComplianceGrade.FAIR: "合格",
            ComplianceGrade.POOR: "不合格",
        }
        for grade in ComplianceGrade:
            count = sum(1 for s in latest_scores if s.grade == grade)
            compliance_distribution.append({
                "grade": grade.value,
                "grade_name": grade_names.get(grade, "未知"),
                "count": count,
                "percentage": round(count / total_scored * 100, 2) if total_scored > 0 else 0
            })

        avg_score = round(sum(s.total_score for s in latest_scores) / total_scored, 2) if total_scored > 0 else 0
        high_risk_count = sum(1 for s in latest_scores if s.grade == ComplianceGrade.POOR)

        compliance_summary = {
            "total_scored": total_scored,
            "avg_score": avg_score,
            "high_risk_count": high_risk_count,
            "high_risk_percentage": round(high_risk_count / total_scored * 100, 2) if total_scored > 0 else 0,
            "distribution": compliance_distribution
        }

    return {
        "institutions": {
            "total": total_institutions
        },
        "practitioners": {
            "total": total_practitioners,
            "unlicensed": unlicensed_practitioners,
            "unlicensed_ratio": round(unlicensed_practitioners / total_practitioners, 4) if total_practitioners > 0 else 0
        },
        "procedures": {
            "total_catalog": total_procedures,
            "total_actual_records": total_actual,
            "over_range_count": over_range_count,
            "over_range_ratio": round(over_range_count / total_actual, 4) if total_actual > 0 else 0
        },
        "clues": {
            "total": total_clues,
            "pending": pending_clues,
            "assigned": assigned_clues,
            "verified_violations": verified_violations,
            "dismissed": dismissed_clues
        },
        "compliance": compliance_summary
    }


@router.get("/by-compliance-grade", response_model=List[schemas.StatsByComplianceGrade])
def stats_by_compliance_grade(db: Session = Depends(get_db)):
    results = []

    latest_scores_subquery = db.query(
        ComplianceScore.institution_id,
        func.max(ComplianceScore.scored_at).label("max_scored_at")
    ).group_by(ComplianceScore.institution_id).subquery()

    latest_scores = db.query(ComplianceScore).join(
        latest_scores_subquery,
        (ComplianceScore.institution_id == latest_scores_subquery.c.institution_id) &
        (ComplianceScore.scored_at == latest_scores_subquery.c.max_scored_at)
    ).all()

    score_by_institution = {s.institution_id: s for s in latest_scores}

    for grade in ComplianceGrade:
        institution_ids = [
            inst_id for inst_id, s in score_by_institution.items()
            if s.grade == grade
        ]

        if not institution_ids:
            results.append(schemas.StatsByComplianceGrade(
                grade=grade,
                institution_count=0,
                avg_score=0.0,
                total_verified_violations=0,
                total_over_range_count=0,
                avg_unlicensed_ratio=0.0
            ))
            continue

        scores = [score_by_institution[iid] for iid in institution_ids]
        avg_score = round(sum(s.total_score for s in scores) / len(scores), 2)

        total_verified = db.query(ViolationClue).filter(
            ViolationClue.institution_id.in_(institution_ids),
            ViolationClue.status == ClueStatus.VERIFIED
        ).count()

        total_over_range = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.institution_id.in_(institution_ids),
            ActualProcedureRecord.is_over_range == True
        ).count()

        unlicensed_ratios = []
        for inst_id in institution_ids:
            unlicensed_count, total_prac = count_unlicensed_practitioners(db, inst_id)
            if total_prac > 0:
                unlicensed_ratios.append(unlicensed_count / total_prac)

        avg_unlicensed = round(sum(unlicensed_ratios) / len(unlicensed_ratios), 4) if unlicensed_ratios else 0.0

        results.append(schemas.StatsByComplianceGrade(
            grade=grade,
            institution_count=len(institution_ids),
            avg_score=avg_score,
            total_verified_violations=total_verified,
            total_over_range_count=total_over_range,
            avg_unlicensed_ratio=avg_unlicensed
        ))

    return results


@router.get("/by-category-with-grade")
def stats_by_category_with_grade(
    grade: Optional[ComplianceGrade] = Query(None, description="按合规等级筛选"),
    db: Session = Depends(get_db)
):
    results = []

    latest_scores_subquery = db.query(
        ComplianceScore.institution_id,
        func.max(ComplianceScore.scored_at).label("max_scored_at")
    ).group_by(ComplianceScore.institution_id).subquery()

    latest_scores = db.query(ComplianceScore).join(
        latest_scores_subquery,
        (ComplianceScore.institution_id == latest_scores_subquery.c.institution_id) &
        (ComplianceScore.scored_at == latest_scores_subquery.c.max_scored_at)
    ).all()

    score_by_institution = {s.institution_id: s for s in latest_scores}

    for category in ProcedureCategory:
        procs = db.query(Procedure).filter(Procedure.category == category).all()
        proc_ids = [p.id for p in procs]

        if not proc_ids:
            results.append({
                "category": category.value,
                "total_actual": 0,
                "over_range_count": 0,
                "over_range_ratio": 0.0,
                "clue_count": 0,
                "by_grade": []
            })
            continue

        query = db.query(ActualProcedureRecord).filter(
            ActualProcedureRecord.procedure_id.in_(proc_ids)
        )

        if grade:
            filtered_inst_ids = [
                iid for iid, s in score_by_institution.items() if s.grade == grade
            ]
            query = query.filter(ActualProcedureRecord.institution_id.in_(filtered_inst_ids))

        total_actual = query.count()

        over_range_query = query.filter(ActualProcedureRecord.is_over_range == True)
        over_range_count = over_range_query.count()

        over_range_ratio = round(over_range_count / total_actual, 4) if total_actual > 0 else 0.0

        clue_query = db.query(ViolationClue).join(
            Procedure, ViolationClue.procedure_id == Procedure.id
        ).filter(
            Procedure.category == category,
            ViolationClue.status == ClueStatus.VERIFIED
        )

        if grade:
            clue_query = clue_query.filter(ViolationClue.institution_id.in_(filtered_inst_ids))

        clue_count = clue_query.count()

        by_grade = []
        if grade is None:
            for g in ComplianceGrade:
                g_inst_ids = [iid for iid, s in score_by_institution.items() if s.grade == g]

                g_total = db.query(ActualProcedureRecord).filter(
                    ActualProcedureRecord.procedure_id.in_(proc_ids),
                    ActualProcedureRecord.institution_id.in_(g_inst_ids)
                ).count()

                g_over_range = db.query(ActualProcedureRecord).filter(
                    ActualProcedureRecord.procedure_id.in_(proc_ids),
                    ActualProcedureRecord.institution_id.in_(g_inst_ids),
                    ActualProcedureRecord.is_over_range == True
                ).count()

                g_ratio = round(g_over_range / g_total, 4) if g_total > 0 else 0.0

                g_clues = db.query(ViolationClue).join(
                    Procedure, ViolationClue.procedure_id == Procedure.id
                ).filter(
                    Procedure.category == category,
                    ViolationClue.status == ClueStatus.VERIFIED,
                    ViolationClue.institution_id.in_(g_inst_ids)
                ).count()

                by_grade.append({
                    "grade": g.value,
                    "total_actual": g_total,
                    "over_range_count": g_over_range,
                    "over_range_ratio": g_ratio,
                    "clue_count": g_clues
                })

        results.append({
            "category": category.value,
            "total_actual": total_actual,
            "over_range_count": over_range_count,
            "over_range_ratio": over_range_ratio,
            "clue_count": clue_count,
            "by_grade": by_grade
        })

    return results
