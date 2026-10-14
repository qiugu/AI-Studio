"""监控审计服务：审计日志查询、模型调用查询、Token 统计、Dashboard 聚合。"""
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.models.audit_log import AuditLog
from app.models.model_call_log import ModelCallLog
from app.models.token_usage import TokenUsage
from app.models.user import User
from app.models.agent import Agent
from app.services.token_usage import TokenUsageService


class AuditService:
    """监控审计服务（租户维度）。"""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # ── 审计日志 ──────────────────────────────────────────────────────────
    def list_audit_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        status_code: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ):
        query = self.db.query(AuditLog).filter(AuditLog.tenant_id == self.tenant_id)
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource:
            query = query.filter(AuditLog.resource == resource)
        if status_code:
            query = query.filter(AuditLog.status_code == status_code)
        if start_time:
            query = query.filter(AuditLog.created_at >= start_time)
        if end_time:
            query = query.filter(AuditLog.created_at <= end_time)
        query = query.order_by(AuditLog.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    # ── 模型调用日志 ──────────────────────────────────────────────────────
    def list_model_calls(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        model_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ):
        query = self.db.query(ModelCallLog).filter(ModelCallLog.tenant_id == self.tenant_id)
        if user_id:
            query = query.filter(ModelCallLog.user_id == user_id)
        if agent_id:
            query = query.filter(ModelCallLog.agent_id == agent_id)
        if model_id:
            query = query.filter(ModelCallLog.model_id == model_id)
        if status:
            query = query.filter(ModelCallLog.status == status)
        if start_time:
            query = query.filter(ModelCallLog.created_at >= start_time)
        if end_time:
            query = query.filter(ModelCallLog.created_at <= end_time)
        query = query.order_by(ModelCallLog.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    # ── 聚合统计 ──────────────────────────────────────────────────────────
    def _trend(self, start_time: datetime, end_time: datetime) -> list[dict]:
        rows = (
            self.db.query(
                func.date(TokenUsage.created_at).label("date"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.count(TokenUsage.id).label("call_count"),
            )
            .filter(
                TokenUsage.tenant_id == self.tenant_id,
                TokenUsage.created_at >= start_time,
                TokenUsage.created_at <= end_time,
            )
            .group_by(func.date(TokenUsage.created_at))
            .order_by(func.date(TokenUsage.created_at))
            .all()
        )
        return [
            {
                "date": str(r.date),
                "total_tokens": int(r.total_tokens or 0),
                "call_count": int(r.call_count or 0),
            }
            for r in rows
        ]

    def _group_by(self, column) -> list[dict]:
        rows = (
            self.db.query(
                column.label("key"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.count(TokenUsage.id).label("call_count"),
            )
            .filter(TokenUsage.tenant_id == self.tenant_id)
            .group_by(column)
            .all()
        )
        return [
            {
                "key": r.key,
                "total_tokens": int(r.total_tokens or 0),
                "call_count": int(r.call_count or 0),
            }
            for r in rows
        ]

    def token_stats(
        self,
        days: int = 30,
        *,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> dict:
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        usage_svc = TokenUsageService(self.db, self.tenant_id)
        totals = usage_svc.get_usage_by_time_range(
            start_time, end_time, agent_id=agent_id, user_id=user_id, model_id=model_id
        )
        return {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "totals": {
                "key": None,
                "total_tokens": totals["total_tokens"],
                "call_count": totals["call_count"],
            },
            "trend": self._trend(start_time, end_time),
            "by_model": [] if model_id else self._group_by(TokenUsage.model_id),
            "by_agent": [] if agent_id else self._group_by(TokenUsage.agent_id),
            "by_user": [] if user_id else self._group_by(TokenUsage.user_id),
        }

    def dashboard(self) -> dict:
        end_time = datetime.now()
        start_time = end_time - timedelta(days=30)
        active_users = (
            self.db.query(User)
            .filter(User.tenant_id == self.tenant_id, User.deleted_at.is_(None), User.status.is_(True))
            .count()
        )
        total_agents = (
            self.db.query(Agent)
            .filter(Agent.tenant_id == self.tenant_id, Agent.deleted_at.is_(None))
            .count()
        )
        usage = TokenUsageService(self.db, self.tenant_id).get_usage_by_time_range(start_time, end_time)
        top_models = sorted(
            self._group_by(TokenUsage.model_id), key=lambda x: x["total_tokens"], reverse=True
        )[:5]
        return {
            "active_users": active_users,
            "total_agents": total_agents,
            "total_tokens_30d": usage["total_tokens"],
            "total_calls_30d": usage["call_count"],
            "token_trend": self._trend(start_time, end_time),
            "top_models": top_models,
        }


def record_model_call(
    db: Session,
    tenant_id: str,
    *,
    model_id: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    provider_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "success",
    error_message: Optional[str] = None,
) -> ModelCallLog:
    """记录一次模型调用（在 LLM 调用完成后由 agent 服务调用）。"""
    log = ModelCallLog(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        model_id=model_id,
        provider_id=provider_id,
        conversation_id=conversation_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        status=status,
        error_message=error_message,
    )
    db.add(log)
    db.flush()
    return log
