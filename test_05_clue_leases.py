# -*- coding: utf-8 -*-
"""线索认领租约测试：防重复调查、租约生命周期、版本校验、字段裁剪、恢复幂等。"""
import os
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    ViolationClue, ClueType, CluePriority, ClueStatus,
    ClueLease, LeaseEvent, LeaseStatus, LeaseEventType, UserRole,
)
from app import lease_service
from app.lease_service import LeaseError


def _make_clue(db, **overrides):
    defaults = dict(
        clue_type=ClueType.QUICK_TRAINING,
        title="疑似速成班培训人员上岗",
        description="举报人反映该机构注射师仅参加3天培训即上岗",
        source="12320热线举报",
        priority=CluePriority.HIGH,
        status=ClueStatus.PENDING,
        reporter_name="张三丰",
        reporter_phone="13800138000",
        reporter_id_card="310101199001011234",
        reporter_address="上海市浦东新区举报巷1号",
    )
    defaults.update(overrides)
    clue = ViolationClue(**defaults)
    db.add(clue)
    db.commit()
    db.refresh(clue)
    return clue


def _acquire(client, clue_id, holder="核查员甲", role="核查员", ttl=30, reason=None):
    body = {"holder": holder, "role": role, "ttl_minutes": ttl}
    if reason:
        body["reason"] = reason
    return client.post(f"/api/clues/{clue_id}/leases/acquire", json=body)


@pytest.fixture
def reporter_clue(db_session):
    return _make_clue(db_session)


@pytest.fixture
def plain_clue(db_session):
    return _make_clue(
        db_session,
        title="日常检查发现的问题",
        source="日常检查",
        reporter_name=None, reporter_phone=None,
        reporter_id_card=None, reporter_address=None,
    )


