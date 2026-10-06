from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional, List
from .models import (
    InstitutionType, ProcedureCategory, SurgeryLevel,
    QualificationType, ClueType, ClueStatus, CluePriority,
    ComplianceGrade, ScoreItem, InspectionFrequency, PlanStatus,
    LeaseStatus, LeaseEventType, UserRole,
)


class InstitutionBase(BaseModel):
    name: str
    unified_social_code: str
    institution_type: InstitutionType
    legal_person: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    registration_date: Optional[date] = None
    business_scope: Optional[str] = None


class InstitutionCreate(InstitutionBase):
    pass


class InstitutionUpdate(BaseModel):
    name: Optional[str] = None
    unified_social_code: Optional[str] = None
    institution_type: Optional[InstitutionType] = None
    legal_person: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    registration_date: Optional[date] = None
    business_scope: Optional[str] = None


class Institution(InstitutionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InstitutionLicenseBase(BaseModel):
    license_number: str
    issuing_authority: Optional[str] = None
    issue_date: Optional[date] = None
    valid_until: Optional[date] = None
    approved_surgeries: Optional[str] = None
    is_valid: bool = True


class InstitutionLicenseCreate(InstitutionLicenseBase):
    institution_id: int


class InstitutionLicense(InstitutionLicenseBase):
    id: int
    created_at: datetime
    institution: Optional[Institution] = None

    class Config:
        from_attributes = True


class PractitionerBase(BaseModel):
    name: str
    id_card: str
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    institution_id: Optional[int] = None
    position: Optional[str] = None


class PractitionerCreate(PractitionerBase):
    pass


class PractitionerUpdate(BaseModel):
    name: Optional[str] = None
    id_card: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    institution_id: Optional[int] = None
    position: Optional[str] = None


class Practitioner(PractitionerBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PractitionerQualificationBase(BaseModel):
    qualification_type: QualificationType
    certificate_number: str
    issuing_authority: Optional[str] = None
    issue_date: Optional[date] = None
    valid_until: Optional[date] = None
    practice_scope: Optional[str] = None
    is_valid: bool = True


class PractitionerQualificationCreate(PractitionerQualificationBase):
    practitioner_id: int


class PractitionerQualification(PractitionerQualificationBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class PractitionerWithQualifications(Practitioner):
    qualifications: List[PractitionerQualification] = []


class ProcedureBase(BaseModel):
    name: str
    code: str
    category: ProcedureCategory
    surgery_level: Optional[SurgeryLevel] = None
    description: Optional[str] = None
    requires_qualification: Optional[str] = None


class ProcedureCreate(ProcedureBase):
    pass


class ProcedureUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[ProcedureCategory] = None
    surgery_level: Optional[SurgeryLevel] = None
    description: Optional[str] = None
    requires_qualification: Optional[str] = None


class Procedure(ProcedureBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class InstitutionAuthorizedProcedureBase(BaseModel):
    institution_id: int
    procedure_id: int
    authorized_date: Optional[date] = None
    remark: Optional[str] = None


class InstitutionAuthorizedProcedureCreate(InstitutionAuthorizedProcedureBase):
    pass


class InstitutionAuthorizedProcedure(InstitutionAuthorizedProcedureBase):
    id: int
    created_at: datetime
    procedure: Optional[Procedure] = None

    class Config:
        from_attributes = True


class PractitionerAuthorizedProcedureBase(BaseModel):
    practitioner_id: int
    procedure_id: int
    authorized_date: Optional[date] = None
    remark: Optional[str] = None


class PractitionerAuthorizedProcedureCreate(PractitionerAuthorizedProcedureBase):
    pass


class PractitionerAuthorizedProcedure(PractitionerAuthorizedProcedureBase):
    id: int
    created_at: datetime
    procedure: Optional[Procedure] = None

    class Config:
        from_attributes = True


class ActualProcedureRecordBase(BaseModel):
    institution_id: int
    practitioner_id: int
    procedure_id: int
    procedure_date: date
    patient_count: int = 1
    remark: Optional[str] = None


class ActualProcedureRecordCreate(ActualProcedureRecordBase):
    pass


class ActualProcedureRecord(ActualProcedureRecordBase):
    id: int
    is_over_range: bool = False
    over_range_detail: Optional[str] = None
    created_at: datetime
    procedure: Optional[Procedure] = None
    practitioner: Optional[Practitioner] = None

    class Config:
        from_attributes = True


class ViolationClueBase(BaseModel):
    clue_type: ClueType
    title: str
    description: str
    institution_id: Optional[int] = None
    practitioner_id: Optional[int] = None
    procedure_id: Optional[int] = None
    source: Optional[str] = None
    priority: CluePriority = CluePriority.MEDIUM


class ViolationClueCreate(ViolationClueBase):
    informant_name: Optional[str] = None
    informant_phone: Optional[str] = None
    informant_id_card: Optional[str] = None
    informant_contact_detail: Optional[str] = None


class ViolationClueUpdate(BaseModel):
    clue_type: Optional[ClueType] = None
    title: Optional[str] = None
    description: Optional[str] = None
    institution_id: Optional[int] = None
    practitioner_id: Optional[int] = None
    procedure_id: Optional[int] = None
    source: Optional[str] = None
    priority: Optional[CluePriority] = None
    status: Optional[ClueStatus] = None
    assignee: Optional[str] = None
    conclusion: Optional[str] = None
    informant_name: Optional[str] = None
    informant_phone: Optional[str] = None
    informant_id_card: Optional[str] = None
    informant_contact_detail: Optional[str] = None


class ViolationClue(ViolationClueBase):
    id: int
    status: ClueStatus = ClueStatus.PENDING
    assignee: Optional[str] = None
    assigned_at: Optional[datetime] = None
    conclusion: Optional[str] = None
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # 举报人明文不进入通用响应，按角色裁剪通过详情/租约接口获取
    current_lease: Optional["ClueLeaseView"] = None

    class Config:
        from_attributes = True


class ClueAssign(BaseModel):
    assignee: str
    assignee_role: UserRole = UserRole.INSPECTOR
    ttl_minutes: Optional[int] = None
    reason: Optional[str] = None


class ClueConclusion(BaseModel):
    status: ClueStatus
    conclusion: str
    # 租约凭证：结案必须持有当前版本；为空时仅允许旧流程兼容（持有人=assignee）
    holder: Optional[str] = None
    lease_id: Optional[int] = None
    lease_version: Optional[int] = None


class InformantView(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    id_card: Optional[str] = None
    contact_detail: Optional[str] = None
    masked: bool = True


class ClueLeaseRequest(BaseModel):
    holder: str = Field(..., min_length=1)
    holder_role: UserRole = UserRole.INSPECTOR
    ttl_minutes: Optional[int] = Field(None, ge=1, le=60 * 24 * 30)
    reason: Optional[str] = None


class ClueLeaseRenew(BaseModel):
    holder: str = Field(..., min_length=1)
    lease_id: int
    version: int
    ttl_minutes: Optional[int] = Field(None, ge=1, le=60 * 24 * 7)
    reason: str = Field(..., min_length=1)


class ClueLeaseRelease(BaseModel):
    holder: str = Field(..., min_length=1)
    lease_id: int
    version: int
    reason: str = Field(..., min_length=1)


class ClueLeaseReassign(BaseModel):
    supervisor: str = Field(..., min_length=1)
    to_holder: str = Field(..., min_length=1)
    to_role: UserRole = UserRole.INSPECTOR
    reason: str = Field(..., min_length=1)


class ClueLeaseView(BaseModel):
    id: int
    clue_id: int
    holder: str
    holder_role: UserRole
    status: LeaseStatus
    version: int
    leased_at: datetime
    expires_at: datetime
    released_at: Optional[datetime] = None
    evidence_summary: str
    evidence_hash: str
    permissions: List[str] = []

    class Config:
        from_attributes = True


class ClueLeaseEventView(BaseModel):
    id: int
    lease_id: int
    clue_id: int
    event_type: LeaseEventType
    actor: str
    reason: str
    from_holder: Optional[str] = None
    to_holder: Optional[str] = None
    version_before: Optional[int] = None
    version_after: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ClueDetailView(ViolationClue):
    informant: Optional[InformantView] = None
    events: List[ClueLeaseEventView] = []


class LeaseRecoverResult(BaseModel):
    expired_count: int
    reassigned_count: int
    expired_lease_ids: List[int] = []
    reassigned_lease_ids: List[int] = []


class LeaseRecoverRequest(BaseModel):
    auto_reassign_to: Optional[str] = None
    reason: Optional[str] = None


class InspectionRecordBase(BaseModel):
    clue_id: int
    inspector: str
    inspection_date: date
    content: str
    finding: Optional[str] = None


class InspectionRecordCreate(InspectionRecordBase):
    # 租约凭证：提交核查记录必须持有当前版本
    lease_id: Optional[int] = None
    lease_version: Optional[int] = None


class InspectionRecord(InspectionRecordBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class InstitutionComplianceCheck(BaseModel):
    institution_id: int
    institution_name: str
    has_valid_license: bool
    license_detail: Optional[str] = None
    authorized_procedure_count: int
    actual_procedure_count: int
    over_range_count: int
    unlicensed_practitioners: int
    total_practitioners: int
    clues_count: int
    verified_violations: int


class PractitionerComplianceCheck(BaseModel):
    practitioner_id: int
    name: str
    has_valid_doctor_license: bool
    has_valid_practice_license: bool
    has_cosmetology_license: bool
    authorized_procedures: List[str] = []
    actual_procedures: List[str] = []
    over_range_procedures: List[str] = []
    is_unlicensed: bool


class StatsByInstitution(BaseModel):
    institution_id: int
    institution_name: str
    total_clues: int
    verified_violations: int
    pending_clues: int
    over_range_count: int
    unlicensed_ratio: float
    risk_score: float


class StatsByCategory(BaseModel):
    category: ProcedureCategory
    total_actual: int
    over_range_count: int
    over_range_ratio: float
    clue_count: int


class ProblemInstitution(BaseModel):
    institution_id: int
    institution_name: str
    verified_violations: int
    over_range_count: int
    unlicensed_ratio: float
    risk_level: str


class ScoreDeduction(BaseModel):
    item: ScoreItem
    max_score: float
    actual_score: float
    deduction: float
    reason: str


class ComplianceScoreBase(BaseModel):
    institution_id: int
    remark: Optional[str] = None


class ComplianceScoreCreate(ComplianceScoreBase):
    pass


class ComplianceScoreUpdate(BaseModel):
    remark: Optional[str] = None


class ComplianceScore(ComplianceScoreBase):
    id: int
    total_score: float
    grade: ComplianceGrade
    license_valid_score: float
    license_complete_score: float
    no_over_range_score: float
    all_staff_licensed_score: float
    no_quick_training_score: float
    no_false_advertisement_score: float
    no_verified_violation_score: float
    deduction_details: Optional[str] = None
    inspection_frequency: InspectionFrequency
    scored_at: datetime
    scoring_period: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ComplianceScoreDetail(ComplianceScore):
    institution: Optional[Institution] = None
    deduction_list: Optional[List[ScoreDeduction]] = None


class SupervisionPlanBase(BaseModel):
    plan_title: str
    plan_content: str
    planned_date: date
    inspector: Optional[str] = None
    focus_areas: Optional[str] = None


class SupervisionPlanCreate(SupervisionPlanBase):
    compliance_score_id: int
    institution_id: int
    priority: Optional[CluePriority] = CluePriority.MEDIUM


class SupervisionPlanUpdate(BaseModel):
    plan_title: Optional[str] = None
    plan_content: Optional[str] = None
    planned_date: Optional[date] = None
    inspector: Optional[str] = None
    status: Optional[PlanStatus] = None
    priority: Optional[CluePriority] = None
    focus_areas: Optional[str] = None
    actual_inspection_date: Optional[date] = None
    result: Optional[str] = None


class SupervisionPlan(SupervisionPlanBase):
    id: int
    compliance_score_id: int
    institution_id: int
    status: PlanStatus
    priority: CluePriority
    actual_inspection_date: Optional[date] = None
    result: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupervisionPlanDetail(SupervisionPlan):
    institution: Optional[Institution] = None
    compliance_score: Optional[ComplianceScore] = None


class ScoreCalculationResult(BaseModel):
    institution_id: int
    institution_name: str
    total_score: float
    grade: ComplianceGrade
    inspection_frequency: InspectionFrequency
    deductions: List[ScoreDeduction]


class BatchScoreResult(BaseModel):
    total_institutions: int
    scored_count: int
    skipped_count: int
    results: List[ScoreCalculationResult]


class PlanGenerationResult(BaseModel):
    institution_id: int
    institution_name: str
    grade: ComplianceGrade
    plans_created: int
    plans: List[SupervisionPlan]


class StatsByComplianceGrade(BaseModel):
    grade: ComplianceGrade
    institution_count: int
    avg_score: float
    total_verified_violations: int
    total_over_range_count: int
    avg_unlicensed_ratio: float


class StatsByInstitutionWithGrade(StatsByInstitution):
    compliance_grade: Optional[ComplianceGrade] = None
    compliance_score: Optional[float] = None
    inspection_frequency: Optional[InspectionFrequency] = None


class ComplianceGradeDistribution(BaseModel):
    grade: ComplianceGrade
    grade_name: str
    count: int
    percentage: float
    score_range: str


# 重建含前向引用（current_lease -> ClueLeaseView）的模型
ViolationClue.model_rebuild()
ClueDetailView.model_rebuild()
