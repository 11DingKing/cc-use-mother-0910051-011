import sys
import os
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models import (
    Institution, InstitutionType, InstitutionLicense,
    Practitioner, PractitionerQualification, QualificationType,
    Procedure, ProcedureCategory, SurgeryLevel,
    InstitutionAuthorizedProcedure, PractitionerAuthorizedProcedure,
    ActualProcedureRecord,
    ViolationClue, ClueType, ClueStatus, CluePriority,
    InspectionRecord
)


def pytest_sessionstart(session):
    """在测试收集前准备接口冒烟测试使用的持久化数据库。"""
    from seed_data import seed_data

    seed_data()

TEST_DATABASE_URL = "sqlite:///./test_medspa.db"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    yield engine
    engine.dispose()
    if os.path.exists("./test_medspa.db"):
        os.remove("./test_medspa.db")


@pytest.fixture(scope="session")
def TestSessionLocal(test_engine):
    Base.metadata.create_all(bind=test_engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session(test_engine, TestSessionLocal):
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    # 服务层会在请求内 commit/rollback。开启嵌套事务（SAVEPOINT）并在每次
    # 内层事务结束后重建保存点，使服务层的提交只释放保存点；测试结束由外层
    # 事务统一回滚，保证用例间数据隔离（含触发 rollback 的租约冲突场景）。
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        if transaction.nested and not transaction._parent.nested:
            connection.begin_nested()

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", restart_savepoint)
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_procedures(db_session):
    procedures = [
        Procedure(
            name="双眼皮成形术",
            code="TEST-001",
            category=ProcedureCategory.SURGERY,
            surgery_level=SurgeryLevel.LEVEL_1,
            requires_qualification="美容外科主诊医师资格"
        ),
        Procedure(
            name="下颌角整形术",
            code="TEST-002",
            category=ProcedureCategory.SURGERY,
            surgery_level=SurgeryLevel.LEVEL_4,
            requires_qualification="三级以上医院、副主任医师以上"
        ),
        Procedure(
            name="玻尿酸填充",
            code="TEST-003",
            category=ProcedureCategory.INJECTION,
            requires_qualification="医师执业证、注射培训合格"
        ),
        Procedure(
            name="肉毒素注射除皱",
            code="TEST-004",
            category=ProcedureCategory.INJECTION,
            requires_qualification="医师执业证、注射培训合格"
        ),
        Procedure(
            name="光子嫩肤",
            code="TEST-005",
            category=ProcedureCategory.PHOTOELECTRIC,
            requires_qualification="皮肤科医师或经过培训的护士"
        ),
        Procedure(
            name="点阵激光祛斑",
            code="TEST-006",
            category=ProcedureCategory.PHOTOELECTRIC,
            requires_qualification="皮肤科医师资格"
        ),
        Procedure(
            name="果酸换肤",
            code="TEST-007",
            category=ProcedureCategory.SKINCARE,
            requires_qualification="皮肤科医师指导"
        ),
        Procedure(
            name="美容牙科美白",
            code="TEST-008",
            category=ProcedureCategory.ORAL,
            requires_qualification="口腔执业医师资格"
        ),
    ]
    for p in procedures:
        db_session.add(p)
    db_session.flush()
    return {p.code: p for p in procedures}


@pytest.fixture
def test_institution_valid(db_session):
    inst = Institution(
        name="测试合规医美医院",
        unified_social_code="91310000TEST0001",
        institution_type=InstitutionType.HOSPITAL,
        legal_person="测试法人",
        address="测试地址1号",
        phone="021-00000001",
        registration_date=date(2020, 1, 1),
        business_scope="医疗美容科；美容外科；美容皮肤科"
    )
    db_session.add(inst)
    db_session.flush()

    lic = InstitutionLicense(
        institution_id=inst.id,
        license_number="PDYTEST001",
        issuing_authority="测试卫健委",
        issue_date=date(2020, 1, 15),
        valid_until=date(2030, 1, 14),
        approved_surgeries="美容外科一级、二级、三级项目；美容皮肤科全部项目",
        is_valid=True
    )
    db_session.add(lic)
    db_session.flush()
    return inst


@pytest.fixture
def test_institution_expired(db_session):
    inst = Institution(
        name="测试许可证过期机构",
        unified_social_code="91310000TEST0002",
        institution_type=InstitutionType.CLINIC,
        legal_person="测试法人2",
        address="测试地址2号",
        phone="021-00000002",
        registration_date=date(2020, 1, 1),
        business_scope="医疗美容科；美容皮肤科"
    )
    db_session.add(inst)
    db_session.flush()

    lic = InstitutionLicense(
        institution_id=inst.id,
        license_number="PDYTEST002",
        issuing_authority="测试卫健委",
        issue_date=date(2020, 1, 15),
        valid_until=date(2023, 1, 14),
        approved_surgeries="美容皮肤科光电类项目",
        is_valid=True
    )
    db_session.add(lic)
    db_session.flush()
    return inst


@pytest.fixture
def test_institution_no_license(db_session):
    inst = Institution(
        name="测试无许可证机构",
        unified_social_code="91310000TEST0003",
        institution_type=InstitutionType.CLINIC,
        legal_person="测试法人3",
        address="测试地址3号",
        phone="021-00000003",
        registration_date=date(2021, 1, 1),
        business_scope="美容咨询"
    )
    db_session.add(inst)
    db_session.flush()
    return inst


@pytest.fixture
def test_practitioner_fully_qualified(db_session, test_institution_valid):
    prac = Practitioner(
        name="张合格",
        id_card="310101198001010001",
        gender="男",
        birth_date=date(1980, 1, 1),
        institution_id=test_institution_valid.id,
        position="美容外科主任医师"
    )
    db_session.add(prac)
    db_session.flush()

    quals = [
        PractitionerQualification(
            practitioner_id=prac.id,
            qualification_type=QualificationType.DOCTOR,
            certificate_number="DOC-TEST-001",
            issuing_authority="测试卫健委",
            issue_date=date(2005, 6, 1),
            valid_until=None,
            practice_scope="外科专业",
            is_valid=True
        ),
        PractitionerQualification(
            practitioner_id=prac.id,
            qualification_type=QualificationType.PRACTICE,
            certificate_number="PRAC-TEST-001",
            issuing_authority="测试卫健委",
            issue_date=date(2006, 3, 1),
            valid_until=date(2030, 12, 31),
            practice_scope="外科专业;医疗美容科",
            is_valid=True
        ),
        PractitionerQualification(
            practitioner_id=prac.id,
            qualification_type=QualificationType.COSMETOLOGY,
            certificate_number="COS-TEST-001",
            issuing_authority="测试医学会",
            issue_date=date(2010, 5, 1),
            valid_until=None,
            practice_scope="美容外科",
            is_valid=True
        ),
    ]
    for q in quals:
        db_session.add(q)
    db_session.flush()
    return prac


@pytest.fixture
def test_practitioner_license_expired(db_session, test_institution_valid):
    prac = Practitioner(
        name="李过期",
        id_card="310101198501010002",
        gender="女",
        birth_date=date(1985, 1, 1),
        institution_id=test_institution_valid.id,
        position="皮肤科医师"
    )
    db_session.add(prac)
    db_session.flush()

    quals = [
        PractitionerQualification(
            practitioner_id=prac.id,
            qualification_type=QualificationType.DOCTOR,
            certificate_number="DOC-TEST-002",
            issuing_authority="测试卫健委",
            issue_date=date(2010, 7, 1),
            valid_until=None,
            practice_scope="皮肤病与性病专业",
            is_valid=True
        ),
        PractitionerQualification(
            practitioner_id=prac.id,
            qualification_type=QualificationType.PRACTICE,
            certificate_number="PRAC-TEST-002",
            issuing_authority="测试卫健委",
            issue_date=date(2011, 4, 1),
            valid_until=date(2023, 12, 31),
            practice_scope="皮肤病与性病专业;医疗美容科",
            is_valid=True
        ),
    ]
    for q in quals:
        db_session.add(q)
    db_session.flush()
    return prac


@pytest.fixture
def test_practitioner_unlicensed(db_session, test_institution_valid):
    prac = Practitioner(
        name="王无证",
        id_card="310101199001010003",
        gender="女",
        birth_date=date(1990, 1, 1),
        institution_id=test_institution_valid.id,
        position="注射师"
    )
    db_session.add(prac)
    db_session.flush()
    return prac


@pytest.fixture
def test_multi_clue_institution(db_session, test_procedures):
    inst = Institution(
        name="测试多线索机构",
        unified_social_code="91310000TEST0010",
        institution_type=InstitutionType.CLINIC,
        legal_person="测试法人10",
        address="测试地址10号",
        phone="021-00000010",
        registration_date=date(2020, 6, 1),
        business_scope="医疗美容科；美容外科；美容皮肤科"
    )
    db_session.add(inst)
    db_session.flush()

    lic = InstitutionLicense(
        institution_id=inst.id,
        license_number="PDYTEST010",
        issuing_authority="测试卫健委",
        issue_date=date(2020, 6, 15),
        valid_until=date(2030, 6, 14),
        approved_surgeries="美容外科一级项目；美容皮肤科项目",
        is_valid=True
    )
    db_session.add(lic)
    db_session.flush()

    auth_procs = [
        InstitutionAuthorizedProcedure(
            institution_id=inst.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2020, 7, 1)
        ),
        InstitutionAuthorizedProcedure(
            institution_id=inst.id,
            procedure_id=test_procedures["TEST-005"].id,
            authorized_date=date(2020, 7, 1)
        ),
    ]
    for auth in auth_procs:
        db_session.add(auth)
    db_session.flush()

    return inst