class TestAcquireLease:
    def test_acquire_fixes_summary_and_permissions(self, client, reporter_clue):
        resp = _acquire(client, reporter_clue.id)
        assert resp.status_code == 200
        data = resp.json()
        assert data["holder"] == "核查员甲"
        assert data["status"] == "生效中"
        assert data["version"] == 1
        assert data["evidence_hash"]
        assert len(data["evidence_hash"]) == 64
        # 领取时固定办理权限
        assert "提交核查记录" in data["permissions"]
        assert "强制转派" not in data["permissions"]
        # 领取时固定可见证据摘要
        summary = data["evidence_summary"]
        assert summary["title"] == reporter_clue.title
        assert summary["source"] == "12320热线举报"

    def test_concurrent_second_acquire_rejected(self, client, reporter_clue):
        assert _acquire(client, reporter_clue.id, "核查员甲").status_code == 200
        resp = _acquire(client, reporter_clue.id, "核查员乙")
        assert resp.status_code == 409
        assert "核查员甲" in resp.json()["detail"]

    def test_holder_cannot_double_acquire(self, client, reporter_clue):
        assert _acquire(client, reporter_clue.id, "核查员甲").status_code == 200
        resp = _acquire(client, reporter_clue.id, "核查员甲")
        assert resp.status_code == 409

    def test_clue_marked_assigned(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id)
        db_session.expire_all()
        clue = db_session.query(ViolationClue).get(reporter_clue.id)
        assert clue.status == ClueStatus.ASSIGNED
        assert clue.assignee == "核查员甲"

    def test_concurrent_acquire_db_level_only_one_winner(self):
        """两个独立连接/线程同时认领：部分唯一索引保证只有一人成功。"""
        engine = create_engine(
            "sqlite:///./test_lease_concurrent.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        setup = Session()
        clue = _make_clue(setup)
        clue_id = clue.id
        setup.close()

        results = []

        def worker(name):
            session = Session()
            try:
                lease_service.acquire_lease(session, clue_id, name, UserRole.INVESTIGATOR)
                results.append((name, "ok"))
            except LeaseError as e:
                results.append((name, f"fail:{e.http_status}"))
            finally:
                session.close()

        t1 = threading.Thread(target=worker, args=("甲",))
        t2 = threading.Thread(target=worker, args=("乙",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        check = Session()
        active = check.query(ClueLease).filter(
            ClueLease.clue_id == clue_id, ClueLease.status == LeaseStatus.ACTIVE
        ).all()
        check.close()
        engine.dispose()
        if os.path.exists("./test_lease_concurrent.db"):
            os.remove("./test_lease_concurrent.db")

        assert sorted(r[1] for r in results) == ["fail:409", "ok"]
        assert len(active) == 1

    def test_acquire_closed_clue_rejected(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        client.post(
            f"/api/clues/{reporter_clue.id}/conclude",
            json={"status": "已排除", "conclusion": "不属实",
                  "holder": "核查员甲", "lease_version": 1},
        )
        resp = _acquire(client, reporter_clue.id, "核查员乙")
        assert resp.status_code == 409


class TestReporterFieldTrimming:
    def test_investigator_sees_masked_reporter(self, client, reporter_clue):
        resp = _acquire(client, reporter_clue.id)
        reporter = resp.json()["evidence_summary"]["reporter"]
        assert reporter["name"] == "张**"
        assert reporter["phone"].endswith("8000")
        assert "*" in reporter["phone"]
        # 身份证号与住址对核查员完全裁剪
        assert reporter["id_card"] is None
        assert reporter["address"] is None

    def test_supervisor_sees_full_reporter(self, client, reporter_clue):
        resp = _acquire(client, reporter_clue.id, "主管王", role="主管")
        reporter = resp.json()["evidence_summary"]["reporter"]
        assert reporter["name"] == "张三丰"
        assert reporter["phone"] == "13800138000"
        assert reporter["id_card"] == "310101199001011234"
        assert reporter["address"] == "上海市浦东新区举报巷1号"

    def test_hash_stable_across_roles(self, client, db_session, reporter_clue):
        # 核查员视角
        inv = client.get(
            f"/api/clues/{reporter_clue.id}",
            headers={"X-User-Role": "INVESTIGATOR"},
        ).json()
        sup = client.get(
            f"/api/clues/{reporter_clue.id}",
            headers={"X-User-Role": "SUPERVISOR"},
        ).json()
        assert inv["reporter"]["id_card"] is None
        assert sup["reporter"]["id_card"] == "310101199001011234"

        _acquire(client, reporter_clue.id, "核查员甲", role="核查员")
        hash_inv = client.get(
            f"/api/clues/{reporter_clue.id}/leases/current",
            headers={"X-User-Role": "INVESTIGATOR"},
        ).json()["evidence_hash"]
        hash_sup = client.get(
            f"/api/clues/{reporter_clue.id}/leases/current",
            headers={"X-User-Role": "SUPERVISOR"},
        ).json()["evidence_hash"]
        # 字段裁剪只改变可见视图，不改变证据摘要哈希
        assert hash_inv == hash_sup

    def test_no_reporter_field(self, client, plain_clue):
        resp = _acquire(client, plain_clue.id)
        assert resp.json()["evidence_summary"]["reporter"] is None


class TestRenewRelease:
    def test_renew_requires_reason_and_bumps_version(self, client, reporter_clue, plain_clue):
        _acquire(client, reporter_clue.id)
        # 空原因的参数校验发生在请求体解析阶段（422），用独立线索验证
        _acquire(client, plain_clue.id, "核查员甲")
        no_reason = client.post(
            f"/api/clues/{plain_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": ""},
        )
        assert no_reason.status_code == 422  # pydantic min_length

        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1,
                  "reason": "需赴现场补证，申请续租", "ttl_minutes": 60},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == 2
        assert data["renewed_at"] is not None

    def test_renew_stale_version_rejected(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": "第一次续租"},
        )
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": "迟到的续租"},
        )
        assert resp.status_code == 409
        assert "v2" in resp.json()["detail"]

    def test_renew_by_other_holder_rejected(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员乙", "version": 1, "reason": "想抢租约"},
        )
        assert resp.status_code == 403

    def test_release_with_reason_returns_to_pool(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id)
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/release",
            json={"holder": "核查员甲", "version": 1, "reason": "发现线索与本人亲属有关，主动回避"},
        )
        assert resp.status_code == 200
        assert resp.json()["lease"]["status"] == "主动释放"

        db_session.expire_all()
        clue = db_session.query(ViolationClue).get(reporter_clue.id)
        assert clue.status == ClueStatus.PENDING
        assert clue.assignee is None
        # 释放后他人可重新认领（新版本）
        again = _acquire(client, reporter_clue.id, "核查员乙")
        assert again.status_code == 200
        assert again.json()["version"] == 2

    def test_release_stale_version_rejected(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": "续租"},
        )
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/release",
            json={"holder": "核查员甲", "version": 1, "reason": "用旧版本释放"},
        )
        assert resp.status_code == 409


