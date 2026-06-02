from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.core.exceptions import QuotaExceededException, NotFoundException


class QuotaService:
    """配额管理服务，在业务层创建资源前检查配额限制。"""

    def __init__(self, db: Session):
        self.db = db

    def _get_tenant(self, tenant_id: int) -> Tenant:
        tenant = (
            self.db.query(Tenant)
            .filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None))
            .first()
        )
        if not tenant:
            raise NotFoundException("Tenant", tenant_id)
        return tenant

    def check_user_quota(self, tenant_id: int) -> None:
        """
        检查用户配额。
        超出配额时抛出 QuotaExceededException（返回 429）。
        """
        tenant = self._get_tenant(tenant_id)
        current_count = (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.deleted_at.is_(None))
            .count()
        )
        if current_count >= tenant.max_users:
            raise QuotaExceededException("users")

    def check_model_quota(self, tenant_id: int) -> None:
        """
        检查 AI 模型配额。
        超出配额时抛出 QuotaExceededException（返回 429）。
        """
        tenant = self._get_tenant(tenant_id)
        from app.models.ai_model import AIModel
        current_count = (
            self.db.query(AIModel)
            .filter(AIModel.tenant_id == tenant_id)
            .count()
        )
        if current_count >= tenant.max_models:
            raise QuotaExceededException("models")
