from datetime import date

import pytest

from app.models import (
    InstitutionType, ProcedureCategory, SurgeryLevel,
    QualificationType, ClueType, ClueStatus, CluePriority,
    Institution, InstitutionLicense,
    Practitioner, PractitionerQualification,
    Procedure,
    InstitutionAuthorizedProcedure, PractitionerAuthorizedProcedure,
    ActualProcedureRecord, ViolationClue
)


class TestFullBusinessChain:
    def test_complete_compliance_check_chain(
        self, client, db_session, test_procedures
    ):
        print("\n" + "=" * 70)
        print("端到端全链路测试：医美资质核验完整流程")
        print("=" * 70)

        print("\n【第1步】创建测试机构并设置许可证")
        inst = Institution(
            name="全链路测试医美医院",
            unified_social_code="91310000FULLCHAIN01",
            institution_type=InstitutionType.HOSPITAL,
            legal_person="全链路法人",
            address="全链路测试地址",
            phone="021-88888888",
            registration_date=date(2020, 1, 1),
            business_scope="医疗美容科；美容外科；美容皮肤科"
        )
        db_session.add(inst)
        db_session.flush()

        lic = InstitutionLicense(
            institution_id=inst.id,
            license_number="PDY-FULLCHAIN-001",
            issuing_authority="全链路测试卫健委",
            issue_date=date(2020, 1, 15),
            valid_until=date(2030, 1, 14),
            approved_surgeries="美容外科一级、二级项目；美容皮肤科全部项目",
            is_valid=True
        )
        db_session.add(lic)
        db_session.flush()
        print(f"  ✓ 机构创建成功: {inst.name}")
        print(f"  ✓ 许可证创建成功，有效期至: {lic.valid_until}")

        print("\n【第2步】核验机构资质")
        response = client.get(f"/api/compliance/institution/{inst.id}")
        assert response.status_code == 200
        inst_check = response.json()
        assert inst_check["has_valid_license"] is True
        print(f"  ✓ 机构资质核验通过: has_valid_license={inst_check['has_valid_license']}")

        print("\n【第3步】创建从业人员并设置资质")
        prac_qualified = Practitioner(
            name="全链路张医生",
            id_card="310101198001018888",
            gender="男",
            birth_date=date(1980, 1, 1),
            institution_id=inst.id,
            position="美容外科主诊医师"
        )
        db_session.add(prac_qualified)
        db_session.flush()

        quals = [
            PractitionerQualification(
                practitioner_id=prac_qualified.id,
                qualification_type=QualificationType.DOCTOR,
                certificate_number="DOC-FULLCHAIN-001",
                issuing_authority="全链路测试卫健委",
                issue_date=date(2005, 6, 1),
                valid_until=None,
                practice_scope="外科专业",
                is_valid=True
            ),
            PractitionerQualification(
                practitioner_id=prac_qualified.id,
                qualification_type=QualificationType.PRACTICE,
                certificate_number="PRAC-FULLCHAIN-001",
                issuing_authority="全链路测试卫健委",
                issue_date=date(2006, 3, 1),
                valid_until=date(2030, 12, 31),
                practice_scope="外科专业;医疗美容科",
                is_valid=True
            ),
            PractitionerQualification(
                practitioner_id=prac_qualified.id,
                qualification_type=QualificationType.COSMETOLOGY,
                certificate_number="COS-FULLCHAIN-001",
                issuing_authority="全链路测试医学会",
                issue_date=date(2010, 5, 1),
                valid_until=None,
                practice_scope="美容外科",
                is_valid=True
            ),
        ]
        for q in quals:
            db_session.add(q)
        db_session.flush()
        print(f"  ✓ 从业人员创建成功: {prac_qualified.name}")
        print(f"  ✓ 三证齐全: 医师资格证、医师执业证、美容主诊医师资格证")

        prac_unqualified = Practitioner(
            name="全链路李注射",
            id_card="310101199501019999",
            gender="女",
            birth_date=date(1995, 1, 1),
            institution_id=inst.id,
            position="注射师"
        )
        db_session.add(prac_unqualified)
        db_session.flush()
        print(f"  ✓ 无证人员创建成功: {prac_unqualified.name} (无任何资质)")

        print("\n【第4步】核验人员资质")
        response = client.get(
            f"/api/compliance/practitioner/{prac_qualified.id}"
        )
        assert response.status_code == 200
        prac1_check = response.json()
        assert prac1_check["has_valid_doctor_license"] is True
        assert prac1_check["has_valid_practice_license"] is True
        assert prac1_check["has_cosmetology_license"] is True
        assert prac1_check["is_unlicensed"] is False
        print(f"  ✓ 合格人员核验通过: is_unlicensed={prac1_check['is_unlicensed']}")

        response = client.get(
            f"/api/compliance/practitioner/{prac_unqualified.id}"
        )
        assert response.status_code == 200
        prac2_check = response.json()
        assert prac2_check["has_valid_doctor_license"] is False
        assert prac2_check["has_valid_practice_license"] is False
        assert prac2_check["is_unlicensed"] is True
        print(f"  ✓ 无证人员正确识别: is_unlicensed={prac2_check['is_unlicensed']}")

        print("\n【第5步】设置机构和人员的项目授权")
        proc_surgery = test_procedures["TEST-001"]
        proc_injection = test_procedures["TEST-003"]
        proc_photo = test_procedures["TEST-005"]
        proc_level4 = test_procedures["TEST-002"]

        auths = [
            InstitutionAuthorizedProcedure(
                institution_id=inst.id,
                procedure_id=proc_surgery.id,
                authorized_date=date(2023, 1, 1)
            ),
            InstitutionAuthorizedProcedure(
                institution_id=inst.id,
                procedure_id=proc_injection.id,
                authorized_date=date(2023, 1, 1)
            ),
            InstitutionAuthorizedProcedure(
                institution_id=inst.id,
                procedure_id=proc_photo.id,
                authorized_date=date(2023, 1, 1)
            ),
        ]
        for auth in auths:
            db_session.add(auth)

        prac_auths = [
            PractitionerAuthorizedProcedure(
                practitioner_id=prac_qualified.id,
                procedure_id=proc_surgery.id,
                authorized_date=date(2023, 1, 1)
            ),
            PractitionerAuthorizedProcedure(
                practitioner_id=prac_qualified.id,
                procedure_id=proc_injection.id,
                authorized_date=date(2023, 1, 1)
            ),
        ]
        for auth in prac_auths:
            db_session.add(auth)
        db_session.flush()
        print(f"  ✓ 机构授权项目: {proc_surgery.name}, {proc_injection.name}, {proc_photo.name}")
        print(f"  ✓ 人员授权项目: {proc_surgery.name}, {proc_injection.name}")

        print("\n【第6步】项目分级验证")
        assert proc_surgery.category == ProcedureCategory.SURGERY
        assert proc_surgery.surgery_level == SurgeryLevel.LEVEL_1
        assert proc_injection.category == ProcedureCategory.INJECTION
        assert proc_photo.category == ProcedureCategory.PHOTOELECTRIC
        assert proc_level4.surgery_level == SurgeryLevel.LEVEL_4
        print(f"  ✓ 手术类项目分级正确: {proc_surgery.name} = {proc_surgery.category.value} (一级)")
        print(f"  ✓ 注射类项目分级正确: {proc_injection.name} = {proc_injection.category.value}")
        print(f"  ✓ 光电类项目分级正确: {proc_photo.name} = {proc_photo.category.value}")
        print(f"  ✓ 四级手术识别正确: {proc_level4.name} = {proc_level4.surgery_level.value}")

        print("\n【第7步】记录执业行为并判定超范围")
        print("  记录1：合格医生做授权的手术项目 → 合规")
        record_data1 = {
            "institution_id": inst.id,
            "practitioner_id": prac_qualified.id,
            "procedure_id": proc_surgery.id,
            "procedure_date": "2024-01-15",
            "patient_count": 3,
            "remark": "双眼皮成形术"
        }
        response = client.post(
            "/api/compliance/actual-procedure", json=record_data1
        )
        assert response.status_code == 200
        rec1 = response.json()
        assert rec1["is_over_range"] is False
        print(f"    ✓ 判定结果: is_over_range={rec1['is_over_range']}")

        print("  记录2：合格医生做未授权的光电项目 → 人员越权")
        record_data2 = {
            "institution_id": inst.id,
            "practitioner_id": prac_qualified.id,
            "procedure_id": proc_photo.id,
            "procedure_date": "2024-01-16",
            "patient_count": 5,
            "remark": "光子嫩肤（人员未授权）"
        }
        response = client.post(
            "/api/compliance/actual-procedure", json=record_data2
        )
        assert response.status_code == 200
        rec2 = response.json()
        assert rec2["is_over_range"] is True
        assert "人员未获得该项目操作授权" in rec2["over_range_detail"]
        assert "机构未获得该项目执业授权" not in rec2["over_range_detail"]
        print(f"    ✓ 判定结果: is_over_range={rec2['is_over_range']}")
        print(f"    ✓ 正确识别为人员越权，非机构问题")

        print("  记录3：无证人员做注射项目 → 人员无证+无授权")
        record_data3 = {
            "institution_id": inst.id,
            "practitioner_id": prac_unqualified.id,
            "procedure_id": proc_injection.id,
            "procedure_date": "2024-01-17",
            "patient_count": 4,
            "remark": "玻尿酸填充（无证人员操作）"
        }
        response = client.post(
            "/api/compliance/actual-procedure", json=record_data3
        )
        assert response.status_code == 200
        rec3 = response.json()
        assert rec3["is_over_range"] is True
        assert "人员无有效医师资格证" in rec3["over_range_detail"]
        assert "人员无有效医师执业证" in rec3["over_range_detail"]
        assert "人员未获得该项目操作授权" in rec3["over_range_detail"]
        print(f"    ✓ 判定结果: is_over_range={rec3['is_over_range']}")
        print(f"    ✓ 超范围详情: {rec3['over_range_detail']}")

        print("  记录4：机构未授权的四级手术 → 机构超范围")
        record_data4 = {
            "institution_id": inst.id,
            "practitioner_id": prac_qualified.id,
            "procedure_id": proc_level4.id,
            "procedure_date": "2024-01-18",
            "patient_count": 1,
            "remark": "下颌角整形（机构无授权）"
        }
        response = client.post(
            "/api/compliance/actual-procedure", json=record_data4
        )
        assert response.status_code == 200
        rec4 = response.json()
        assert rec4["is_over_range"] is True
        assert "机构未获得该项目执业授权" in rec4["over_range_detail"]
        print(f"    ✓ 判定结果: is_over_range={rec4['is_over_range']}")
        print(f"    ✓ 正确识别机构超范围")

        print("\n【第8步】验证自动生成的超范围线索")
        over_range_clues = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id,
            ViolationClue.clue_type == ClueType.OVER_RANGE_PRACTICE
        ).all()
        assert len(over_range_clues) == 3
        print(f"  ✓ 自动生成 {len(over_range_clues)} 条超范围执业线索")
        for clue in over_range_clues:
            print(f"    - {clue.title}")

        print("\n【第9步】手动登记其他类型线索")
        clue_quick = {
            "clue_type": "疑似速成班培训",
            "title": "全链路测试：无证人员疑似速成班",
            "description": f"从业人员{prac_unqualified.name}疑似仅参加3天培训即上岗",
            "institution_id": inst.id,
            "practitioner_id": prac_unqualified.id,
            "procedure_id": proc_injection.id,
            "source": "全链路测试",
            "priority": "高"
        }
        response = client.post("/api/clues/", json=clue_quick)
        assert response.status_code == 200
        clue1 = response.json()
        print(f"  ✓ 登记速成班线索: {clue1['title']}")

        clue_false_ad = {
            "clue_type": "广告虚假宣传",
            "title": "全链路测试：机构虚假宣传四级手术资质",
            "description": "机构官网宣传可开展下颌角整形等四级手术，但实际无资质",
            "institution_id": inst.id,
            "procedure_id": proc_level4.id,
            "source": "全链路测试",
            "priority": "中"
        }
        response = client.post("/api/clues/", json=clue_false_ad)
        assert response.status_code == 200
        clue2 = response.json()
        print(f"  ✓ 登记虚假宣传线索: {clue2['title']}")

        print("\n【第10步】分派线索并核查")
        print(f"  分派线索 {clue1['id']} 给稽查员张三")
        response = client.post(
            f"/api/clues/{clue1['id']}/assign",
            json={"assignee": "稽查员张三"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "核查中"
        assert response.json()["assignee"] == "稽查员张三"
        print(f"    ✓ 分派成功，状态变为：核查中")

        print(f"  为线索 {clue1['id']} 添加核查记录")
        inspection_data = {
            "clue_id": clue1["id"],
            "inspector": "稽查员张三",
            "inspection_date": "2024-01-20",
            "content": "现场检查，调取{prac_unqualified.name}的资质材料，发现其无法提供医师资格证和执业证，仅出示某商业培训机构3天培训结业证。",
            "finding": "非医师行医事实清楚"
        }
        response = client.post(
            f"/api/clues/{clue1['id']}/inspections",
            json=inspection_data
        )
        assert response.status_code == 200
        print(f"    ✓ 核查记录添加成功")

        print("\n【第11步】作出核查结论")
        print(f"  线索 {clue1['id']} 结论：已核实违规")
        response = client.post(
            f"/api/clues/{clue1['id']}/conclude",
            json={
                "status": "已核实违规",
                "conclusion": "经核查，{prac_unqualified.name}未取得医师资格证书和医师执业证书，仅持有某商业培训机构3天培训结业证书，属于非医师行医。已立案查处。"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "已核实违规"
        assert response.json()["verified_at"] is not None
        print(f"    ✓ 结论提交成功，状态变为：已核实违规")

        print(f"  线索 {clue2['id']} 结论：已排除")
        client.post(
            f"/api/clues/{clue2['id']}/assign",
            json={"assignee": "稽查员李四"}
        )
        response = client.post(
            f"/api/clues/{clue2['id']}/conclude",
            json={
                "status": "已排除",
                "conclusion": "经核实，机构已及时整改官网内容，未实际开展四级手术，不予处罚。"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "已排除"
        print(f"    ✓ 结论提交成功，状态变为：已排除")

        print("\n【第12步】统计验证，确保分类统计口径正确")
        print("  验证线索分类统计...")
        all_clues = db_session.query(ViolationClue).filter(
            ViolationClue.institution_id == inst.id
        ).all()

        quick_training_count = sum(
            1 for c in all_clues if c.clue_type == ClueType.QUICK_TRAINING
        )
        unlicensed_count = sum(
            1 for c in all_clues if c.clue_type == ClueType.UNLICENSED_STAFF
        )
        false_ad_count = sum(
            1 for c in all_clues if c.clue_type == ClueType.FALSE_ADVERTISEMENT
        )
        over_range_count = sum(
            1 for c in all_clues if c.clue_type == ClueType.OVER_RANGE_PRACTICE
        )

        assert quick_training_count == 1
        assert unlicensed_count == 0
        assert false_ad_count == 1
        assert over_range_count == 3
        assert len(all_clues) == 5
        assert len(all_clues) == quick_training_count + unlicensed_count + false_ad_count + over_range_count

        print(f"    ✓ 疑似速成班培训: {quick_training_count} 条")
        print(f"    ✓ 无证人员上岗: {unlicensed_count} 条")
        print(f"    ✓ 广告虚假宣传: {false_ad_count} 条")
        print(f"    ✓ 超范围执业: {over_range_count} 条")
        print(f"    ✓ 总计: {len(all_clues)} 条 (无重复、无遗漏)")

        print("\n  验证状态统计...")
        verified_count = sum(
            1 for c in all_clues if c.status == ClueStatus.VERIFIED
        )
        dismissed_count = sum(
            1 for c in all_clues if c.status == ClueStatus.DISMISSED
        )
        pending_count = sum(
            1 for c in all_clues if c.status == ClueStatus.PENDING
        )
        assigned_count = sum(
            1 for c in all_clues if c.status == ClueStatus.ASSIGNED
        )

        assert verified_count == 1
        assert dismissed_count == 1
        assert pending_count + assigned_count == 3
        assert len(all_clues) == verified_count + dismissed_count + pending_count + assigned_count

        print(f"    ✓ 已核实违规: {verified_count} 条")
        print(f"    ✓ 已排除: {dismissed_count} 条")
        print(f"    ✓ 待分派+核查中: {pending_count + assigned_count} 条")
        print(f"    ✓ 总计: {len(all_clues)} 条 (口径一致)")

        print("\n  验证API统计接口...")
        response = client.get("/api/stats/summary")
        assert response.status_code == 200
        summary = response.json()
        assert summary["clues"]["total"] == 5
        assert summary["clues"]["verified_violations"] == 1
        assert summary["clues"]["dismissed"] == 1
        assert summary["procedures"]["total_actual_records"] == 4
        assert summary["procedures"]["over_range_count"] == 3
        print(f"    ✓ 总线索数: {summary['clues']['total']}")
        print(f"    ✓ 已核实违规: {summary['clues']['verified_violations']}")
        print(f"    ✓ 总执业记录: {summary['procedures']['total_actual_records']}")
        print(f"    ✓ 超范围记录: {summary['procedures']['over_range_count']}")

        response = client.get("/api/stats/by-category")
        assert response.status_code == 200
        cat_data = response.json()
        surgery_stats = next(
            (d for d in cat_data if d["category"] == "手术类"), None
        )
        injection_stats = next(
            (d for d in cat_data if d["category"] == "注射类"), None
        )
        photoelectric_stats = next(
            (d for d in cat_data if d["category"] == "光电类"), None
        )

        assert surgery_stats["total_actual"] == 2
        assert surgery_stats["over_range_count"] == 1
        assert injection_stats["total_actual"] == 1
        assert injection_stats["over_range_count"] == 1
        assert photoelectric_stats["total_actual"] == 1
        assert photoelectric_stats["over_range_count"] == 1
        print(f"    ✓ 手术类: 实际 {surgery_stats['total_actual']}, 超范围 {surgery_stats['over_range_count']}")
        print(f"    ✓ 注射类: 实际 {injection_stats['total_actual']}, 超范围 {injection_stats['over_range_count']}")
        print(f"    ✓ 光电类: 实际 {photoelectric_stats['total_actual']}, 超范围 {photoelectric_stats['over_range_count']}")

        print("\n" + "=" * 70)
        print("✓ 全链路测试通过！所有业务流程验证正确")
        print("=" * 70)

    def test_license_expiry_boundary(
        self, client, db_session, test_procedures
    ):
        print("\n" + "=" * 70)
        print("边界测试：许可证过期时间点验证")
        print("=" * 70)

        inst = Institution(
            name="边界测试诊所",
            unified_social_code="91310000BOUNDARY01",
            institution_type=InstitutionType.CLINIC,
            legal_person="边界法人",
            address="边界测试地址",
            phone="021-77777777",
            registration_date=date(2020, 1, 1),
            business_scope="医疗美容科；美容皮肤科"
        )
        db_session.add(inst)
        db_session.flush()

        expiry_date = date(2024, 6, 30)
        lic = InstitutionLicense(
            institution_id=inst.id,
            license_number="PDY-BOUNDARY-001",
            issuing_authority="边界测试卫健委",
            issue_date=date(2020, 1, 15),
            valid_until=expiry_date,
            approved_surgeries="美容皮肤科光电类项目",
            is_valid=True
        )
        db_session.add(lic)
        db_session.flush()

        prac = Practitioner(
            name="边界张医生",
            id_card="310101198001017777",
            gender="男",
            birth_date=date(1980, 1, 1),
            institution_id=inst.id,
            position="皮肤科医师"
        )
        db_session.add(prac)
        db_session.flush()

        quals = [
            PractitionerQualification(
                practitioner_id=prac.id,
                qualification_type=QualificationType.DOCTOR,
                certificate_number="DOC-BOUNDARY-001",
                issuing_authority="边界测试卫健委",
                issue_date=date(2005, 6, 1),
                valid_until=None,
                practice_scope="皮肤病与性病专业",
                is_valid=True
            ),
            PractitionerQualification(
                practitioner_id=prac.id,
                qualification_type=QualificationType.PRACTICE,
                certificate_number="PRAC-BOUNDARY-001",
                issuing_authority="边界测试卫健委",
                issue_date=date(2006, 3, 1),
                valid_until=None,
                practice_scope="皮肤病与性病专业;医疗美容科",
                is_valid=True
            ),
        ]
        for q in quals:
            db_session.add(q)

        proc = test_procedures["TEST-005"]
        db_session.add(InstitutionAuthorizedProcedure(
            institution_id=inst.id,
            procedure_id=proc.id,
            authorized_date=date(2023, 1, 1)
        ))
        db_session.add(PractitionerAuthorizedProcedure(
            practitioner_id=prac.id,
            procedure_id=proc.id,
            authorized_date=date(2023, 1, 1)
        ))
        db_session.flush()

        print(f"\n许可证有效期至: {expiry_date}")

        print(f"\n测试1：许可证到期前一天 ({date(2024, 6, 29)}) → 有效")
        response = client.get(
            "/api/compliance/check/single",
            params={
                "institution_id": inst.id,
                "practitioner_id": prac.id,
                "procedure_id": proc.id,
                "procedure_date": "2024-06-29"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is False
        print(f"  ✓ 判定: is_over_range={data['is_over_range']} (正确)")

        print(f"\n测试2：许可证到期当天 ({date(2024, 6, 30)}) → 有效")
        response = client.get(
            "/api/compliance/check/single",
            params={
                "institution_id": inst.id,
                "practitioner_id": prac.id,
                "procedure_id": proc.id,
                "procedure_date": "2024-06-30"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is False
        print(f"  ✓ 判定: is_over_range={data['is_over_range']} (正确)")

        print(f"\n测试3：许可证到期后一天 ({date(2024, 7, 1)}) → 超范围")
        response = client.get(
            "/api/compliance/check/single",
            params={
                "institution_id": inst.id,
                "practitioner_id": prac.id,
                "procedure_id": proc.id,
                "procedure_date": "2024-07-01"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_over_range"] is True
        assert any("许可证已过期" in issue for issue in data["issues"])
        print(f"  ✓ 判定: is_over_range={data['is_over_range']} (正确)")
        print(f"  ✓ 问题: {data['issues'][0]}")

        print("\n" + "=" * 70)
        print("✓ 边界测试通过！许可证过期时间点判定正确")
        print("=" * 70)
