"""监控审计相关 Schema：审计日志、模型调用日志、Token 统计、Dashboard 聚合。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── 审计日志 ────────────────────────────────────────────────────────────────
class AuditLogOut(BaseModel):
    id: str
    tenant_id: str
    user_id: Optional[str] = None
    action: str
    resource: str
    resource_id: Optional[str] = None
    method: str
    path: str
    status_code: int
    ip_address: Optional[str] = None
    duration_ms: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── 模型调用日志 ──────────────────────────────────────────────────────────────
class ModelCallLogOut(BaseModel):
    id: str
    tenant_id: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    model_id: str
    provider_id: Optional[str] = None
    conversation_id: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    status: str
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Token 统计 ────────────────────────────────────────────────────────────────
class TokenTrendPoint(BaseModel):
    date: str
    total_tokens: int
    call_count: int


class TokenGroupItem(BaseModel):
    key: Optional[str] = None  # model_id / agent_id / user_id
    total_tokens: int
    call_count: int


class TokenStatsOut(BaseModel):
    start_time: str
    end_time: str
    totals: TokenGroupItem
    trend: list[TokenTrendPoint] = []
    by_model: list[TokenGroupItem] = []
    by_agent: list[TokenGroupItem] = []
    by_user: list[TokenGroupItem] = []


# ── Dashboard 聚合 ─────────────────────────────────────────────────────────────
class DashboardOut(BaseModel):
    active_users: int
    total_agents: int
    total_tokens_30d: int
    total_calls_30d: int
    token_trend: list[TokenTrendPoint] = []
    top_models: list[TokenGroupItem] = []
