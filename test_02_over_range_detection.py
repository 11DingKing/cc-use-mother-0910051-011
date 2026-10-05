from datetime import date

import pytest

from app.models import (
    ProcedureCategory, SurgeryLevel,
    InstitutionAuthorizedProcedure, PractitionerAuthorizedProcedure,
    ActualProcedureRecord, ViolationClue, ClueType
)
from app.compliance_utils import (
    check_institution_procedure_authorized,
    check_practitioner_procedure_authorized,
    judge_over_range_practice,
    recalculate_all_over_range_records,
    create_over_range_clue
)


class TestProcedureCategory:
    def test_surgery_category(self, test_procedures):
        assert test_procedures["TEST-001"].category == ProcedureCategory.SURGERY
        assert test_procedures["TEST-001"].surgery_level == SurgeryLevel.LEVEL_1
        assert test_procedures["TEST-002"].category == ProcedureCategory.SURGERY
        assert test_procedures["TEST-002"].surgery_level == SurgeryLevel.LEVEL_4

    def test_injection_category(self, test_procedures):
        assert test_procedures["TEST-003"].category == ProcedureCategory.INJECTION
        assert test_procedures["TEST-004"].category == ProcedureCategory.INJECTION

    def test_photoelectric_category(self, test_procedures):
        assert test_procedures["TEST-005"].category == ProcedureCategory.PHOTOELECTRIC
        assert test_procedures["TEST-006"].category == ProcedureCategory.PHOTOELECTRIC

    def test_skincare_category(self, test_procedures):
        assert test_procedures["TEST-007"].category == ProcedureCategory.SKINCARE

    def test_oral_category(self, test_procedures):
        assert test_procedures["TEST-008"].category == ProcedureCategory.ORAL

    def test_procedure_category_list_api(self, client):
        response = client.get("/api/procedures/categories/list")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert len(data["categories"]) == 5
        assert "手术类" in data["categories"]
        assert "注射类" in data["categories"]
        assert "光电类" in data["categories"]
        assert "皮肤护理类" in data["categories"]
        assert "口腔美容类" in data["categories"]
        assert "surgery_levels" in data
        assert len(data["surgery_levels"]) == 4


class TestInstitutionAuthorization:
    def test_institution_authorized_procedure(
        self, db_session, test_multi_clue_institution, test_procedures
    ):
        is_authorized, detail = check_institution_procedure_authorized(
            db_session,
            test_multi_clue_institution.id,
            test_procedures["TEST-001"].id
        )
        assert is_authorized is True
        assert detail is None

    def test_institution_unauthorized_procedure(
        self, db_session, test_multi_clue_institution, test_procedures
    ):
        is_authorized, detail = check_institution_procedure_authorized(
            db_session,
            test_multi_clue_institution.id,
            test_procedures["TEST-003"].id
        )
        assert is_authorized is False
        assert "机构未获得该项目执业授权" in detail

    def test_institution_no_license_authorization(
        self, db_session, test_institution_no_license, test_procedures
    ):
        is_authorized, detail = check_institution_procedure_authorized(
            db_session,
            test_institution_no_license.id,
            test_procedures["TEST-001"].id
        )
        assert is_authorized is False
        assert "机构未获得该项目执业授权" in detail


