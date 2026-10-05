from datetime import date, datetime

import pytest

from app.models import (
    ClueType, ClueStatus, CluePriority,
    ViolationClue, InspectionRecord,
    ProcedureCategory
)


class TestClueCRUD:
    def test_create_clue(self, client, test_multi_clue_institution, test_procedures):
        clue_data = {
            "clue_type": "疑似速成班培训",
            "title": "测试新增速成班线索",
            "description": "这是一条测试线索，人员疑似仅参加3天培训",
            "institution_id": test_multi_clue_institution.id,
            "procedure_id": test_procedures["TEST-003"].id,
            "source": "测试",
            "priority": "高"
        }
        response = client.post("/api/clues/", json=clue_data)
        assert response.status_code == 200
        data = response.json()
        assert data["clue_type"] == "疑似速成班培训"
        assert data["status"] == "待分派"
        assert data["id"] is not None

    def test_create_clue_invalid_institution(self, client):
        clue_data = {
            "clue_type": "疑似速成班培训",
            "title": "测试线索",
            "description": "测试",
            "institution_id": 99999,
            "priority": "中"
        }
        response = client.post("/api/clues/", json=clue_data)
        assert response.status_code == 404
        assert "关联机构不存在" in response.json()["detail"]

    def test_list_clues(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/clues/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

    def test_get_clue_detail(self, client, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][0].id
        response = client.get(f"/api/clues/{clue_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == clue_id
        assert data["clue_type"] == "疑似速成班培训"

    def test_get_clue_not_found(self, client):
        response = client.get("/api/clues/99999")
        assert response.status_code == 404
        assert "线索不存在" in response.json()["detail"]

    def test_update_clue(self, client, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][0].id
        update_data = {
            "title": "更新后的线索标题",
            "priority": "高"
        }
        response = client.put(f"/api/clues/{clue_id}", json=update_data)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "更新后的线索标题"
        assert data["priority"] == "高"

    def test_delete_clue(self, client, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][0].id
        response = client.delete(f"/api/clues/{clue_id}")
        assert response.status_code == 200

        response = client.get(f"/api/clues/{clue_id}")
        assert response.status_code == 404


class TestClueLifecycle:
    def test_assign_clue(self, client, create_test_clues):
        test_data = create_test_clues()
        pending_clue = test_data["clues"][0]
        assert pending_clue.status == ClueStatus.PENDING

        response = client.post(
            f"/api/clues/{pending_clue.id}/assign",
            json={"assignee": "测试稽查员"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "核查中"
        assert data["assignee"] == "测试稽查员"
        assert data["assigned_at"] is not None

    def test_conclude_clue_verified(self, client, create_test_clues):
        test_data = create_test_clues()
        pending_clue = test_data["clues"][0]

        client.post(
            f"/api/clues/{pending_clue.id}/assign",
            json={"assignee": "测试稽查员"}
        )

        response = client.post(
            f"/api/clues/{pending_clue.id}/conclude",
            json={
                "status": "已核实违规",
                "conclusion": "经核查，情况属实，已立案查处"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "已核实违规"
        assert data["conclusion"] == "经核查，情况属实，已立案查处"
        assert data["verified_at"] is not None

    def test_conclude_clue_dismissed(self, client, create_test_clues):
        test_data = create_test_clues()
        pending_clue = test_data["clues"][0]

        client.post(
            f"/api/clues/{pending_clue.id}/assign",
            json={"assignee": "测试稽查员"}
        )

        response = client.post(
            f"/api/clues/{pending_clue.id}/conclude",
            json={
                "status": "已排除",
                "conclusion": "经核实，不属实"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "已排除"
        assert data["conclusion"] == "经核实，不属实"
        assert data["verified_at"] is not None

    def test_conclude_clue_invalid_status(self, client, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][0].id

        response = client.post(
            f"/api/clues/{clue_id}/conclude",
            json={
                "status": "核查中",
                "conclusion": "无效状态"
            }
        )
        assert response.status_code == 400
        assert "结论状态只能为已核实违规或已排除" in response.json()["detail"]

    def test_add_inspection_record(self, client, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][0].id

        inspection_data = {
            "clue_id": clue_id,
            "inspector": "稽查员测试",
            "inspection_date": "2024-01-20",
            "content": "现场检查，调取相关资质材料",
            "finding": "发现资质不全"
        }
        response = client.post(
            f"/api/clues/{clue_id}/inspections",
            json=inspection_data
        )
        assert response.status_code == 200
        data = response.json()
        assert data["inspector"] == "稽查员测试"
        assert data["finding"] == "发现资质不全"

    def test_list_inspection_records(self, client, db_session, create_test_clues):
        test_data = create_test_clues()
        clue_id = test_data["clues"][1].id

        insp1 = InspectionRecord(
            clue_id=clue_id,
            inspector="稽查员A",
            inspection_date=date(2024, 1, 16),
            content="第一次检查",
            finding="发现问题"
        )
        insp2 = InspectionRecord(
            clue_id=clue_id,
            inspector="稽查员A",
            inspection_date=date(2024, 1, 18),
            content="第二次复查",
            finding="确认违规"
        )
        db_session.add_all([insp1, insp2])
        db_session.flush()

        response = client.get(f"/api/clues/{clue_id}/inspections")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_filter_clues_by_type(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/clues/?clue_type=疑似速成班培训")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        for clue in data:
            assert clue["clue_type"] == "疑似速成班培训"

    def test_filter_clues_by_status(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/clues/?status=已核实违规")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        for clue in data:
            assert clue["status"] == "已核实违规"

    def test_filter_clues_by_priority(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/clues/?priority=高")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_filter_clues_by_assignee(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/clues/?assignee=稽查员A")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        for clue in data:
            assert clue["assignee"] == "稽查员A"


class TestMultiClueStatistics:
    def test_stats_summary(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/stats/summary")
        assert response.status_code == 200
        data = response.json()

        assert data["clues"]["total"] == 5
        assert data["clues"]["pending"] == 1
        assert data["clues"]["assigned"] == 1
        assert data["clues"]["verified_violations"] == 2
        assert data["clues"]["dismissed"] == 1

    def test_stats_by_institution(self, client, create_test_clues):
        test_data = create_test_clues()
        inst_id = test_data["clues"][0].institution_id

        response = client.get("/api/stats/by-institution")
        assert response.status_code == 200
        data = response.json()

        target = next((d for d in data if d["institution_id"] == inst_id), None)
        assert target is not None
        assert target["total_clues"] == 5
        assert target["verified_violations"] == 2
        assert target["pending_clues"] == 2

    def test_clue_type_distribution(self, client, db_session, create_test_clues):
        test_data = create_test_clues()
        inst_id = test_data["clues"][0].institution_id

        quick_training = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst_id,
            ViolationClue.clue_type == ClueType.QUICK_TRAINING
        ).count()
        assert quick_training == 2

        unlicensed = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst_id,
            ViolationClue.clue_type == ClueType.UNLICENSED_STAFF
        ).count()
        assert unlicensed == 1

        false_ad = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst_id,
            ViolationClue.clue_type == ClueType.FALSE_ADVERTISEMENT
        ).count()
        assert false_ad == 1

        over_range = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst_id,
            ViolationClue.clue_type == ClueType.OVER_RANGE_PRACTICE
        ).count()
        assert over_range == 1

        total = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst_id
        ).count()
        assert total == 5
        assert total == quick_training + unlicensed + false_ad + over_range

    def test_stats_by_category(self, client, db_session, create_test_clues, test_procedures):
        test_data = create_test_clues()
        inst_id = test_data["clues"][0].institution_id

        from app.models import ActualProcedureRecord, InstitutionAuthorizedProcedure

        auth_procs = [
            test_procedures["TEST-001"],
            test_procedures["TEST-005"]
        ]

        for proc in auth_procs:
            db_session.add(InstitutionAuthorizedProcedure(
                institution_id=inst_id,
                procedure_id=proc.id,
                authorized_date=date(2023, 1, 1)
            ))
        db_session.flush()

        actual_records = [
            ActualProcedureRecord(
                institution_id=inst_id,
                practitioner_id=test_data["practitioners"][0].id,
                procedure_id=test_procedures["TEST-001"].id,
                procedure_date=date(2024, 1, 10),
                patient_count=3,
                is_over_range=False
            ),
            ActualProcedureRecord(
                institution_id=inst_id,
                practitioner_id=test_data["practitioners"][1].id,
                procedure_id=test_procedures["TEST-003"].id,
                procedure_date=date(2024, 1, 12),
                patient_count=5,
                is_over_range=True,
                over_range_detail="人员无资质"
            ),
            ActualProcedureRecord(
                institution_id=inst_id,
                practitioner_id=test_data["practitioners"][1].id,
                procedure_id=test_procedures["TEST-006"].id,
                procedure_date=date(2024, 1, 15),
                patient_count=2,
                is_over_range=True,
                over_range_detail="机构无授权，人员无资质"
            ),
            ActualProcedureRecord(
                institution_id=inst_id,
                practitioner_id=test_data["practitioners"][0].id,
                procedure_id=test_procedures["TEST-004"].id,
                procedure_date=date(2024, 1, 18),
                patient_count=4,
                is_over_range=True,
                over_range_detail="机构无授权"
            ),
            ActualProcedureRecord(
                institution_id=inst_id,
                practitioner_id=test_data["practitioners"][0].id,
                procedure_id=test_procedures["TEST-005"].id,
                procedure_date=date(2024, 1, 20),
                patient_count=6,
                is_over_range=False
            ),
        ]
        for r in actual_records:
            db_session.add(r)
        db_session.flush()

        response = client.get("/api/stats/by-category")
        assert response.status_code == 200
        data = response.json()

        surgery_stats = next(
            (d for d in data if d["category"] == "手术类"), None
        )
        assert surgery_stats is not None
        assert surgery_stats["total_actual"] == 1
        assert surgery_stats["over_range_count"] == 0
        assert surgery_stats["over_range_ratio"] == 0.0

        injection_stats = next(
            (d for d in data if d["category"] == "注射类"), None
        )
        assert injection_stats is not None
        assert injection_stats["total_actual"] == 2
        assert injection_stats["over_range_count"] == 2
        assert injection_stats["over_range_ratio"] == 1.0

        photoelectric_stats = next(
            (d for d in data if d["category"] == "光电类"), None
        )
        assert photoelectric_stats is not None
        assert photoelectric_stats["total_actual"] == 2
        assert photoelectric_stats["over_range_count"] == 1
        assert photoelectric_stats["over_range_ratio"] == 0.5

        total_actual = sum(d["total_actual"] for d in data)
        total_over_range = sum(d["over_range_count"] for d in data)
        assert total_actual == 5
        assert total_over_range == 3

    def test_problem_institutions(self, client, create_test_clues):
        create_test_clues()
        response = client.get("/api/stats/problem-institutions?threshold=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_no_double_counting_in_stats(self, client, db_session, test_multi_clue_institution, test_procedures):
        from app.models import ActualProcedureRecord, InstitutionAuthorizedProcedure

        for proc_code in ["TEST-001", "TEST-003", "TEST-005"]:
            db_session.add(InstitutionAuthorizedProcedure(
                institution_id=test_multi_clue_institution.id,
                procedure_id=test_procedures[proc_code].id,
                authorized_date=date(2023, 1, 1)
            ))

        record_surgery = ActualProcedureRecord(
            institution_id=test_multi_clue_institution.id,
            practitioner_id=1,
            procedure_id=test_procedures["TEST-001"].id,
            procedure_date=date(2024, 1, 10),
            patient_count=2,
            is_over_range=False
        )
        record_injection = ActualProcedureRecord(
            institution_id=test_multi_clue_institution.id,
            practitioner_id=1,
            procedure_id=test_procedures["TEST-003"].id,
            procedure_date=date(2024, 1, 11),
            patient_count=3,
            is_over_range=True,
            over_range_detail="人员无资质"
        )
        record_photo = ActualProcedureRecord(
            institution_id=test_multi_clue_institution.id,
            practitioner_id=1,
            procedure_id=test_procedures["TEST-005"].id,
            procedure_date=date(2024, 1, 12),
            patient_count=1,
            is_over_range=False
        )
        db_session.add_all([record_surgery, record_injection, record_photo])
        db_session.flush()

        clue1 = ViolationClue(
            clue_type=ClueType.QUICK_TRAINING,
            title="速成班线索1",
            description="测试",
            institution_id=test_multi_clue_institution.id,
            source="测试",
            status=ClueStatus.VERIFIED,
            conclusion="违规"
        )
        clue2 = ViolationClue(
            clue_type=ClueType.UNLICENSED_STAFF,
            title="无证线索1",
            description="测试",
            institution_id=test_multi_clue_institution.id,
            source="测试",
            status=ClueStatus.VERIFIED,
            conclusion="违规"
        )
        clue3 = ViolationClue(
            clue_type=ClueType.FALSE_ADVERTISEMENT,
            title="虚假宣传1",
            description="测试",
            institution_id=test_multi_clue_institution.id,
            source="测试",
            status=ClueStatus.VERIFIED,
            conclusion="违规"
        )
        db_session.add_all([clue1, clue2, clue3])
        db_session.flush()

        response = client.get("/api/stats/by-institution")
        assert response.status_code == 200
        data = response.json()

        target = next(
            (d for d in data if d["institution_id"] == test_multi_clue_institution.id),
            None
        )
        assert target is not None
        assert target["total_clues"] == 3
        assert target["verified_violations"] == 3
        assert target["over_range_count"] == 1

        response = client.get("/api/stats/summary")
        assert response.status_code == 200
        summary = response.json()
        assert summary["clues"]["total"] == 3
        assert summary["clues"]["verified_violations"] == 3
        assert summary["procedures"]["total_actual_records"] == 3
        assert summary["procedures"]["over_range_count"] == 1


class TestClueTypesAPI:
    def test_list_clue_types(self, client):
        response = client.get("/api/clues/types/list")
        assert response.status_code == 200
        data = response.json()
        assert "clue_types" in data
        assert len(data["clue_types"]) == 4
        assert "疑似速成班培训" in data["clue_types"]
        assert "无证人员上岗" in data["clue_types"]
        assert "广告虚假宣传" in data["clue_types"]
        assert "超范围执业" in data["clue_types"]

        assert "statuses" in data
        assert len(data["statuses"]) == 4

        assert "priorities" in data
        assert len(data["priorities"]) == 3
