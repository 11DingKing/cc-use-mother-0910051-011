import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .routers import (
    institutions, practitioners, procedures,
    compliance, clues, stats, compliance_score
)
from .lease_service import LeaseReaper

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动即执行一次恢复扫描（覆盖停机期间超时的租约），随后周期回收；
    # 回收为条件更新，重复执行只会产生一次结果。
    reaper = None
    if os.environ.get("LEASE_REAPER_DISABLED") != "1":
        interval = float(os.environ.get("LEASE_REAPER_INTERVAL_SECONDS", "60"))
        reaper = LeaseReaper(interval_seconds=interval)
        reaper.start()
    try:
        yield
    finally:
        if reaper is not None:
            reaper.stop()


app = FastAPI(
    title="医美合规核验系统 API",
    description="医美机构和从业人员合规核验、项目分级管理、违规线索登记与核查、统计分析；"
                "线索办理支持有期限的认领租约（续租/释放/超时回收/强制转派、版本校验与审计）",
    version="1.1.0",
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
