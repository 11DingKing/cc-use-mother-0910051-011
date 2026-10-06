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

热线集中转入时，多名核查人员可能同时打开同一条线索。系统为线索办理提供
**有期限的独占认领租约**，防止重复调查与离岗线索长期无人接手。

### 并发与一致性保证

- **独占认领**：`clue_leases` 表上对 `status='ACTIVE'` 建有部分唯一索引，
  并发认领由数据库裁决，至多一人成功，其余返回 `409`。
- **领取即固定**：认领成功时冻结证据摘要 `evidence_summary`、稳定证据哈希
  `evidence_hash` 与办理权限 `permissions`。哈希始终基于服务端完整证据
  （含举报人明文）规范化计算，与查看者角色无关，故字段被裁剪、续租或转派后
  哈希保持稳定；证据实质内容变更后哈希才变化。
- **生命周期留痕**：认领 / 续租 / 主动释放 / 超时回收 / 主管强制转派 / 结案
  终结均写入只追加的租约事件表 `clue_lease_events`，且续租、释放、转派必须
  提交原因。
- **乐观版本闸门**：每次续租 / 释放 / 回收 / 转派 / 结案都会推进租约
  `version`。提交核查记录或结案必须出示当前持有人 + 租约编号 + 版本；
  原承办人租约过期或被转派后的迟到请求返回 `409`，不能覆盖新承办人的工作。
- **超时回收与恢复幂等**：租约到期后由启动恢复任务（或
  `POST /api/clues/leases/recover-expired`）条件回收。回收使用带状态/版本谓词
  的条件 UPDATE，以 `rowcount` 判定是否真实迁移；状态迁移与审计事件同事务落库，
  因此服务重启后恢复任务重复执行，同一条租约只产生一次回收、至多一次转派。
- **举报人字段按角色裁剪**：`GET /api/clues/{id}` 依据请求头 `X-User-Role`
  （`INSPECTOR`/`SUPERVISOR`/`ADMIN`，默认核查员）返回举报人信息：核查员得到
  脱敏值且不含联系明细，主管/管理员可见明文；通用列表接口不返回举报人字段。

### 接口一览（前缀 `/api/clues`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/{id}/leases/claim` | 认领线索，返回租约（含证据摘要、哈希、权限、版本、到期时间） |
| GET | `/{id}/leases/active` | 查询当前有效租约 |
| POST | `/{id}/leases/renew` | 续租（必填原因，校验持有人与版本，推进版本） |
| POST | `/{id}/leases/release` | 主动释放（必填原因，线索回到待分派池） |
| POST | `/{id}/leases/reassign` | 主管强制转派（需主管角色与原因，原租约终结、新租约立约） |
| POST | `/leases/recover-expired` | 超时回收/可选转派（需主管角色，幂等） |
| GET | `/{id}/events` | 查询租约生命周期审计事件 |
| POST | `/{id}/inspections` | 提交核查记录（可带 `lease_id`+`lease_version` 做版本闸门） |
| POST | `/{id}/conclude` | 结案（带 `holder`+`lease_id`+`lease_version` 严格校验） |

旧的 `POST /{id}/assign` 仍兼容：分派时自动建立一条认领租约，已被他人持有的
线索不能重复分派。

