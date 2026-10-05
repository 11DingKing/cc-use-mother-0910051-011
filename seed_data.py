import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models import (
    Institution, InstitutionType, InstitutionLicense,
    Practitioner, PractitionerQualification, QualificationType,
    Procedure, ProcedureCategory, SurgeryLevel,
    InstitutionAuthorizedProcedure, PractitionerAuthorizedProcedure,
    ActualProcedureRecord,
    ViolationClue, ClueType, ClueStatus, CluePriority,
    InspectionRecord,
    ComplianceScore, SupervisionPlan, ComplianceGrade,
    ScoreItem, InspectionFrequency, PlanStatus
)

from app.routers.compliance_score import (
    calculate_compliance_score, save_compliance_score,
    generate_inspection_plans
)


def seed_data():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("开始初始化数据...")

        institutions = [
            {
                "name": "华美医疗美容医院",
                "unified_social_code": "91310000MA1FL001",
                "institution_type": InstitutionType.HOSPITAL,
                "legal_person": "张建国",
                "address": "上海市浦东新区世纪大道100号",
                "phone": "021-58880001",
                "registration_date": date(2018, 3, 15),
                "business_scope": "医疗美容科；美容外科；美容皮肤科；美容中医科"
            },
            {
                "name": "悦美医疗美容诊所",
                "unified_social_code": "91310000MA1FL002",
                "institution_type": InstitutionType.CLINIC,
                "legal_person": "李美丽",
                "address": "上海市静安区南京西路888号",
                "phone": "021-62220002",
                "registration_date": date(2020, 7, 1),
                "business_scope": "医疗美容科；美容皮肤科"
            },
            {
                "name": "丽人医疗美容门诊部",
                "unified_social_code": "91310000MA1FL003",
                "institution_type": InstitutionType.OUTPATIENT,
                "legal_person": "王芳华",
                "address": "上海市徐汇区衡山路500号",
                "phone": "021-64440003",
                "registration_date": date(2019, 11, 20),
                "business_scope": "医疗美容科；美容外科；美容牙科"
            },
            {
                "name": "星光整形医院",
                "unified_social_code": "91310000MA1FL004",
                "institution_type": InstitutionType.HOSPITAL,
                "legal_person": "陈星光",
                "address": "上海市黄浦区淮海中路200号",
                "phone": "021-63330004",
                "registration_date": date(2017, 5, 10),
                "business_scope": "医疗美容科；美容外科一级二级项目"
            },
            {
                "name": "轻颜皮肤管理中心",
                "unified_social_code": "91310000MA1FL005",
                "institution_type": InstitutionType.CLINIC,
                "legal_person": "刘轻颜",
                "address": "上海市长宁区虹桥路1000号",
                "phone": "021-62220005",
                "registration_date": date(2021, 2, 28),
                "business_scope": "医疗美容科；美容皮肤科"
            }
        ]

        db_institutions = []
        for inst_data in institutions:
            inst = Institution(**inst_data)
            db.add(inst)
            db_institutions.append(inst)
        db.flush()
        print(f"已创建 {len(db_institutions)} 家机构")

        institution_licenses = [
            {
                "institution_id": db_institutions[0].id,
                "license_number": "PDY123456-310115",
                "issuing_authority": "上海市浦东新区卫生健康委员会",
                "issue_date": date(2018, 3, 20),
                "valid_until": date(2028, 3, 19),
                "approved_surgeries": "美容外科一级、二级、三级项目；美容皮肤科全部项目",
                "is_valid": True
            },
            {
                "institution_id": db_institutions[1].id,
                "license_number": "PDY123457-310106",
                "issuing_authority": "上海市静安区卫生健康委员会",
                "issue_date": date(2020, 7, 10),
                "valid_until": date(2025, 7, 9),
                "approved_surgeries": "美容皮肤科光电类项目",
                "is_valid": True
            },
            {
                "institution_id": db_institutions[2].id,
                "license_number": "PDY123458-310104",
                "issuing_authority": "上海市徐汇区卫生健康委员会",
                "issue_date": date(2019, 12, 1),
                "valid_until": date(2024, 11, 30),
                "approved_surgeries": "美容外科一级项目；美容牙科项目",
                "is_valid": False
            },
            {
                "institution_id": db_institutions[3].id,
                "license_number": "PDY123459-310101",
                "issuing_authority": "上海市黄浦区卫生健康委员会",
                "issue_date": date(2017, 5, 20),
                "valid_until": date(2027, 5, 19),
                "approved_surgeries": "美容外科一级、二级项目",
                "is_valid": True
            },
            {
                "institution_id": db_institutions[4].id,
                "license_number": "PDY123460-310105",
                "issuing_authority": "上海市长宁区卫生健康委员会",
                "issue_date": date(2021, 3, 5),
                "valid_until": date(2026, 3, 4),
                "approved_surgeries": "美容皮肤科护理类项目",
                "is_valid": True
            }
        ]

        for lic_data in institution_licenses:
            db.add(InstitutionLicense(**lic_data))
        db.flush()
        print(f"已创建 {len(institution_licenses)} 条机构许可证")

        practitioners = [
            {
                "name": "张医生",
                "id_card": "310101198001010011",
                "gender": "男",
                "birth_date": date(1980, 1, 1),
                "institution_id": db_institutions[0].id,
                "position": "美容外科主任医师"
            },
            {
                "name": "李医生",
                "id_card": "310101198505050022",
                "gender": "女",
                "birth_date": date(1985, 5, 5),
                "institution_id": db_institutions[0].id,
                "position": "皮肤科副主任医师"
            },
            {
                "name": "王护士",
                "id_card": "310101199003030033",
                "gender": "女",
                "birth_date": date(1990, 3, 3),
                "institution_id": db_institutions[0].id,
                "position": "护士长"
            },
            {
                "name": "赵速成",
                "id_card": "310101199505050044",
                "gender": "女",
                "birth_date": date(1995, 5, 5),
                "institution_id": db_institutions[1].id,
                "position": "注射师"
            },
            {
                "name": "陈医生",
                "id_card": "310101197808080055",
                "gender": "男",
                "birth_date": date(1978, 8, 8),
                "institution_id": db_institutions[2].id,
                "position": "美容外科医师"
            },
            {
                "name": "刘无证",
                "id_card": "310101199212120066",
                "gender": "男",
                "birth_date": date(1992, 12, 12),
                "institution_id": db_institutions[2].id,
                "position": "光电操作师"
            },
            {
                "name": "孙医生",
                "id_card": "310101198206060077",
                "gender": "男",
                "birth_date": date(1982, 6, 6),
                "institution_id": db_institutions[3].id,
                "position": "整形外科副主任医师"
            },
            {
                "name": "周速成",
                "id_card": "310101199809090088",
                "gender": "女",
                "birth_date": date(1998, 9, 9),
                "institution_id": db_institutions[4].id,
                "position": "皮肤管理师"
            }
        ]

        db_practitioners = []
        for prac_data in practitioners:
            prac = Practitioner(**prac_data)
            db.add(prac)
            db_practitioners.append(prac)
        db.flush()
        print(f"已创建 {len(db_practitioners)} 名从业人员")

        qualifications = [
            {
                "practitioner_id": db_practitioners[0].id,
                "qualification_type": QualificationType.DOCTOR,
                "certificate_number": "199931110110101800101001",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2005, 6, 1),
                "valid_until": None,
                "practice_scope": "外科专业",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[0].id,
                "qualification_type": QualificationType.PRACTICE,
                "certificate_number": "110310000001001",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2006, 3, 1),
                "valid_until": date(2030, 12, 31),
                "practice_scope": "外科专业;医疗美容科",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[0].id,
                "qualification_type": QualificationType.COSMETOLOGY,
                "certificate_number": "MY-2010-0001",
                "issuing_authority": "上海市医学会",
                "issue_date": date(2010, 5, 1),
                "valid_until": None,
                "practice_scope": "美容外科",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[1].id,
                "qualification_type": QualificationType.DOCTOR,
                "certificate_number": "200831110110101850505002",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2010, 7, 1),
                "valid_until": None,
                "practice_scope": "皮肤病与性病专业",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[1].id,
                "qualification_type": QualificationType.PRACTICE,
                "certificate_number": "110310000001002",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2011, 4, 1),
                "valid_until": date(2028, 12, 31),
                "practice_scope": "皮肤病与性病专业;医疗美容科",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[2].id,
                "qualification_type": QualificationType.NURSE,
                "certificate_number": "201031220001",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2012, 5, 10),
                "valid_until": date(2027, 5, 9),
                "practice_scope": "护理专业",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[4].id,
                "qualification_type": QualificationType.DOCTOR,
                "certificate_number": "200331110110101780808005",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2005, 9, 1),
                "valid_until": None,
                "practice_scope": "外科专业",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[4].id,
                "qualification_type": QualificationType.PRACTICE,
                "certificate_number": "110310000001005",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2006, 6, 1),
                "valid_until": date(2024, 5, 31),
                "practice_scope": "外科专业",
                "is_valid": False
            },
            {
                "practitioner_id": db_practitioners[6].id,
                "qualification_type": QualificationType.DOCTOR,
                "certificate_number": "200631110110101820606007",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2008, 8, 1),
                "valid_until": None,
                "practice_scope": "外科专业",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[6].id,
                "qualification_type": QualificationType.PRACTICE,
                "certificate_number": "110310000001007",
                "issuing_authority": "上海市卫生健康委员会",
                "issue_date": date(2009, 5, 1),
                "valid_until": date(2029, 12, 31),
                "practice_scope": "外科专业;医疗美容科",
                "is_valid": True
            },
            {
                "practitioner_id": db_practitioners[6].id,
                "qualification_type": QualificationType.COSMETOLOGY,
                "certificate_number": "MY-2012-0007",
                "issuing_authority": "上海市医学会",
                "issue_date": date(2012, 8, 1),
                "valid_until": None,
                "practice_scope": "美容外科",
                "is_valid": True
            }
        ]

        for qual_data in qualifications:
            db.add(PractitionerQualification(**qual_data))
        db.flush()
        print(f"已创建 {len(qualifications)} 条人员资质")

        procedures = [
            {
                "name": "双眼皮成形术",
                "code": "MRSS-001",
                "category": ProcedureCategory.SURGERY,
                "surgery_level": SurgeryLevel.LEVEL_1,
                "description": "通过手术方式形成双眼皮",
                "requires_qualification": "美容外科主诊医师资格"
            },
            {
                "name": "假体隆鼻术",
                "code": "MRSS-002",
                "category": ProcedureCategory.SURGERY,
                "surgery_level": SurgeryLevel.LEVEL_1,
                "description": "植入假体进行隆鼻",
                "requires_qualification": "美容外科主诊医师资格"
            },
            {
                "name": "下颌角整形术",
                "code": "MRSS-003",
                "category": ProcedureCategory.SURGERY,
                "surgery_level": SurgeryLevel.LEVEL_4,
                "description": "四级颌面整形手术",
                "requires_qualification": "三级以上医院、副主任医师以上"
            },
            {
                "name": "肉毒素注射除皱",
                "code": "MRZS-001",
                "category": ProcedureCategory.INJECTION,
                "description": "注射肉毒素祛除皱纹",
                "requires_qualification": "医师执业证、注射培训合格"
            },
            {
                "name": "玻尿酸填充",
                "code": "MRZS-002",
                "category": ProcedureCategory.INJECTION,
                "description": "注射玻尿酸进行面部填充",
                "requires_qualification": "医师执业证、注射培训合格"
            },
            {
                "name": "水光针注射",
                "code": "MRZS-003",
                "category": ProcedureCategory.INJECTION,
                "description": "水光针注射补水",
                "requires_qualification": "医师或护士执业证"
            },
            {
                "name": "光子嫩肤",
                "code": "MRGD-001",
                "category": ProcedureCategory.PHOTOELECTRIC,
                "description": "强脉冲光嫩肤治疗",
                "requires_qualification": "皮肤科医师或经过培训的护士"
            },
            {
                "name": "点阵激光祛斑",
                "code": "MRGD-002",
                "category": ProcedureCategory.PHOTOELECTRIC,
                "description": "点阵激光祛除色斑",
                "requires_qualification": "皮肤科医师资格"
            },
            {
                "name": "热玛吉抗衰老",
                "code": "MRGD-003",
                "category": ProcedureCategory.PHOTOELECTRIC,
                "description": "射频紧肤抗衰老治疗",
                "requires_qualification": "医师或经过认证的操作人员"
            },
            {
                "name": "果酸换肤",
                "code": "MRPF-001",
                "category": ProcedureCategory.SKINCARE,
                "description": "化学剥脱术",
                "requires_qualification": "皮肤科医师指导"
            },
            {
                "name": "美容牙科美白",
                "code": "MRKQ-001",
                "category": ProcedureCategory.ORAL,
                "description": "冷光牙齿美白",
                "requires_qualification": "口腔执业医师资格"
            }
        ]

        db_procedures = []
        for proc_data in procedures:
            proc = Procedure(**proc_data)
            db.add(proc)
            db_procedures.append(proc)
        db.flush()
        print(f"已创建 {len(db_procedures)} 个医美项目")

        inst_auths = [
            (db_institutions[0].id, db_procedures[0].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[1].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[3].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[4].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[5].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[6].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[7].id, date(2018, 4, 1)),
            (db_institutions[0].id, db_procedures[8].id, date(2018, 4, 1)),
            (db_institutions[1].id, db_procedures[6].id, date(2020, 8, 1)),
            (db_institutions[2].id, db_procedures[0].id, date(2020, 1, 1)),
            (db_institutions[2].id, db_procedures[10].id, date(2020, 1, 1)),
            (db_institutions[3].id, db_procedures[0].id, date(2017, 6, 1)),
            (db_institutions[3].id, db_procedures[1].id, date(2017, 6, 1)),
            (db_institutions[4].id, db_procedures[9].id, date(2021, 4, 1)),
        ]

        for inst_id, proc_id, auth_date in inst_auths:
            db.add(InstitutionAuthorizedProcedure(
                institution_id=inst_id,
                procedure_id=proc_id,
                authorized_date=auth_date
            ))
        db.flush()
        print(f"已创建 {len(inst_auths)} 条机构项目授权")

        prac_auths = [
            (db_practitioners[0].id, db_procedures[0].id, date(2018, 4, 10)),
            (db_practitioners[0].id, db_procedures[1].id, date(2018, 4, 10)),
            (db_practitioners[0].id, db_procedures[3].id, date(2018, 4, 10)),
            (db_practitioners[0].id, db_procedures[4].id, date(2018, 4, 10)),
            (db_practitioners[1].id, db_procedures[6].id, date(2018, 4, 15)),
            (db_practitioners[1].id, db_procedures[7].id, date(2018, 4, 15)),
            (db_practitioners[1].id, db_procedures[8].id, date(2018, 4, 15)),
            (db_practitioners[6].id, db_procedures[0].id, date(2017, 6, 10)),
            (db_practitioners[6].id, db_procedures[1].id, date(2017, 6, 10)),
        ]

        for prac_id, proc_id, auth_date in prac_auths:
            db.add(PractitionerAuthorizedProcedure(
                practitioner_id=prac_id,
                procedure_id=proc_id,
                authorized_date=auth_date
            ))
        db.flush()
        print(f"已创建 {len(prac_auths)} 条人员项目授权")

        actual_records = [
            {
                "institution_id": db_institutions[0].id,
                "practitioner_id": db_practitioners[0].id,
                "procedure_id": db_procedures[0].id,
                "procedure_date": date(2024, 1, 10),
                "patient_count": 3,
                "remark": "正常合规操作"
            },
            {
                "institution_id": db_institutions[0].id,
                "practitioner_id": db_practitioners[1].id,
                "procedure_id": db_procedures[6].id,
                "procedure_date": date(2024, 1, 12),
                "patient_count": 8,
                "remark": "正常合规操作"
            },
            {
                "institution_id": db_institutions[0].id,
                "practitioner_id": db_practitioners[1].id,
                "procedure_id": db_procedures[7].id,
                "procedure_date": date(2024, 1, 15),
                "patient_count": 2,
                "remark": "正常合规操作"
            },
            {
                "institution_id": db_institutions[1].id,
                "practitioner_id": db_practitioners[3].id,
                "procedure_id": db_procedures[4].id,
                "procedure_date": date(2024, 1, 8),
                "patient_count": 5,
                "remark": "注射师无医师资格，人员未授权"
            },
            {
                "institution_id": db_institutions[1].id,
                "practitioner_id": db_practitioners[3].id,
                "procedure_id": db_procedures[3].id,
                "procedure_date": date(2024, 1, 20),
                "patient_count": 3,
                "remark": "注射师无医师资格，人员未授权"
            },
            {
                "institution_id": db_institutions[2].id,
                "practitioner_id": db_practitioners[4].id,
                "procedure_id": db_procedures[0].id,
                "procedure_date": date(2024, 2, 1),
                "patient_count": 2,
                "remark": "医师执业证已过期"
            },
            {
                "institution_id": db_institutions[2].id,
                "practitioner_id": db_practitioners[5].id,
                "procedure_id": db_procedures[7].id,
                "procedure_date": date(2024, 2, 5),
                "patient_count": 6,
                "remark": "光电操作师无任何资质，机构也未授权该项目"
            },
            {
                "institution_id": db_institutions[3].id,
                "practitioner_id": db_practitioners[6].id,
                "procedure_id": db_procedures[2].id,
                "procedure_date": date(2024, 1, 18),
                "patient_count": 1,
                "remark": "四级手术超范围执业，机构仅有一二级授权"
            },
            {
                "institution_id": db_institutions[4].id,
                "practitioner_id": db_practitioners[7].id,
                "procedure_id": db_procedures[6].id,
                "procedure_date": date(2024, 2, 10),
                "patient_count": 4,
                "remark": "皮肤管理师无医师证，机构也未授权光电项目"
            }
        ]

        for record_data in actual_records:
            inst_authorized = db.query(InstitutionAuthorizedProcedure).filter(
                InstitutionAuthorizedProcedure.institution_id == record_data["institution_id"],
                InstitutionAuthorizedProcedure.procedure_id == record_data["procedure_id"]
            ).first()

            prac_authorized = db.query(PractitionerAuthorizedProcedure).filter(
                PractitionerAuthorizedProcedure.practitioner_id == record_data["practitioner_id"],
                PractitionerAuthorizedProcedure.procedure_id == record_data["procedure_id"]
            ).first()

            is_over_range = not inst_authorized or not prac_authorized
            details = []
            if not inst_authorized:
                details.append("机构未获授权")
            if not prac_authorized:
                details.append("人员未获授权")

            db.add(ActualProcedureRecord(
                **record_data,
                is_over_range=is_over_range,
                over_range_detail="; ".join(details) if details else None
            ))
        db.flush()
        print(f"已创建 {len(actual_records)} 条实际项目记录")

        clues = [
            {
                "clue_type": ClueType.QUICK_TRAINING,
                "title": "悦美诊所涉嫌雇佣速成班培训人员",
                "description": "群众举报悦美医疗美容诊所注射师赵速成疑似仅参加过为期3天的轻医美速成班即上岗开展注射类项目，无正规医师资质。",
                "institution_id": db_institutions[1].id,
                "practitioner_id": db_practitioners[3].id,
                "procedure_id": db_procedures[4].id,
                "source": "12320卫生热线举报",
                "priority": CluePriority.HIGH,
                "status": ClueStatus.VERIFIED,
                "assignee": "稽查员王建国",
                "assigned_at": datetime(2024, 1, 25, 10, 0),
                "conclusion": "经核查，赵速成未取得医师资格证书和医师执业证书，仅持有某商业培训机构3天培训结业证书，属于无证人员上岗。已立案查处。",
                "verified_at": datetime(2024, 2, 1, 15, 30)
            },
            {
                "clue_type": ClueType.UNLICENSED_STAFF,
                "title": "丽人门诊部光电操作师无证上岗",
                "description": "日常监督检查发现丽人医疗美容门诊部光电操作师刘无证无法出示任何医师或护士执业证件，独立操作点阵激光设备开展祛斑治疗。",
                "institution_id": db_institutions[2].id,
                "practitioner_id": db_practitioners[5].id,
                "procedure_id": db_procedures[7].id,
                "source": "日常监督检查",
                "priority": CluePriority.HIGH,
                "status": ClueStatus.VERIFIED,
                "assignee": "稽查员李明",
                "assigned_at": datetime(2024, 2, 8, 9, 0),
                "conclusion": "核查确认刘无证未取得任何医疗卫生人员执业资格，独立开展医疗美容项目属于非医师行医。已依法处罚。",
                "verified_at": datetime(2024, 2, 15, 14, 0)
            },
            {
                "clue_type": ClueType.UNLICENSED_STAFF,
                "title": "轻颜皮肤管理中心皮肤管理师无证执业",
                "description": "网络舆情反映轻颜皮肤管理中心的周速成皮肤管理师在某社交平台展示操作热玛吉设备视频，疑似无资质。",
                "institution_id": db_institutions[4].id,
                "practitioner_id": db_practitioners[7].id,
                "procedure_id": db_procedures[8].id,
                "source": "网络舆情监测",
                "priority": CluePriority.MEDIUM,
                "status": ClueStatus.ASSIGNED,
                "assignee": "稽查员张华",
                "assigned_at": datetime(2024, 2, 18, 11, 0)
            },
            {
                "clue_type": ClueType.FALSE_ADVERTISEMENT,
                "title": "星光整形医院虚假宣传四级手术资质",
                "description": "星光整形医院官网宣传可开展下颌角整形等四级颌面整形手术，但其医疗机构执业许可证核准的手术级别仅为一、二级，涉嫌超范围宣传。",
                "institution_id": db_institutions[3].id,
                "procedure_id": db_procedures[2].id,
                "source": "广告监测",
                "priority": CluePriority.MEDIUM,
                "status": ClueStatus.VERIFIED,
                "assignee": "稽查员王建国",
                "assigned_at": datetime(2024, 1, 30, 10, 30),
                "conclusion": "经查证星光整形医院确实超出核准登记范围发布四级手术广告，违反《医疗广告管理办法》，已责令整改并处罚。",
                "verified_at": datetime(2024, 2, 10, 16, 0)
            },
            {
                "clue_type": ClueType.QUICK_TRAINING,
                "title": "多家机构人员疑似速成班培训上岗",
                "description": "自媒体曝光本市多家医美机构存在从业人员仅参加一周以内轻医美培训即上岗执业的情况，涉及注射、光电等多个项目。",
                "source": "媒体曝光",
                "priority": CluePriority.HIGH,
                "status": ClueStatus.PENDING
            },
            {
                "clue_type": ClueType.FALSE_ADVERTISEMENT,
                "title": "华美医院广告夸大效果承诺100%成功",
                "description": "华美医疗美容医院在地铁广告中宣传隆鼻手术成功率100%、零风险，涉嫌虚假宣传和夸大效果。",
                "institution_id": db_institutions[0].id,
                "procedure_id": db_procedures[1].id,
                "source": "广告监测",
                "priority": CluePriority.LOW,
                "status": ClueStatus.PENDING
            },
            {
                "clue_type": ClueType.UNLICENSED_STAFF,
                "title": "丽人门诊部医师执业证过期",
                "description": "丽人门诊部陈姓医师的医师执业证书已于2024年5月31日到期，目前仍在从事诊疗活动。",
                "institution_id": db_institutions[2].id,
                "practitioner_id": db_practitioners[4].id,
                "procedure_id": db_procedures[0].id,
                "source": "资质核验系统比对",
                "priority": CluePriority.MEDIUM,
                "status": ClueStatus.DISMISSED,
                "assignee": "稽查员李明",
                "assigned_at": datetime(2024, 2, 12, 9, 30),
                "conclusion": "经核实，该医师正在办理执业证延续注册，相关材料已提交，属于过渡阶段，已督促尽快完成注册。",
                "verified_at": datetime(2024, 2, 20, 10, 0)
            }
        ]

        db_clues = []
        for clue_data in clues:
            clue = ViolationClue(**clue_data)
            db.add(clue)
            db_clues.append(clue)
        db.flush()
        print(f"已创建 {len(db_clues)} 条违规线索")

        inspections = [
            {
                "clue_id": db_clues[0].id,
                "inspector": "稽查员王建国",
                "inspection_date": date(2024, 1, 28),
                "content": "现场检查悦美诊所，调取赵速成资质材料，发现其无法提供医师资格证、执业证，仅出示一张某医美培训中心3天结业证。现场询问5名就诊顾客，均确认由赵速成为其进行玻尿酸注射。",
                "finding": "非医师行医事实清楚，证据确凿"
            },
            {
                "clue_id": db_clues[0].id,
                "inspector": "稽查员王建国",
                "inspection_date": date(2024, 1, 30),
                "content": "对赵速成进行询问笔录，其承认仅参加3天速成班培训，缴纳学费8800元后获得结业证，未接受正规医学教育。对诊所法定代表人李美丽进行询问，其承认知道赵速成无医师资质但仍雇佣。",
                "finding": "机构使用非卫生技术人员"
            },
            {
                "clue_id": db_clues[1].id,
                "inspector": "稽查员李明",
                "inspection_date": date(2024, 2, 10),
                "content": "对丽人门诊部进行现场检查，刘无证正在操作点阵激光设备，当场无法出示任何执业资格证件。调阅近3个月就诊记录，发现其独立操作光电项目共计36例。",
                "finding": "无证人员独立开展医疗美容项目"
            },
            {
                "clue_id": db_clues[3].id,
                "inspector": "稽查员王建国",
                "inspection_date": date(2024, 2, 5),
                "content": "查看星光整形医院官方网站，发现其在项目介绍页面明确宣传可开展下颌角整形（四级手术），并配有多个案例。核对医疗机构执业许可证，核准诊疗科目仅包含美容外科一级、二级项目。",
                "finding": "超出核准范围发布医疗广告"
            }
        ]

        for insp_data in inspections:
            db.add(InspectionRecord(**insp_data))
        db.flush()
        print(f"已创建 {len(inspections)} 条核查记录")

        print("\n开始生成机构合规评分种子数据...")
        compliance_scores = []
        supervision_plans_count = 0

        for inst in db_institutions:
            try:
                result = calculate_compliance_score(inst.id, db)
                score_record = save_compliance_score(result, db, "初始化种子数据")
                plans = generate_inspection_plans(score_record, db)
                compliance_scores.append(score_record)
                supervision_plans_count += len(plans)
                print(f"  {inst.name}: {result.total_score}分 ({result.grade.value}级), 生成 {len(plans)} 个检查计划")
            except Exception as e:
                print(f"  {inst.name}: 评分生成失败 - {e}")
                continue

        print(f"\n已生成 {len(compliance_scores)} 条机构合规评分记录")
        print(f"已生成 {supervision_plans_count} 条监管检查计划")

        db.commit()
        print("\n数据初始化完成！")
        print(f"  机构数量: {len(db_institutions)}")
        print(f"  人员数量: {len(db_practitioners)}")
        print(f"  项目数量: {len(db_procedures)}")
        print(f"  实际记录: {len(actual_records)} (其中超范围 {sum(1 for r in actual_records if any(x in r['remark'] for x in ['无', '过期', '超范围', '未']))} 条)")
        print(f"  违规线索: {len(db_clues)}")
        print(f"  核查记录: {len(inspections)}")
        print(f"  合规评分记录: {len(compliance_scores)}")
        print(f"  监管检查计划: {supervision_plans_count}")
        print("\n机构合规评分详情:")
        grade_names = {
            ComplianceGrade.EXCELLENT: "优秀(A)",
            ComplianceGrade.GOOD: "良好(B)",
            ComplianceGrade.FAIR: "合格(C)",
            ComplianceGrade.POOR: "不合格(D)",
        }
        for cs in compliance_scores:
            inst = db.query(Institution).filter(Institution.id == cs.institution_id).first()
            freq_names = {
                InspectionFrequency.QUARTERLY: "每季度一次",
                InspectionFrequency.BIANNUAL: "每半年一次",
                InspectionFrequency.ANNUAL: "每年一次",
                InspectionFrequency.EXTENDED: "每两年一次",
            }
            print(f"  {inst.name if inst else '未知'}: {cs.total_score}分 - {grade_names.get(cs.grade, '未知')}, 检查频率: {freq_names.get(cs.inspection_frequency, '未知')}")

    except Exception as e:
        db.rollback()
        print(f"初始化失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
