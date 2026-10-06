"""线索认领租约专项测试：独占认领、证据/权限快照、续租/释放/回收/转派、
版本闸门防迟到覆盖、举报人字段按角色裁剪、恢复任务幂等。"""
import os
import tempfile
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    ViolationClue, ClueType, CluePriority, ClueStatus,
    ClueLease, ClueLeaseEvent, LeaseStatus, LeaseEventType, UserRole,
)
from app import lease_service


def make_clue(db, **overrides):
    defaults = dict(
        clue_type=ClueType.UNLICENSED_STAFF,
        title="租约测试线索",
        description="举报人王某反映某机构无证人员上岗操作光电设备",
        source="12320卫生热线举报",
        priority=CluePriority.HIGH,
        status=ClueStatus.PENDING,
        informant_name="王保护",
        informant_phone="13800001234",
        informant_id_card="310101198801011234",
        informant_contact_detail="现住上海市测试路1号，要求保密身份",
    )
    defaults.update(overrides)
    clue = ViolationClue(**defaults)
    db.add(clue)
    db.flush()
    return clue


class TestClaimExclusive:
    def test_claim_creates_lease_with_snapshot(self, client, db_session):
        clue = make_clue(db_session)
        resp = client.post(f"/api/clues/{clue.id}/leases/claim", json={
            "holder": "核查员甲", "holder_role": "核查员",
            "ttl_minutes": 60, "reason": "热线集中转入，开始核查",
        })
        assert resp.status_code == 200, resp.text
        lease = resp.json()
        assert lease["holder"] == "核查员甲"
        assert lease["status"] == "持有中"
        assert lease["version"] == 1
        assert "无证人员上岗" in lease["evidence_summary"]
        assert len(lease["evidence_hash"]) == 64
        assert "submit_inspection" in lease["permissions"]
        assert "force_reassign" not in lease["permissions"]
        # 线索进入核查中并挂到认领人名下
        db_session.expire_all()
        refreshed = db_session.get(ViolationClue, clue.id)
        assert refreshed.status == ClueStatus.ASSIGNED
        assert refreshed.assignee == "核查员甲"

    def test_concurrent_second_claim_rejected(self, client, db_session):
        clue = make_clue(db_session)
        first = client.post(f"/api/clues/{clue.id}/leases/claim",
                            json={"holder": "核查员甲"})
        assert first.status_code == 200
        second = client.post(f"/api/clues/{clue.id}/leases/claim",
                             json={"holder": "核查员乙"})
        assert second.status_code == 409
        assert "核查员甲" in second.json()["detail"]
        # 失败后只有一条 ACTIVE 租约，且事务回滚未污染已有数据
        active = db_session.query(ClueLease).filter_by(
            clue_id=clue.id, status=LeaseStatus.ACTIVE).all()
        assert len(active) == 1
        assert active[0].holder == "核查员甲"
        assert db_session.get(ViolationClue, clue.id).title == "租约测试线索"

    def test_claim_closed_clue_rejected(self, client, db_session):
        clue = make_clue(db_session, status=ClueStatus.VERIFIED)
        resp = client.post(f"/api/clues/{clue.id}/leases/claim",
                           json={"holder": "核查员甲"})
        assert resp.status_code == 400

    def test_permissions_snapshot_differs_by_role(self, client, db_session):
        clue = make_clue(db_session)
        resp = client.post(f"/api/clues/{clue.id}/leases/claim", json={
            "holder": "主管丁", "holder_role": "主管",
        })
        perms = resp.json()["permissions"]
        assert "force_reassign" in perms and "view_informant" in perms


