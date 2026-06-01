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
        # 避免循环依赖，动态导入
        from app.models.user import User  # noqa: F811 - 占位，后续阶段引入 AIModel 后替换
        # 阶段一暂无 AIModel，此处仅做 tenant 配额校验框架
        # 后续阶段：替换为 AIModel 的实际查询
        _ = tenant.max_models  # 记录字段已就位，待阶段二实装
