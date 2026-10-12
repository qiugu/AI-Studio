"""Token统计服务"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.token_usage import TokenUsage


class TokenUsageService:
    """Token统计服务"""

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    def record_usage(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> TokenUsage:
        """记录Token使用情况"""
        usage = TokenUsage(
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            model_id=model_id,
            user_id=user_id,
            conversation_id=conversation_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self.db.add(usage)
        self.db.flush()
        return usage

    def get_usage_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取时间范围内的Token使用统计"""
        query = self.db.query(TokenUsage).filter(
            and_(
                TokenUsage.tenant_id == self.tenant_id,
                TokenUsage.created_at >= start_time,
                TokenUsage.created_at <= end_time,
            )
        )

        if agent_id:
            query = query.filter(TokenUsage.agent_id == agent_id)
        if user_id:
            query = query.filter(TokenUsage.user_id == user_id)
        if model_id:
            query = query.filter(TokenUsage.model_id == model_id)

        # 统计总数
        total_prompt_tokens = query.with_entities(
            func.sum(TokenUsage.prompt_tokens)
        ).scalar() or 0
        total_completion_tokens = query.with_entities(
            func.sum(TokenUsage.completion_tokens)
        ).scalar() or 0
        total_tokens = query.with_entities(
            func.sum(TokenUsage.total_tokens)
        ).scalar() or 0

        # 统计调用次数
        call_count = query.count()

        return {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "call_count": call_count,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }

    def get_usage_by_agent(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """按Agent统计Token使用情况"""
        query = self.db.query(
            TokenUsage.agent_id,
            func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(TokenUsage.completion_tokens).label("total_completion_tokens"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
            func.count(TokenUsage.id).label("call_count"),
        ).filter(TokenUsage.tenant_id == self.tenant_id)

        if start_time:
            query = query.filter(TokenUsage.created_at >= start_time)
        if end_time:
            query = query.filter(TokenUsage.created_at <= end_time)

        query = query.group_by(TokenUsage.agent_id)

        results = []
        for row in query.all():
            results.append({
                "agent_id": row.agent_id,
                "total_prompt_tokens": row.total_prompt_tokens,
                "total_completion_tokens": row.total_completion_tokens,
                "total_tokens": row.total_tokens,
                "call_count": row.call_count,
            })

        return results

    def get_usage_by_model(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """按模型统计Token使用情况"""
        query = self.db.query(
            TokenUsage.model_id,
            func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(TokenUsage.completion_tokens).label("total_completion_tokens"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
            func.count(TokenUsage.id).label("call_count"),
        ).filter(TokenUsage.tenant_id == self.tenant_id)

        if start_time:
            query = query.filter(TokenUsage.created_at >= start_time)
        if end_time:
            query = query.filter(TokenUsage.created_at <= end_time)

        query = query.group_by(TokenUsage.model_id)

        results = []
        for row in query.all():
            results.append({
                "model_id": row.model_id,
                "total_prompt_tokens": row.total_prompt_tokens,
                "total_completion_tokens": row.total_completion_tokens,
                "total_tokens": row.total_tokens,
                "call_count": row.call_count,
            })

        return results

    def get_usage_by_user(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """按用户统计Token使用情况"""
        query = self.db.query(
            TokenUsage.user_id,
            func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(TokenUsage.completion_tokens).label("total_completion_tokens"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
            func.count(TokenUsage.id).label("call_count"),
        ).filter(TokenUsage.tenant_id == self.tenant_id)

        if start_time:
            query = query.filter(TokenUsage.created_at >= start_time)
        if end_time:
            query = query.filter(TokenUsage.created_at <= end_time)

        query = query.group_by(TokenUsage.user_id)

        results = []
        for row in query.all():
            results.append({
                "user_id": row.user_id,
                "total_prompt_tokens": row.total_prompt_tokens,
                "total_completion_tokens": row.total_completion_tokens,
                "total_tokens": row.total_tokens,
                "call_count": row.call_count,
            })

        return results
