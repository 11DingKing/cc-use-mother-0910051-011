# 医疗美容执业与项目合规服务

本项目是使用 Python、FastAPI 与 SQLite 实现的服务端应用，覆盖机构、人员资质、项目分级、执业范围、合规线索和监管处置。它可在单个 Linux 应用容器内完成安装、测试、编译和接口验收，不依赖浏览器、外部数据库、缓存、消息队列或额外运行服务。

## 安装

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

## 测试

```bash
python3 seed_data.py && python3 -m pytest -q
```

## 编译

```bash
python3 -m compileall -q .
```

## 接口验收

```bash
python3 -c "from app.main import app; assert len(app.routes) > 5; print(len(app.routes))"
```

## 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 线索认领租约

热线集中转入的线索通过“有期限的认领租约”防止重复调查与线索挂起。租约领取时即
**固定可见证据摘要（含 SHA-256 哈希）与办理权限**，并带单调递增的版本号：

| 操作 | 接口 | 说明 |
| --- | --- | --- |
| 认领 | `POST /api/clues/{id}/leases/acquire` | 生效租约唯一，他人不可重复认领；返回证据摘要与权限 |
| 续租 | `POST /api/clues/{id}/leases/renew` | 必须携带当前版本号与续租原因，版本号递增 |
| 主动释放 | `POST /api/clues/{id}/leases/release` | 必须携带版本号与原因，线索回到待分派池 |
| 主管强制转派 | `POST /api/clues/{id}/leases/force-assign` | 仅主管，须填原因；旧租约终止、生成新版本租约 |
| 超时回收 | `POST /api/clues/leases/recover` | 条件更新，重复/并发执行只产生一次回收结果 |
| 当前租约 | `GET /api/clues/{id}/leases/current` | |
| 租约审计 | `GET /api/clues/{id}/leases/events` | 仅主管；续租/释放/回收/转派均留原因 |

- 提交核查记录 `POST /api/clues/{id}/inspections` 与结案 `POST /api/clues/{id}/conclude`
  必须携带 `holder` 与 `lease_version`；过期持有者的迟到请求（版本或持有人不匹配）会被
  拒绝，不能覆盖新承办人的工作。
- 证据摘要哈希只由证据内容决定，与观看角色无关，因而跨角色保持稳定；租约期内快照冻结。
- 举报人姓名、联系方式、身份证号、住址等敏感字段按角色裁剪（`X-User-Role` 请求头，
  核查员见脱敏视图，主管/管理员见完整信息），裁剪不影响哈希。
- 服务启动时自动执行一次恢复扫描，随后由后台守护任务周期性回收超时租约
  （`LEASE_REAPER_INTERVAL_SECONDS` 可调，`LEASE_REAPER_DISABLED=1` 可关闭）。