class TestEvidenceHashStable:
    def test_hash_independent_of_viewer_role(self, client, db_session):
        clue = make_clue(db_session)
        h_inspector = client.post(f"/api/clues/{clue.id}/leases/claim", json={
            "holder": "核查员甲", "holder_role": "核查员",
        }).json()["evidence_hash"]
        # 释放后由主管重新认领
        lid = client.get(f"/api/clues/{clue.id}/leases/active").json()["id"]
        client.post(f"/api/clues/{clue.id}/leases/release", json={
            "holder": "核查员甲", "lease_id": lid, "version": 1,
            "reason": "回避，改由主管办理",
        })
        h_supervisor = client.post(f"/api/clues/{clue.id}/leases/claim", json={
            "holder": "主管丁", "holder_role": "主管",
        }).json()["evidence_hash"]
        assert h_inspector == h_supervisor

    def test_hash_changes_when_evidence_changes(self, client, db_session):
        clue = make_clue(db_session)
        h1 = client.post(f"/api/clues/{clue.id}/leases/claim",
                         json={"holder": "核查员甲"}).json()["evidence_hash"]
        lid = client.get(f"/api/clues/{clue.id}/leases/active").json()["id"]
        client.post(f"/api/clues/{clue.id}/leases/release", json={
            "holder": "核查员甲", "lease_id": lid, "version": 1,
            "reason": "补充新证据前先释放",
        })
        clue.informant_phone = "13900009999"
        db_session.flush()
        h2 = client.post(f"/api/clues/{clue.id}/leases/claim",
                         json={"holder": "核查员乙"}).json()["evidence_hash"]
        assert h1 != h2


class TestInformantFieldMasking:
    def test_inspector_sees_masked_informant(self, client, db_session):
        clue = make_clue(db_session)
        resp = client.get(f"/api/clues/{clue.id}",
                          headers={"X-User-Role": "INSPECTOR"})
        informant = resp.json()["informant"]
        assert informant["masked"] is True
        assert informant["name"].startswith("王") and "*" in informant["name"]
        assert informant["phone"].endswith("1234") and informant["phone"].startswith("*")
        assert informant["id_card"].startswith("310") and informant["id_card"].endswith("234")
        assert informant["contact_detail"] is None
        # 列表接口不携带举报人信息
        listing = client.get("/api/clues/").json()
        target = next(c for c in listing if c["id"] == clue.id)
        assert "informant" not in target

    def test_supervisor_sees_plaintext_informant(self, client, db_session):
        clue = make_clue(db_session)
        resp = client.get(f"/api/clues/{clue.id}",
                          headers={"X-User-Role": "SUPERVISOR"})
        informant = resp.json()["informant"]
        assert informant["masked"] is False
        assert informant["name"] == "王保护"
        assert informant["phone"] == "13800001234"
        assert "测试路1号" in informant["contact_detail"]


