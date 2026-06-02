from sqlalchemy.orm import Session

from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.schemas.ai_provider import AIProviderCreate, AIProviderUpdate, ConnectivityTestResult
from app.core.exceptions import NotFoundException, ConflictException
from app.utils.encryption import encrypt, decrypt
from app.utils import llm as llm_utils


class AIProviderService:
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    def _get_or_404(self, provider_id: int) -> AIProvider:
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

    def list(self, page: int = 1, page_size: int = 20, status: bool | None = None):
        query = self.db.query(AIProvider).filter(
            AIProvider.tenant_id == self.tenant_id
        )
        if status is not None:
            query = query.filter(AIProvider.status == status)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get(self, provider_id: int) -> AIProvider:
        return self._get_or_404(provider_id)

    def create(self, data: AIProviderCreate) -> AIProvider:
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

    def update(self, provider_id: int, data: AIProviderUpdate) -> AIProvider:
        provider = self._get_or_404(provider_id)
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

    def delete(self, provider_id: int) -> None:
        provider = self._get_or_404(provider_id)
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
        self, provider_id: int, model_name: str
    ) -> ConnectivityTestResult:
        provider = self._get_or_404(provider_id)
        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        result = llm_utils.test_connectivity(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=provider.api_base_url,
            model_name=model_name,
        )
        return ConnectivityTestResult(**result)