class TestPractitionerAuthorization:
    def test_practitioner_authorized_procedure(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add(auth)
        db_session.flush()

        is_authorized, detail = check_practitioner_procedure_authorized(
            db_session,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-001"].id
        )
        assert is_authorized is True
        assert detail is None

    def test_practitioner_unauthorized_procedure(
        self, db_session, test_practitioner_fully_qualified, test_procedures
    ):
        is_authorized, detail = check_practitioner_procedure_authorized(
            db_session,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-003"].id
        )
        assert is_authorized is False
        assert "人员未获得该项目操作授权" in detail


class TestOverRangeJudgment:
    def test_fully_compliant_procedure(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_valid.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-001"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is False
        assert len(issues) == 0

    def test_institution_expired_license(
        self,
        db_session,
        test_institution_expired,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_expired.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2022, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2022, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_expired.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-006"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True
        assert len(issues) >= 1
        assert any("许可证已过期" in issue for issue in issues)

    def test_institution_not_authorized(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-003"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add(prac_auth)
        db_session.flush()

        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_valid.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-003"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True
        assert any("机构未获得该项目执业授权" in issue for issue in issues)

    def test_institution_authorized_but_practitioner_unqualified(
        self,
        db_session,
        test_multi_clue_institution,
        test_practitioner_unlicensed,
        test_procedures
    ):
        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_multi_clue_institution.id,
            test_practitioner_unlicensed.id,
            test_procedures["TEST-001"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True

        issue_text = "；".join(issues)
        assert "人员无有效医师资格证" in issue_text
        assert "人员无有效医师执业证" in issue_text
        assert "人员未获得该项目操作授权" in issue_text
        assert "机构未获得该项目执业授权" not in issue_text

    def test_institution_authorized_practitioner_qualified_but_no_prac_auth(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-003"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add(inst_auth)
        db_session.flush()

        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_valid.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-003"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True

        issue_text = "；".join(issues)
        assert "人员未获得该项目操作授权" in issue_text
        assert "机构未获得该项目执业授权" not in issue_text

    def test_practitioner_license_expired(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_license_expired,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_license_expired.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_valid.id,
            test_practitioner_license_expired.id,
            test_procedures["TEST-006"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True
        assert any("医师执业证已过期" in issue for issue in issues)

    def test_multiple_issues(
        self,
        db_session,
        test_institution_no_license,
        test_practitioner_unlicensed,
        test_procedures
    ):
        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_no_license.id,
            test_practitioner_unlicensed.id,
            test_procedures["TEST-002"].id,
            date(2024, 1, 15)
        )
        assert is_over_range is True
        assert len(issues) >= 4

        issue_text = "；".join(issues)
        assert "无有效医疗机构执业许可证" in issue_text
        assert "机构未获得该项目执业授权" in issue_text
        assert "人员无有效医师资格证" in issue_text
        assert "人员无有效医师执业证" in issue_text
        assert "人员未获得该项目操作授权" in issue_text

    def test_over_range_with_historical_date(
        self,
        db_session,
        test_institution_expired,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_expired.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2020, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-006"].id,
            authorized_date=date(2020, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        procedure_date = date(2022, 6, 1)
        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_expired.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-006"].id,
            procedure_date
        )
        assert is_over_range is False
        assert len(issues) == 0

        procedure_date = date(2024, 6, 1)
        is_over_range, issues = judge_over_range_practice(
            db_session,
            test_institution_expired.id,
            test_practitioner_fully_qualified.id,
            test_procedures["TEST-006"].id,
            procedure_date
        )
        assert is_over_range is True
        assert any("许可证已过期" in issue for issue in issues)


class TestActualProcedureRecordAPI:
    def test_record_compliant_procedure(
        self,
        client,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        record_data = {
            "institution_id": test_institution_valid.id,
            "practitioner_id": test_practitioner_fully_qualified.id,
            "procedure_id": test_procedures["TEST-001"].id,
            "procedure_date": "2024-01-15",
            "patient_count": 3,
            "remark": "合规操作"
        }
        response = client.post("/api/compliance/actual-procedure", json=record_data)
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is False
        assert data["over_range_detail"] is None

    def test_record_over_range_procedure(
        self,
        client,
        db_session,
        test_multi_clue_institution,
        test_practitioner_unlicensed,
        test_procedures
    ):
        record_data = {
            "institution_id": test_multi_clue_institution.id,
            "practitioner_id": test_practitioner_unlicensed.id,
            "procedure_id": test_procedures["TEST-001"].id,
            "procedure_date": "2024-01-15",
            "patient_count": 2,
            "remark": "测试超范围"
        }
        response = client.post("/api/compliance/actual-procedure", json=record_data)
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is True
        assert data["over_range_detail"] is not None
        assert "人员无有效医师资格证" in data["over_range_detail"]

        clues = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == test_multi_clue_institution.id,
            ViolationClue.clue_type == ClueType.OVER_RANGE_PRACTICE
        ).all()
        assert len(clues) >= 1

    def test_record_procedure_invalid_institution(self, client, test_procedures):
        record_data = {
            "institution_id": 99999,
            "practitioner_id": 1,
            "procedure_id": test_procedures["TEST-001"].id,
            "procedure_date": "2024-01-15"
        }
        response = client.post("/api/compliance/actual-procedure", json=record_data)
        assert response.status_code == 404
        assert "机构不存在" in response.json()["detail"]

    def test_list_over_range_procedures(
        self,
        client,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_practitioner_unlicensed,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        compliant_record = ActualProcedureRecord(
            institution_id=test_institution_valid.id,
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            procedure_date=date(2024, 1, 10),
            patient_count=2,
            is_over_range=False
        )
        over_range_record = ActualProcedureRecord(
            institution_id=test_institution_valid.id,
            practitioner_id=test_practitioner_unlicensed.id,
            procedure_id=test_procedures["TEST-003"].id,
            procedure_date=date(2024, 1, 12),
            patient_count=3,
            is_over_range=True,
            over_range_detail="人员无资质"
        )
        db_session.add_all([compliant_record, over_range_record])
        db_session.flush()

        response = client.get("/api/compliance/actual-procedures?only_over_range=true")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["is_over_range"] is True

        response = client.get(
            f"/api/compliance/institution/{test_institution_valid.id}/over-range"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestRecalculateOverRange:
    def test_recalculate_updates_records(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_practitioner_license_expired,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        record1 = ActualProcedureRecord(
            institution_id=test_institution_valid.id,
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            procedure_date=date(2024, 1, 10),
            patient_count=2,
            is_over_range=False
        )
        record2 = ActualProcedureRecord(
            institution_id=test_institution_valid.id,
            practitioner_id=test_practitioner_license_expired.id,
            procedure_id=test_procedures["TEST-006"].id,
            procedure_date=date(2024, 1, 12),
            patient_count=3,
            is_over_range=False
        )
        db_session.add_all([record1, record2])
        db_session.flush()

        result = recalculate_all_over_range_records(db_session)

        assert result["total_records"] == 2
        assert result["updated_records"] == 1
        assert result["newly_marked_over_range"] == 1
        assert result["newly_cleared"] == 0
        assert result["clues_created"] == 1

        db_session.refresh(record2)
        assert record2.is_over_range is True
        assert "医师执业证已过期" in record2.over_range_detail

    def test_recalculate_api(self, client):
        response = client.post("/api/compliance/recalculate")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "detail" in data
        assert "超范围执业判定重算完成" in data["message"]


class TestCheckSingleOverRangeAPI:
    def test_check_single_compliant(
        self,
        client,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_procedures
    ):
        inst_auth = InstitutionAuthorizedProcedure(
            institution_id=test_institution_valid.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        prac_auth = PractitionerAuthorizedProcedure(
            practitioner_id=test_practitioner_fully_qualified.id,
            procedure_id=test_procedures["TEST-001"].id,
            authorized_date=date(2023, 1, 1)
        )
        db_session.add_all([inst_auth, prac_auth])
        db_session.flush()

        response = client.get(
            "/api/compliance/check/single",
            params={
                "institution_id": test_institution_valid.id,
                "practitioner_id": test_practitioner_fully_qualified.id,
                "procedure_id": test_procedures["TEST-001"].id,
                "procedure_date": "2024-01-15"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is False
        assert len(data["issues"]) == 0

    def test_check_single_over_range(
        self,
        client,
        test_institution_no_license,
        test_practitioner_unlicensed,
        test_procedures
    ):
        response = client.get(
            "/api/compliance/check/single",
            params={
                "institution_id": test_institution_no_license.id,
                "practitioner_id": test_practitioner_unlicensed.id,
                "procedure_id": test_procedures["TEST-002"].id
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is True
        assert len(data["issues"]) >= 4
