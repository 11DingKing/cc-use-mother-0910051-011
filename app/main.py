from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .database import engine, Base, SessionLocal
from .routers import (
    institutions, practitioners, procedures,
    compliance, clues, stats, compliance_score
)
from . import lease_service

Base.metadata.create_all(bind=engine)

logger = logging.getLogger("clue-lease-recovery")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务（重）启动后执行一次到期租约回收。

    服务层使用条件 UPDATE + 同事务审计事件，重复执行幂等，
    因此多个 worker 同时启动或多次重启都只会产生一次回收/转派结果。
    """
    db = SessionLocal()
    try:
        result = lease_service.recover_expired_leases(db)
        if result["expired_count"]:
            logger.warning(
                "启动恢复：回收到期租约 %s 条，转派 %s 条",
                result["expired_count"], result["reassigned_count"],
            )
    except Exception:
        logger.exception("启动租约恢复任务失败")
    finally:
        db.close()
    yield


app = FastAPI(
    title="医美合规核验系统 API",
    description="医美机构和从业人员合规核验、项目分级管理、违规线索登记与核查、统计分析",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(institutions.router, prefix="/api/institutions", tags=["机构档案"])
app.include_router(practitioners.router, prefix="/api/practitioners", tags=["从业人员档案"])
app.include_router(procedures.router, prefix="/api/procedures", tags=["医美项目分级管理"])
app.include_router(compliance.router, prefix="/api/compliance", tags=["合规核验"])
app.include_router(clues.router, prefix="/api/clues", tags=["违规线索管理"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计分析"])
app.include_router(compliance_score.router, prefix="/api/compliance-score", tags=["机构合规评分与监管计划"])


@app.get("/api/health", tags=["系统"])
def health_check():
    return {"status": "ok", "service": "医美合规核验系统"}
