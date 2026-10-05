from datetime import date, timedelta

import pytest

from app.models import QualificationType
from app.compliance_utils import (
    check_institution_license_valid,
    check_practitioner_qualification_valid,
    check_practitioner_core_qualifications,
    count_unlicensed_practitioners,
    _is_date_valid
)


class TestDateValidation:
    def test_date_valid_none_expiry(self):
        assert _is_date_valid(None) is True

    def test_date_valid_future_expiry(self):
        future = date.today() + timedelta(days=365)
        assert _is_date_valid(future) is True

    def test_date_valid_today_expiry(self):
        today = date.today()
        assert _is_date_valid(today) is True

    def test_date_valid_past_expiry(self):
        past = date.today() - timedelta(days=1)
        assert _is_date_valid(past) is False

    def test_date_valid_custom_check_date(self):
        expiry = date(2025, 6, 30)
        check_before = date(2025, 6, 29)
        check_after = date(2025, 7, 1)
        assert _is_date_valid(expiry, check_before) is True
        assert _is_date_valid(expiry, check_after) is False


class TestInstitutionLicenseCheck:
    def test_valid_license(self, db_session, test_institution_valid):
        is_valid, detail, lic = check_institution_license_valid(
            db_session, test_institution_valid.id
        )
        assert is_valid is True
        assert lic is not None
        assert "许可证号" in detail
        assert "PDYTEST001" in detail

    def test_expired_license(self, db_session, test_institution_expired):
        is_valid, detail, lic = check_institution_license_valid(
            db_session, test_institution_expired.id
        )
        assert is_valid is False
        assert lic is not None
        assert "已过期" in detail
        assert "许可证已过期" in detail

    def test_expired_license_with_check_date(self, db_session, test_institution_expired):
        check_date = date(2022, 1, 1)
        is_valid, detail, lic = check_institution_license_valid(
            db_session, test_institution_expired.id, check_date
        )
        assert is_valid is True
        assert lic is not None

        check_date = date(2024, 1, 1)
        is_valid, detail, lic = check_institution_license_valid(
            db_session, test_institution_expired.id, check_date
        )
        assert is_valid is False
        assert "已过期" in detail

    def test_no_license(self, db_session, test_institution_no_license):
        is_valid, detail, lic = check_institution_license_valid(
            db_session, test_institution_no_license.id
        )
        assert is_valid is False
        assert lic is None
        assert "无有效医疗机构执业许可证" in detail

    def test_invalid_license_marked(self, db_session, test_institution_valid):
        from app.models import InstitutionLicense
        lic = db_session.query(InstitutionLicense).filter(
            InstitutionLicense.institution_id == test_institution_valid.id
        ).first()
        lic.is_valid = False
        db_session.flush()

        is_valid, detail, lic_result = check_institution_license_valid(
            db_session, test_institution_valid.id
        )
        assert is_valid is False
        assert lic_result is None
        assert "无有效医疗机构执业许可证" in detail


class TestPractitionerQualificationCheck:
    def test_doctor_qualification_valid(
        self, db_session, test_practitioner_fully_qualified
    ):
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_fully_qualified.id,
            QualificationType.DOCTOR
        )
        assert is_valid is True
        assert detail is None

    def test_practice_qualification_valid(
        self, db_session, test_practitioner_fully_qualified
    ):
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_fully_qualified.id,
            QualificationType.PRACTICE
        )
        assert is_valid is True
        assert detail is None

    def test_cosmetology_qualification_valid(
        self, db_session, test_practitioner_fully_qualified
    ):
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_fully_qualified.id,
            QualificationType.COSMETOLOGY
        )
        assert is_valid is True
        assert detail is None

    def test_qualification_expired(
        self, db_session, test_practitioner_license_expired
    ):
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_license_expired.id,
            QualificationType.PRACTICE
        )
        assert is_valid is False
        assert "已过期" in detail
        assert "医师执业证" in detail

    def test_qualification_expired_with_check_date(
        self, db_session, test_practitioner_license_expired
    ):
        check_date = date(2023, 1, 1)
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_license_expired.id,
            QualificationType.PRACTICE,
            check_date
        )
        assert is_valid is True
        assert detail is None

        check_date = date(2024, 1, 1)
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_license_expired.id,
            QualificationType.PRACTICE,
            check_date
        )
        assert is_valid is False
        assert "已过期" in detail

    def test_no_qualification(self, db_session, test_practitioner_unlicensed):
        is_valid, detail = check_practitioner_qualification_valid(
            db_session,
            test_practitioner_unlicensed.id,
            QualificationType.DOCTOR
        )
        assert is_valid is False
        assert "无有效医师资格证" in detail