class TestRenewRelease:
    def test_renew_requires_reason_and_bumps_version(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲", "ttl_minutes": 30}).json()
        no_reason = client.post(f"/api/clues/{clue.id}/leases/renew", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "reason": "   ",
        })
        assert no_reason.status_code == 400

        before = datetime.fromisoformat(claimed["expires_at"])
        renewed = client.post(f"/api/clues/{clue.id}/leases/renew", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "ttl_minutes": 120, "reason": "需赴外地调取病历，申请续租",
        })
        assert renewed.status_code == 200
        body = renewed.json()
        assert body["version"] == 2
        assert datetime.fromisoformat(body["expires_at"]) > before

    def test_renew_with_stale_version_rejected(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲"}).json()
        client.post(f"/api/clues/{clue.id}/leases/renew", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "reason": "第一次续租",
        })
        stale = client.post(f"/api/clues/{clue.id}/leases/renew", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "reason": "持旧版本迟到续租",
        })
        assert stale.status_code == 409
        assert "版本" in stale.json()["detail"]

    def test_release_returns_clue_to_pool_and_logs_reason(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲"}).json()
        resp = client.post(f"/api/clues/{clue.id}/leases/release", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "reason": "核查员突发疾病离岗",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "主动释放"
        db_session.expire_all()
        assert db_session.get(ViolationClue, clue.id).status == ClueStatus.PENDING
        # 他人可立即重新认领
        second = client.post(f"/api/clues/{clue.id}/leases/claim",
                             json={"holder": "核查员乙"})
        assert second.status_code == 200
        # 事件流含认领与带原因的释放
        events = client.get(f"/api/clues/{clue.id}/events").json()
        reasons = " ".join(e["reason"] for e in events)
        assert "突发疾病离岗" in reasons

    def test_release_by_non_holder_rejected(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲"}).json()
        resp = client.post(f"/api/clues/{clue.id}/leases/release", json={
            "holder": "核查员乙", "lease_id": claimed["id"], "version": 1,
            "reason": "越权释放",
        })
        assert resp.status_code == 409


class TestTimeoutRecovery:
    def _expire(self, db, clue_id):
        lease = lease_service.get_active_lease(db, clue_id)
        lease.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.flush()
        return lease

    def test_recovery_recycles_once_and_is_idempotent(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        self._expire(db_session, clue.id)

        first = client.post("/api/clues/leases/recover-expired",
                            json={}, headers={"X-User-Role": "SUPERVISOR"})
        assert first.status_code == 200, first.text
        assert first.json()["expired_count"] == 1

        # 重复执行（模拟服务重启后恢复任务再跑一遍）
        second = client.post("/api/clues/leases/recover-expired",
                             json={}, headers={"X-User-Role": "SUPERVISOR"})
        assert second.json()["expired_count"] == 0

        expire_events = db_session.query(ClueLeaseEvent).filter_by(
            clue_id=clue.id, event_type=LeaseEventType.EXPIRE).count()
        assert expire_events == 1
        assert db_session.get(ViolationClue, clue.id).status == ClueStatus.PENDING

    def test_recovery_requires_supervisor(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        self._expire(db_session, clue.id)
        resp = client.post("/api/clues/leases/recover-expired",
                           json={}, headers={"X-User-Role": "INSPECTOR"})
        assert resp.status_code == 403

    def test_recovery_with_auto_reassign_single_result(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        self._expire(db_session, clue.id)

        first = client.post("/api/clues/leases/recover-expired",
                            json={"auto_reassign_to": "值班主管",
                                  "reason": "原核查员离岗超时，转派值班"},
                            headers={"X-User-Role": "SUPERVISOR"})
        body = first.json()
        assert body["expired_count"] == 1
        assert body["reassigned_count"] == 1
        # 再跑一遍：既不重复回收也不重复转派
        second = client.post("/api/clues/leases/recover-expired",
                             json={"auto_reassign_to": "值班主管"},
                             headers={"X-User-Role": "SUPERVISOR"}).json()
        assert second["expired_count"] == 0
        assert second["reassigned_count"] == 0
        active = lease_service.get_active_lease(db_session, clue.id)
        assert active.holder == "值班主管"
        reassign_claims = db_session.query(ClueLeaseEvent).filter(
            ClueLeaseEvent.clue_id == clue.id,
            ClueLeaseEvent.event_type == LeaseEventType.CLAIM,
            ClueLeaseEvent.reason.like("%值班%"),
        ).count()
        assert reassign_claims == 1

    def test_expired_holder_cannot_renew_or_submit(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲"}).json()
        self._expire(db_session, clue.id)
        # 触发一次惰性/批量回收
        client.post("/api/clues/leases/recover-expired",
                    json={}, headers={"X-User-Role": "SUPERVISOR"})
        renew = client.post(f"/api/clues/{clue.id}/leases/renew", json={
            "holder": "核查员甲", "lease_id": claimed["id"], "version": 1,
            "reason": "过期后续租",
        })
        assert renew.status_code == 409


class TestForceReassign:
    def test_inspector_cannot_force_reassign(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        resp = client.post(f"/api/clues/{clue.id}/leases/reassign", json={
            "supervisor": "核查员乙", "to_holder": "核查员丙",
            "reason": "试图抢单",
        }, headers={"X-User-Role": "INSPECTOR"})
        assert resp.status_code == 403

    def test_reassign_requires_reason(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        resp = client.post(f"/api/clues/{clue.id}/leases/reassign", json={
            "supervisor": "主管丁", "to_holder": "核查员丙", "reason": "   ",
        }, headers={"X-User-Role": "SUPERVISOR"})
        assert resp.status_code == 400

    def test_reassign_terminates_and_recreates_lease_with_audit(self, client, db_session):
        clue = make_clue(db_session)
        old = client.post(f"/api/clues/{clue.id}/leases/claim",
                          json={"holder": "核查员甲"}).json()
        resp = client.post(f"/api/clues/{clue.id}/leases/reassign", json={
            "supervisor": "主管丁", "to_holder": "核查员丙",
            "reason": "核查员甲调离本辖区，线索长期未推进",
        }, headers={"X-User-Role": "SUPERVISOR"})
        assert resp.status_code == 200, resp.text
        new = resp.json()
        assert new["id"] != old["id"]
        assert new["holder"] == "核查员丙"
        assert new["version"] == 1

        old_lease = db_session.get(ClueLease, old["id"])
        assert old_lease.status == LeaseStatus.REASSIGNED
        events = client.get(f"/api/clues/{clue.id}/events").json()
        reassign_event = next(e for e in events if e["event_type"] == "强制转派")
        assert reassign_event["from_holder"] == "核查员甲"
        assert reassign_event["to_holder"] == "核查员丙"
        assert reassign_event["actor"] == "主管丁"
        assert "调离本辖区" in reassign_event["reason"]

    def test_reassign_is_idempotent_for_same_target(self, client, db_session):
        clue = make_clue(db_session)
        client.post(f"/api/clues/{clue.id}/leases/claim", json={"holder": "核查员甲"})
        payload = {"supervisor": "主管丁", "to_holder": "核查员丙",
                   "reason": "统一调岗"}
        r1 = client.post(f"/api/clues/{clue.id}/leases/reassign", json=payload,
                         headers={"X-User-Role": "SUPERVISOR"})
        r2 = client.post(f"/api/clues/{clue.id}/leases/reassign", json=payload,
                         headers={"X-User-Role": "SUPERVISOR"})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]
        count = db_session.query(ClueLeaseEvent).filter_by(
            clue_id=clue.id, event_type=LeaseEventType.REASSIGN).count()
        assert count == 1


class TestStaleRequestCannotOverwrite:
    def test_old_holder_late_inspection_rejected(self, client, db_session):
        clue = make_clue(db_session)
        old = client.post(f"/api/clues/{clue.id}/leases/claim",
                          json={"holder": "核查员甲"}).json()
        # 主管将线索转派给核查员丙
        client.post(f"/api/clues/{clue.id}/leases/reassign", json={
            "supervisor": "主管丁", "to_holder": "核查员丙",
            "reason": "原承办人离岗",
        }, headers={"X-User-Role": "SUPERVISOR"})

        # 原承办人拿着旧租约 id/version 的迟到请求
        late = client.post(f"/api/clues/{clue.id}/inspections", json={
            "clue_id": clue.id, "inspector": "核查员甲",
            "inspection_date": "2026-10-06",
            "content": "迟到的核查记录",
            "lease_id": old["id"], "lease_version": 1,
        })
        assert late.status_code == 409

        # 新承办人持当前租约可正常提交
        new = client.get(f"/api/clues/{clue.id}/leases/active").json()
        ok = client.post(f"/api/clues/{clue.id}/inspections", json={
            "clue_id": clue.id, "inspector": "核查员丙",
            "inspection_date": "2026-10-06",
            "content": "新承办人的核查记录",
            "lease_id": new["id"], "lease_version": 1,
        })
        assert ok.status_code == 200
        records = client.get(f"/api/clues/{clue.id}/inspections").json()
        assert len(records) == 1
        assert records[0]["inspector"] == "核查员丙"

    def test_conclude_with_stale_version_rejected_and_no_overwrite(self, client, db_session):
        clue = make_clue(db_session)
        old = client.post(f"/api/clues/{clue.id}/leases/claim",
                          json={"holder": "核查员甲"}).json()
        client.post(f"/api/clues/{clue.id}/leases/reassign", json={
            "supervisor": "主管丁", "to_holder": "核查员丙",
            "reason": "原承办人离岗",
        }, headers={"X-User-Role": "SUPERVISOR"})

        late = client.post(f"/api/clues/{clue.id}/conclude", json={
            "status": "已核实违规", "conclusion": "原承办人迟到结论",
            "holder": "核查员甲", "lease_id": old["id"], "lease_version": 1,
        })
        assert late.status_code == 409
        assert db_session.get(ViolationClue, clue.id).status == ClueStatus.ASSIGNED
        assert db_session.get(ViolationClue, clue.id).conclusion is None

        new = client.get(f"/api/clues/{clue.id}/leases/active").json()
        ok = client.post(f"/api/clues/{clue.id}/conclude", json={
            "status": "已排除", "conclusion": "新承办人核实后结案",
            "holder": "核查员丙", "lease_id": new["id"], "lease_version": 1,
        })
        assert ok.status_code == 200
        db_session.expire_all()
        final = db_session.get(ViolationClue, clue.id)
        assert final.status == ClueStatus.DISMISSED
        assert final.conclusion == "新承办人核实后结案"
        # 结案后租约终结，无法再认领
        again = client.post(f"/api/clues/{clue.id}/leases/claim",
                            json={"holder": "核查员戊"})
        assert again.status_code == 400

    def test_expired_holder_late_conclude_rejected(self, client, db_session):
        clue = make_clue(db_session)
        claimed = client.post(f"/api/clues/{clue.id}/leases/claim",
                              json={"holder": "核查员甲", "ttl_minutes": 1}).json()
        lease = lease_service.get_active_lease(db_session, clue.id)
        lease.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db_session.flush()

        # 兼容模式（不带版本）下，过期租约持有人的迟到结案同样被拒
        resp = client.post(f"/api/clues/{clue.id}/conclude", json={
            "status": "已核实违规", "conclusion": "过期迟到结论",
        })
        assert resp.status_code == 409
        assert db_session.get(ViolationClue, clue.id).status == ClueStatus.PENDING


class TestRealConcurrentClaim:
    """使用独立文件库与多线程，验证数据库层互斥：N 人并发抢同一线索仅一人成功。"""

    def test_only_one_winner_under_threads(self):
        from sqlalchemy import event as sa_event

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @sa_event.listens_for(engine, "connect")
        def _pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        Base.metadata.create_all(engine)
        SessionFactory = sessionmaker(bind=engine)

        setup = SessionFactory()
        clue = ViolationClue(
            clue_type=ClueType.FALSE_ADVERTISEMENT,
            title="并发抢单线索", description="多人同时打开同一条记录",
            source="热线", priority=CluePriority.HIGH, status=ClueStatus.PENDING,
        )
        setup.add(clue)
        setup.commit()
        clue_id = clue.id
        setup.close()

        winners, losers, errors = [], [], []
        barrier = threading.Barrier(8)

        def worker(idx):
            session = SessionFactory()
            try:
                barrier.wait()
                c = session.get(ViolationClue, clue_id)
                lease = lease_service.claim_lease(
                    session, c, holder=f"核查员{idx}",
                    reason="热线集中转入并发认领",
                )
                winners.append((idx, lease.id))
            except lease_service.LeaseError:
                losers.append(idx)
            except Exception as exc:  # 不应出现数据库锁死等错误
                errors.append(repr(exc))
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check = SessionFactory()
        active = check.query(ClueLease).filter_by(
            clue_id=clue_id, status=LeaseStatus.ACTIVE
        ).all()
        claim_events = check.query(ClueLeaseEvent).filter_by(
            clue_id=clue_id, event_type=LeaseEventType.CLAIM
        ).count()
        check.close()
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)

        assert errors == [], errors
        assert len(winners) == 1, winners
        assert len(losers) == 7
        assert len(active) == 1
        # 唯一索引 + 事务保证只产生一条认领导约与一条认领事件
        assert claim_events == 1
