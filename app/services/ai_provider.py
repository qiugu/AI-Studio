from sqlalchemy.orm import Session

from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.schemas.ai_provider import AIProviderCreate, AIProviderUpdate, ConnectivityTestResult
from app.core.exceptions import NotFoundException, ConflictException
from app.core.authorization import AuthorizationService
from app.models.user import User
from app.utils.encryption import encrypt, decrypt
from app.utils.secret_fields import contains_sensitive_field
from app.utils import llm as llm_utils
from app.core.reauthentication import require_current_password


class AIProviderService:
    def __init__(self, db: Session, tenant_id: str, actor: User | None = None):
        self.db = db
        self.tenant_id = tenant_id
        self.actor = actor
        self.authorization = AuthorizationService(db)

    def _get_or_404(self, provider_id: str) -> AIProvider:
        provider = (
            self.db.query(AIProvider)
            .filter(
                AIProvider.id == provider_id,
                AIProvider.tenant_id == self.tenant_id,
            )
            .first()
        )
        if not provider:
            raise NotFoundException("AIProvider", provider_id)
        return provider

    @staticmethod
    def _credential_change(api_key: str | None, config: dict | None) -> bool:
        return api_key is not None or contains_sensitive_field(config)

    def list(self, page: int = 1, page_size: int = 20, status: bool | None = None):
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor, self.tenant_id, "ai_provider", "read"
            )
        query = self.db.query(AIProvider).filter(
            AIProvider.tenant_id == self.tenant_id
        )
        if status is not None:
            query = query.filter(AIProvider.status == status)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get(self, provider_id: str) -> AIProvider:
        provider = self._get_or_404(provider_id)
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor,
                self.tenant_id,
                "ai_provider",
                "read",
                resource_obj=provider,
            )
        return provider

    def create(self, data: AIProviderCreate) -> AIProvider:
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor, self.tenant_id, "ai_provider", "create"
            )
            if self._credential_change(data.api_key, data.config):
                require_current_password(
                    self.actor, data.current_password, "ai_provider_credential_create"
                )
        provider = AIProvider(
            tenant_id=self.tenant_id,
            name=data.name,
            provider_type=data.provider_type,
            api_base_url=data.api_base_url,
            api_key_encrypted=encrypt(data.api_key) if data.api_key else None,
            config=data.config,
            status=data.status,
        )
        self.db.add(provider)
        self.db.flush()
        return provider

    def update(self, provider_id: str, data: AIProviderUpdate) -> AIProvider:
        provider = self._get_or_404(provider_id)
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor,
                self.tenant_id,
                "ai_provider",
                "update",
                resource_obj=provider,
            )
            if self._credential_change(data.api_key, data.config):
                require_current_password(
                    self.actor, data.current_password, "ai_provider_credential_update"
                )
        if data.name is not None:
            provider.name = data.name
        if data.provider_type is not None:
            provider.provider_type = data.provider_type
        if data.api_base_url is not None:
            provider.api_base_url = data.api_base_url
        if data.api_key is not None:
            provider.api_key_encrypted = encrypt(data.api_key)
        if data.config is not None:
            provider.config = data.config
        if data.status is not None:
            provider.status = data.status
        self.db.flush()
        return provider

    def delete(self, provider_id: str) -> None:
        provider = self._get_or_404(provider_id)
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor,
                self.tenant_id,
                "ai_provider",
                "delete",
                resource_obj=provider,
            )
        # 检查是否有模型依赖此供应商
        model_count = (
            self.db.query(AIModel)
            .filter(AIModel.provider_id == provider_id)
            .count()
        )
        if model_count > 0:
            raise ConflictException(
                f"Cannot delete provider: {model_count} model(s) are using it"
            )
        self.db.delete(provider)
        self.db.flush()

    def test_connectivity(
        self, provider_id: str, model_name: str
    ) -> ConnectivityTestResult:
        provider = self._get_or_404(provider_id)
        if self.actor is not None:
            self.authorization.require_permission(
                self.actor,
                self.tenant_id,
                "ai_provider",
                "test",
                resource_obj=provider,
            )
        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        result = llm_utils.test_connectivity(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=provider.api_base_url,
            model_name=model_name,
        )
        return ConnectivityTestResult(**result)