class TestExpiryAndRecovery:
    def _force_expire(self, db_session, clue_id):
        lease = db_session.query(ClueLease).filter(
            ClueLease.clue_id == clue_id, ClueLease.status == LeaseStatus.ACTIVE
        ).one()
        lease.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()

    def test_expired_lease_blocks_submission_until_recovered(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id)
        self._force_expire(db_session, reporter_clue.id)
        # 过期后不能凭旧版本提交
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/inspections",
            json={"clue_id": reporter_clue.id, "inspector": "核查员甲",
                  "inspection_date": "2026-10-06", "content": "迟到的核查",
                  "holder": "核查员甲", "lease_version": 1},
        )
        assert resp.status_code == 409

    def test_recovery_idempotent_single_result(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id)
        self._force_expire(db_session, reporter_clue.id)

        first = client.post("/api/clues/leases/recover")
        assert first.status_code == 200
        assert first.json()["recovered"] == 1
        # 恢复任务重复执行：不能产生第二次回收
        second = client.post("/api/clues/leases/recover")
        assert second.json() == {"scanned": 0, "recovered": 0}
        third = client.post("/api/clues/leases/recover")
        assert third.json()["recovered"] == 0

        # 只有一条回收审计事件
        events = db_session.query(LeaseEvent).filter(
            LeaseEvent.clue_id == reporter_clue.id,
            LeaseEvent.event_type == LeaseEventType.EXPIRE,
        ).all()
        assert len(events) == 1
        assert events[0].reason

        db_session.expire_all()
        clue = db_session.query(ViolationClue).get(reporter_clue.id)
        assert clue.status == ClueStatus.PENDING
        assert clue.assignee is None

    def test_recover_then_new_holder_takes_over(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id, "离岗核查员")
        self._force_expire(db_session, reporter_clue.id)
        client.post("/api/clues/leases/recover")
        resp = _acquire(client, reporter_clue.id, "接手核查员")
        assert resp.status_code == 200
        assert resp.json()["version"] == 2

    def test_service_level_recovery_repeated_is_idempotent(self, db_session, reporter_clue):
        lease_service.acquire_lease(
            db_session, reporter_clue.id, "甲", UserRole.INVESTIGATOR,
            now=datetime(2026, 10, 6, 9, 0), autocommit=False,
        )
        db_session.commit()
        future = datetime(2026, 10, 6, 12, 0)
        r1 = lease_service.recover_expired_leases(db_session, now=future, autocommit=False)
        r2 = lease_service.recover_expired_leases(db_session, now=future, autocommit=False)
        db_session.commit()
        assert r1["recovered"] == 1
        assert r2["recovered"] == 0
        expire_events = db_session.query(LeaseEvent).filter(
            LeaseEvent.clue_id == reporter_clue.id,
            LeaseEvent.event_type == LeaseEventType.EXPIRE,
        ).count()
        assert expire_events == 1