@pytest.fixture
def create_test_clues(db_session, test_multi_clue_institution, test_procedures):
    def _create_clues():
        prac1 = Practitioner(
            name="赵速成",
            id_card="310101199501010010",
            gender="女",
            birth_date=date(1995, 1, 1),
            institution_id=test_multi_clue_institution.id,
            position="注射师"
        )
        db_session.add(prac1)
        db_session.flush()

        prac2 = Practitioner(
            name="钱无证",
            id_card="310101199201010011",
            gender="男",
            birth_date=date(1992, 1, 1),
            institution_id=test_multi_clue_institution.id,
            position="光电操作师"
        )
        db_session.add(prac2)
        db_session.flush()

        clues = [
            ViolationClue(
                clue_type=ClueType.QUICK_TRAINING,
                title="疑似速成班培训人员上岗",
                description="赵速成疑似仅参加3天培训即上岗",
                institution_id=test_multi_clue_institution.id,
                practitioner_id=prac1.id,
                procedure_id=test_procedures["TEST-003"].id,
                source="12320举报",
                priority=CluePriority.HIGH,
                status=ClueStatus.PENDING
            ),
            ViolationClue(
                clue_type=ClueType.UNLICENSED_STAFF,
                title="无证人员上岗操作",
                description="钱无证无医师资质独立操作",
                institution_id=test_multi_clue_institution.id,
                practitioner_id=prac2.id,
                procedure_id=test_procedures["TEST-006"].id,
                source="日常检查",
                priority=CluePriority.HIGH,
                status=ClueStatus.VERIFIED,
                assignee="稽查员A",
                assigned_at=datetime(2024, 1, 15),
                conclusion="经查实无证上岗，已处罚",
                verified_at=datetime(2024, 1, 20)
            ),
            ViolationClue(
                clue_type=ClueType.FALSE_ADVERTISEMENT,
                title="虚假宣传四级手术资质",
                description="机构宣传可开展四级手术但无资质",
                institution_id=test_multi_clue_institution.id,
                procedure_id=test_procedures["TEST-002"].id,
                source="广告监测",
                priority=CluePriority.MEDIUM,
                status=ClueStatus.VERIFIED,
                assignee="稽查员B",
                assigned_at=datetime(2024, 1, 10),
                conclusion="经查实虚假宣传，已整改",
                verified_at=datetime(2024, 1, 18)
            ),
            ViolationClue(
                clue_type=ClueType.OVER_RANGE_PRACTICE,
                title="超范围执业",
                description="开展未授权项目",
                institution_id=test_multi_clue_institution.id,
                procedure_id=test_procedures["TEST-008"].id,
                source="系统判定",
                priority=CluePriority.HIGH,
                status=ClueStatus.ASSIGNED,
                assignee="稽查员A",
                assigned_at=datetime(2024, 1, 25)
            ),
            ViolationClue(
                clue_type=ClueType.QUICK_TRAINING,
                title="另一起速成班线索",
                description="另一人疑似速成班",
                institution_id=test_multi_clue_institution.id,
                source="舆情监测",
                priority=CluePriority.MEDIUM,
                status=ClueStatus.DISMISSED,
                assignee="稽查员C",
                assigned_at=datetime(2024, 1, 5),
                conclusion="经核实不属实",
                verified_at=datetime(2024, 1, 12)
            ),
        ]
        for clue in clues:
            db_session.add(clue)
        db_session.flush()
        return {
            "practitioners": [prac1, prac2],
            "clues": clues
        }
    return _create_clues