class TestPractitionerCoreQualifications:
    def test_fully_qualified_practitioner(
        self, db_session, test_practitioner_fully_qualified
    ):
        issues = check_practitioner_core_qualifications(
            db_session, test_practitioner_fully_qualified.id
        )
        assert len(issues) == 0

    def test_expired_license_practitioner(
        self, db_session, test_practitioner_license_expired
    ):
        issues = check_practitioner_core_qualifications(
            db_session, test_practitioner_license_expired.id
        )
        assert len(issues) == 1
        assert "医师执业证已过期" in issues[0]

    def test_unlicensed_practitioner(
        self, db_session, test_practitioner_unlicensed
    ):
        issues = check_practitioner_core_qualifications(
            db_session, test_practitioner_unlicensed.id
        )
        assert len(issues) == 2
        assert any("医师资格证" in issue for issue in issues)
        assert any("医师执业证" in issue for issue in issues)

    def test_doctor_qualification_invalid_marked(
        self, db_session, test_practitioner_fully_qualified
    ):
        from app.models import PractitionerQualification
        qual = db_session.query(PractitionerQualification).filter(
            PractitionerQualification.practitioner_id == test_practitioner_fully_qualified.id,
            PractitionerQualification.qualification_type == QualificationType.DOCTOR
        ).first()
        qual.is_valid = False
        db_session.flush()

        issues = check_practitioner_core_qualifications(
            db_session, test_practitioner_fully_qualified.id
        )
        assert len(issues) == 1
        assert "无有效医师资格证" in issues[0]


class TestUnlicensedPractitionerCount:
    def test_count_with_mixed_practitioners(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_practitioner_license_expired,
        test_practitioner_unlicensed
    ):
        unlicensed, total = count_unlicensed_practitioners(
            db_session, test_institution_valid.id
        )
        assert total == 3
        assert unlicensed == 2

    def test_count_institution_specific(
        self,
        db_session,
        test_institution_valid,
        test_institution_no_license,
        test_practitioner_fully_qualified
    ):
        from app.models import Practitioner
        other_prac = Practitioner(
            name="其他机构人员",
            id_card="310101199001010099",
            gender="男",
            birth_date=date(1990, 1, 1),
            institution_id=test_institution_no_license.id,
            position="医师"
        )
        db_session.add(other_prac)
        db_session.flush()

        unlicensed, total = count_unlicensed_practitioners(
            db_session, test_institution_valid.id
        )
        assert total == 1
        assert unlicensed == 0

        unlicensed_all, total_all = count_unlicensed_practitioners(db_session)
        assert total_all == 2
        assert unlicensed_all == 1

    def test_count_with_check_date(
        self,
        db_session,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_practitioner_license_expired
    ):
        check_date = date(2023, 1, 1)
        unlicensed, total = count_unlicensed_practitioners(
            db_session, test_institution_valid.id, check_date
        )
        assert total == 2
        assert unlicensed == 0

        check_date = date(2024, 1, 1)
        unlicensed, total = count_unlicensed_practitioners(
            db_session, test_institution_valid.id, check_date
        )
        assert total == 2
        assert unlicensed == 1


class TestInstitutionComplianceAPI:
    def test_institution_compliance_check_valid(
        self, client, test_institution_valid
    ):
        response = client.get(
            f"/api/compliance/institution/{test_institution_valid.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["institution_id"] == test_institution_valid.id
        assert data["has_valid_license"] is True
        assert "许可证号" in data["license_detail"]

    def test_institution_compliance_check_expired(
        self, client, test_institution_expired
    ):
        response = client.get(
            f"/api/compliance/institution/{test_institution_expired.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_valid_license"] is False
        assert "已过期" in data["license_detail"]

    def test_institution_compliance_check_no_license(
        self, client, test_institution_no_license
    ):
        response = client.get(
            f"/api/compliance/institution/{test_institution_no_license.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_valid_license"] is False
        assert "无有效医疗机构执业许可证" in data["license_detail"]

    def test_institution_compliance_not_found(self, client):
        response = client.get("/api/compliance/institution/99999")
        assert response.status_code == 404
        assert "机构不存在" in response.json()["detail"]

    def test_institution_compliance_with_practitioners(
        self,
        client,
        test_institution_valid,
        test_practitioner_fully_qualified,
        test_practitioner_unlicensed
    ):
        response = client.get(
            f"/api/compliance/institution/{test_institution_valid.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_practitioners"] == 2
        assert data["unlicensed_practitioners"] == 1


class TestPractitionerComplianceAPI:
    def test_practitioner_compliance_fully_qualified(
        self, client, test_practitioner_fully_qualified
    ):
        response = client.get(
            f"/api/compliance/practitioner/{test_practitioner_fully_qualified.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["practitioner_id"] == test_practitioner_fully_qualified.id
        assert data["has_valid_doctor_license"] is True
        assert data["has_valid_practice_license"] is True
        assert data["has_cosmetology_license"] is True
        assert data["is_unlicensed"] is False

    def test_practitioner_compliance_expired(
        self, client, test_practitioner_license_expired
    ):
        response = client.get(
            f"/api/compliance/practitioner/{test_practitioner_license_expired.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_valid_doctor_license"] is True
        assert data["has_valid_practice_license"] is False
        assert data["has_cosmetology_license"] is False
        assert data["is_unlicensed"] is True

    def test_practitioner_compliance_unlicensed(
        self, client, test_practitioner_unlicensed
    ):
        response = client.get(
            f"/api/compliance/practitioner/{test_practitioner_unlicensed.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_valid_doctor_license"] is False
        assert data["has_valid_practice_license"] is False
        assert data["has_cosmetology_license"] is False
        assert data["is_unlicensed"] is True

    def test_practitioner_compliance_not_found(self, client):
        response = client.get("/api/compliance/practitioner/99999")
        assert response.status_code == 404
        assert "人员不存在" in response.json()["detail"]
