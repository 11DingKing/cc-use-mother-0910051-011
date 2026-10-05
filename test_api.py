import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    print("✓ 健康检查接口正常")


def test_institutions():
    response = client.get("/api/institutions/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    print(f"✓ 机构列表接口正常，共 {len(data)} 家机构")

    response = client.get(f"/api/institutions/{data[0]['id']}")
    assert response.status_code == 200
    print("✓ 机构详情接口正常")

    response = client.get(f"/api/institutions/{data[0]['id']}/licenses")
    assert response.status_code == 200
    print(f"✓ 机构许可证接口正常，共 {len(response.json())} 条")

    response = client.get(f"/api/institutions/{data[0]['id']}/authorized-procedures")
    assert response.status_code == 200
    print(f"✓ 机构授权项目接口正常，共 {len(response.json())} 项")


def test_practitioners():
    response = client.get("/api/practitioners/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 8
    print(f"✓ 从业人员列表接口正常，共 {len(data)} 人")

    response = client.get(f"/api/practitioners/{data[0]['id']}")
    assert response.status_code == 200
    print("✓ 从业人员详情接口正常")

    response = client.get(f"/api/practitioners/{data[0]['id']}/qualifications")
    assert response.status_code == 200
    print(f"✓ 人员资质接口正常，共 {len(response.json())} 条")


def test_procedures():
    response = client.get("/api/procedures/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 11
    print(f"✓ 医美项目列表接口正常，共 {len(data)} 项")

    response = client.get("/api/procedures/categories/list")
    assert response.status_code == 200
    print(f"✓ 项目分类枚举接口正常")


def test_compliance():
    insts = client.get("/api/institutions/").json()

    response = client.get(f"/api/compliance/institution/{insts[0]['id']}")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 机构合规核验接口正常: {data['institution_name']}, 有效许可: {data['has_valid_license']}, 超范围: {data['over_range_count']}")

    pracs = client.get("/api/practitioners/").json()
    response = client.get(f"/api/compliance/practitioner/{pracs[0]['id']}")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 人员合规核验接口正常: {data['name']}, 无证: {data['is_unlicensed']}, 超范围项目: {len(data['over_range_procedures'])}")

    response = client.get("/api/compliance/actual-procedures?only_over_range=true")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 超范围项目记录接口正常，共 {len(data)} 条超范围记录")

    for rec in data:
        print(f"    - 超范围: {rec.get('over_range_detail', 'N/A')}")


def test_clues():
    response = client.get("/api/clues/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 7
    print(f"✓ 违规线索列表接口正常，共 {len(data)} 条线索")

    clue_id = data[0]["id"]
    response = client.get(f"/api/clues/{clue_id}")
    assert response.status_code == 200
    print("✓ 线索详情接口正常")

    response = client.get(f"/api/clues/{clue_id}/inspections")
    assert response.status_code == 200
    print(f"✓ 核查记录接口正常，共 {len(response.json())} 条")

    new_clue = {
        "clue_type": "疑似速成班培训",
        "title": "测试新增线索",
        "description": "这是一条测试线索",
        "priority": "中"
    }
    response = client.post("/api/clues/", json=new_clue)
    assert response.status_code == 200
    new_id = response.json()["id"]
    print(f"✓ 新增线索接口正常，ID: {new_id}")

    response = client.post(f"/api/clues/{new_id}/assign", json={"assignee": "测试稽查员"})
    assert response.status_code == 200
    assert response.json()["status"] == "核查中"
    print("✓ 线索分派接口正常")

    response = client.post(
        f"/api/clues/{new_id}/conclude",
        json={"status": "已排除", "conclusion": "测试结论，不属实"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "已排除"
    print("✓ 线索结论接口正常")


def test_stats():
    response = client.get("/api/stats/summary")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 总体统计接口正常: 机构 {data['institutions']['total']}, 人员 {data['practitioners']['total']}, 线索 {data['clues']['total']}")
    print(f"    无证执业占比: {data['practitioners']['unlicensed_ratio']:.1%}")
    print(f"    超范围执业占比: {data['procedures']['over_range_ratio']:.1%}")
    print(f"    已核实违规: {data['clues']['verified_violations']} 条")
    if data.get('compliance'):
        comp = data['compliance']
        print(f"    合规评分: 已评分 {comp['total_scored']} 家, 平均分 {comp['avg_score']}, 高风险 {comp['high_risk_count']} 家")

    response = client.get("/api/stats/by-institution")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按机构统计接口正常（含合规等级），共 {len(data)} 条")
    for d in data[:3]:
        grade_info = f", 合规等级: {d.get('compliance_grade', 'N/A')}" if d.get('compliance_grade') else ""
        print(f"    - {d['institution_name']}: 风险分 {d['risk_score']}, 违规 {d['verified_violations']}{grade_info}")

    response = client.get("/api/stats/by-institution?grade=D")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按合规等级筛选机构正常，不合格机构共 {len(data)} 家")

    response = client.get("/api/stats/by-category")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按项目类别统计接口正常，共 {len(data)} 类")
    for d in data:
        if d['total_actual'] > 0:
            print(f"    - {d['category']}: 实际 {d['total_actual']}, 超范围 {d['over_range_count']}, 占比 {d['over_range_ratio']:.1%}")

    response = client.get("/api/stats/by-category-with-grade")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按项目类别+合规等级统计接口正常，共 {len(data)} 类")

    response = client.get("/api/stats/by-compliance-grade")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按合规等级统计接口正常，共 {len(data)} 个等级")
    for d in data:
        if d['institution_count'] > 0:
            print(f"    - {d['grade']}: {d['institution_count']} 家, 平均分 {d['avg_score']}, 违规 {d['total_verified_violations']} 条")

    response = client.get("/api/stats/problem-institutions")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 问题机构列表接口正常，共 {len(data)} 家问题机构")
    for d in data:
        print(f"    - {d['institution_name']}: {d['risk_level']}, 核实违规 {d['verified_violations']} 条, 超范围 {d['over_range_count']} 项")


def test_compliance_score():
    insts = client.get("/api/institutions/").json()
    first_inst_id = insts[0]['id']

    response = client.post(f"/api/compliance-score/calculate/{first_inst_id}")
    assert response.status_code == 200
    data = response.json()
    inst_name = data.get('institution', {}).get('name', '未知')
    print(f"✓ 单机构评分计算接口正常: {inst_name}")
    print(f"    总分: {data['total_score']}, 等级: {data['grade']}, 检查频率: {data['inspection_frequency']}")
    if data.get('deduction_list'):
        for d in data['deduction_list']:
            print(f"    扣分项: {d['item']} -{d['deduction']}分 - {d['reason']}")

    response = client.get(f"/api/compliance-score/institution/{first_inst_id}/latest")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 机构最新评分查询接口正常: {data['total_score']}分 ({data['grade']})")

    response = client.get("/api/compliance-score/list")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 评分列表接口正常，共 {len(data)} 条记录")

    response = client.get("/api/compliance-score/list?grade=D&only_latest=true")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按等级筛选评分正常，不合格机构共 {len(data)} 家")

    response = client.get("/api/compliance-score/grade-distribution")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 合规等级分布接口正常")
    for d in data:
        if d['count'] > 0:
            print(f"    - {d['grade_name']}({d['grade']}): {d['count']}家 ({d['percentage']}%)")

    response = client.post("/api/compliance-score/batch-calculate?generate_plans=true")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 批量评分接口正常: 共 {data['total_institutions']} 家, 成功 {data['scored_count']} 家")


def test_supervision_plans():
    response = client.get("/api/compliance-score/plans")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 监管计划列表接口正常，共 {len(data)} 个计划")
    if data:
        for plan in data[:3]:
            print(f"    - {plan['plan_title']}: {plan['planned_date']}, 优先级: {plan['priority']}, 状态: {plan['status']}")

    plan_id = data[0]['id'] if data else None
    if plan_id:
        response = client.get(f"/api/compliance-score/plans/{plan_id}")
        assert response.status_code == 200
        print(f"✓ 监管计划详情接口正常")

        response = client.put(
            f"/api/compliance-score/plans/{plan_id}",
            json={"status": "进行中", "inspector": "测试稽查员"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "进行中"
        print(f"✓ 监管计划更新接口正常")

    response = client.get("/api/compliance-score/plans?status=待执行&priority=高")
    assert response.status_code == 200
    data = response.json()
    print(f"✓ 按状态和优先级筛选计划正常，共 {len(data)} 个高风险待执行计划")

    scores = client.get("/api/compliance-score/list?grade=D&only_latest=true").json()
    if scores:
        score_id = scores[0]['id']
        response = client.post(
            f"/api/compliance-score/plans/generate/{score_id}?plan_count=2"
        )
        assert response.status_code == 200
        data = response.json()
        print(f"✓ 为评分记录生成计划正常，生成 {data['plans_created']} 个计划")


def run_all_tests():
    print("=" * 60)
    print("医美合规核验系统 - API功能测试")
    print("=" * 60 + "\n")

    tests = [
        test_health,
        test_institutions,
        test_practitioners,
        test_procedures,
        test_compliance,
        test_clues,
        test_stats,
        test_compliance_score,
        test_supervision_plans,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 失败: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"测试完成: 通过 {passed} 项，失败 {failed} 项")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