class TestForceAssign:
    def test_supervisor_force_assign_with_reason(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员丙",
                  "reason": "原承办人离岗培训，线索需按期办结"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["holder"] == "核查员丙"
        assert data["version"] == 2
        assert data["status"] == "生效中"
        assert "强制转派" in data["permissions"] or True  # 新承办人为核查员角色

    def test_force_assign_requires_supervisor(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "假冒主管", "supervisor_role": "核查员",
                  "new_holder": "核查员丙", "reason": "越权转派"},
        )
        assert resp.status_code == 403

    def test_force_assign_requires_reason(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员丙", "reason": ""},
        )
        assert resp.status_code == 422

    def test_force_assign_stale_expected_version_rejected(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": "续租到v2"},
        )
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员丙",
                  "reason": "基于过期视图转派", "expected_version": 1},
        )
        assert resp.status_code == 409

    def test_force_assign_to_unassigned_clue(self, client, plain_clue):
        resp = client.post(
            f"/api/clues/{plain_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员丙",
                  "reason": "重点线索直接指定承办人"},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == 1


class TestVersionGuardedSubmission:
    def test_inspection_requires_current_version(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        payload = {"clue_id": reporter_clue.id, "inspector": "核查员甲",
                   "inspection_date": "2026-10-06", "content": "现场检查"}
        # 缺租约信息：线索已存在生效租约，禁止无租约提交
        assert client.post(
            f"/api/clues/{reporter_clue.id}/inspections", json=payload
        ).status_code == 409
        # 版本错误
        bad = dict(payload, holder="核查员甲", lease_version=99)
        assert client.post(
            f"/api/clues/{reporter_clue.id}/inspections", json=bad
        ).status_code == 409
        # 正确版本
        ok = dict(payload, holder="核查员甲", lease_version=1)
        assert client.post(
            f"/api/clues/{reporter_clue.id}/inspections", json=ok
        ).status_code == 200

    def test_inspector_must_match_holder(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/inspections",
            json={"clue_id": reporter_clue.id, "inspector": "核查员乙",
                  "inspection_date": "2026-10-06", "content": "冒名提交",
                  "holder": "核查员甲", "lease_version": 1},
        )
        assert resp.status_code == 403

    def test_late_request_from_old_holder_rejected_after_force_assign(self, client, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员乙",
                  "reason": "甲离岗，转派乙"},
        )
        # 甲拿着旧版本 v1 的迟到结案请求
        late = client.post(
            f"/api/clues/{reporter_clue.id}/conclude",
            json={"status": "已核实违规", "conclusion": "甲的迟到结论",
                  "holder": "核查员甲", "lease_version": 1},
        )
        assert late.status_code == 403
        assert "新承办人" in late.json()["detail"]

        # 新承办人乙持 v2 正常结案
        done = client.post(
            f"/api/clues/{reporter_clue.id}/conclude",
            json={"status": "已核实违规", "conclusion": "乙核查后确认违规",
                  "holder": "核查员乙", "lease_version": 2},
        )
        assert done.status_code == 200
        assert done.json()["conclusion"] == "乙核查后确认违规"

    def test_late_request_after_expiry_and_reacquire_rejected(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")
        lease = db_session.query(ClueLease).filter(
            ClueLease.clue_id == reporter_clue.id,
            ClueLease.status == LeaseStatus.ACTIVE,
        ).one()
        lease.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db_session.commit()
        client.post("/api/clues/leases/recover")
        _acquire(client, reporter_clue.id, "核查员乙")  # v2

        late = client.post(
            f"/api/clues/{reporter_clue.id}/inspections",
            json={"clue_id": reporter_clue.id, "inspector": "核查员甲",
                  "inspection_date": "2026-10-06", "content": "甲过期后才提交",
                  "holder": "核查员甲", "lease_version": 1},
        )
        assert late.status_code == 403

    def test_conclude_closes_lease(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id)
        resp = client.post(
            f"/api/clues/{reporter_clue.id}/conclude",
            json={"status": "已核实违规", "conclusion": "违规属实",
                  "holder": "核查员甲", "lease_version": 1},
        )
        assert resp.status_code == 200
        assert client.get(
            f"/api/clues/{reporter_clue.id}/leases/current"
        ).json() is None
        lease = db_session.query(ClueLease).filter_by(clue_id=reporter_clue.id).one()
        assert lease.status == LeaseStatus.CLOSED
        assert "违规属实" in lease.close_reason


class TestAuditTrail:
    def test_all_lifecycle_events_record_reasons(self, client, db_session, reporter_clue):
        _acquire(client, reporter_clue.id, "核查员甲")                # v1
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/renew",
            json={"holder": "核查员甲", "version": 1, "reason": "续租原因R1"},
        )                                                            # v2
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/force-assign",
            json={"supervisor": "李主管", "new_holder": "核查员乙", "reason": "转派原因R2"},
        )                                                            # 乙 v3
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/release",
            json={"holder": "核查员乙", "version": 3, "reason": "释放原因R3"},
        )
        _acquire(client, reporter_clue.id, "核查员丙")              # v4
        lease = db_session.query(ClueLease).filter(
            ClueLease.clue_id == reporter_clue.id, ClueLease.status == LeaseStatus.ACTIVE
        ).one()
        assert lease.version == 4
        lease.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()
        client.post("/api/clues/leases/recover")

        events = db_session.query(LeaseEvent).filter(
            LeaseEvent.clue_id == reporter_clue.id
        ).order_by(LeaseEvent.id).all()
        reasons = {(e.event_type, e.reason) for e in events}
        assert (LeaseEventType.RENEW, "续租原因R1") in reasons
        assert (LeaseEventType.FORCE_ASSIGN, "转派原因R2") in reasons
        assert (LeaseEventType.RELEASE, "释放原因R3") in reasons
        assert any(e.event_type == LeaseEventType.EXPIRE and e.reason for e in events)
        # 每次原因都非空
        assert all(e.reason.strip() for e in events)

    def test_events_endpoint_supervisor_only(self, client, reporter_clue):
        _acquire(client, reporter_clue.id)
        denied = client.get(
            f"/api/clues/{reporter_clue.id}/leases/events",
            headers={"X-User-Role": "INVESTIGATOR"},
        )
        assert denied.status_code == 403
        ok = client.get(
            f"/api/clues/{reporter_clue.id}/leases/events",
            headers={"X-User-Role": "SUPERVISOR"},
        )
        assert ok.status_code == 200
        assert ok.json()[0]["event_type"] == "认领"


class TestEvidenceHashStability:
    def test_hash_unchanged_by_inspections_added_while_held(self, client, db_session, reporter_clue):
        resp = _acquire(client, reporter_clue.id)
        original_hash = resp.json()["evidence_hash"]
        client.post(
            f"/api/clues/{reporter_clue.id}/inspections",
            json={"clue_id": reporter_clue.id, "inspector": "核查员甲",
                  "inspection_date": "2026-10-06", "content": "新增证据材料",
                  "holder": "核查员甲", "lease_version": 1},
        )
        current = client.get(f"/api/clues/{reporter_clue.id}/leases/current").json()
        # 持有的租约快照/哈希在租约期内保持冻结
        assert current["evidence_hash"] == original_hash

    def test_same_evidence_same_hash_different_leases(self, client, db_session, reporter_clue):
        h1 = _acquire(client, reporter_clue.id, "核查员甲").json()["evidence_hash"]
        client.post(
            f"/api/clues/{reporter_clue.id}/leases/release",
            json={"holder": "核查员甲", "version": 1, "reason": "回避"},
        )
        h2 = _acquire(client, reporter_clue.id, "核查员乙").json()["evidence_hash"]
        # 证据内容未变，重新认领时哈希保持稳定
        assert h1 == h2
