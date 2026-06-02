from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.schemas.ai_model import AIModelCreate, AIModelUpdate, ModelTestResult
from app.core.exceptions import NotFoundException
from app.services.quota import QuotaService
from app.utils import llm as llm_utils
from app.utils.encryption import decrypt


class AIModelService:
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    def _base_filter(self, include_public: bool = False):
        if include_public:
            return or_(
                AIModel.tenant_id == self.tenant_id,
                AIModel.tenant_id.is_(None),
            )
        return AIModel.tenant_id == self.tenant_id

    def _get_or_404(self, model_id: int) -> AIModel:
        model = (
            self.db.query(AIModel)
            .filter(
                self._base_filter(include_public=True),
                AIModel.id == model_id,
            )
            .first()
        )
        if not model:
            raise NotFoundException("AIModel", model_id)
        return model

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        model_type: str | None = None,
        provider_id: int | None = None,
        include_public: bool = False,
    ):
        query = self.db.query(AIModel).filter(self._base_filter(include_public))
        if model_type:
            query = query.filter(AIModel.model_type == model_type)
        if provider_id:
            query = query.filter(AIModel.provider_id == provider_id)
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    def get(self, model_id: int) -> AIModel:
        return self._get_or_404(model_id)

    def create(self, data: AIModelCreate) -> AIModel:
        # 配额检查
        QuotaService(self.db).check_model_quota(self.tenant_id)
        model = AIModel(
            tenant_id=self.tenant_id,
            provider_id=data.provider_id,
            name=data.name,
            display_name=data.display_name,
            model_type=data.model_type,
            config=data.config,
            unit_price_input=data.unit_price_input,
            unit_price_output=data.unit_price_output,
            max_context_tokens=data.max_context_tokens,
            max_output_tokens=data.max_output_tokens,
            status=data.status,
        )
        self.db.add(model)
        self.db.flush()
        return model

    def update(self, model_id: int, data: AIModelUpdate) -> AIModel:
        model = self._get_or_404(model_id)
        # 公共模型（tenant_id=None）不允许普通租户修改
        if model.tenant_id is None:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("ai_model", "update")
        update_fields = data.model_dump(exclude_none=True)
        for key, value in update_fields.items():
            setattr(model, key, value)
        self.db.flush()
        return model

    def delete(self, model_id: int) -> None:
        model = self._get_or_404(model_id)
        if model.tenant_id is None:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("ai_model", "delete")
        self.db.delete(model)
        self.db.flush()

    def test_model(self, model_id: int, messages: list[dict]) -> ModelTestResult:
        model = self._get_or_404(model_id)
        provider = (
            self.db.query(AIProvider)
            .filter(AIProvider.id == model.provider_id)
            .first()
        )
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)
        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        result = llm_utils.invoke_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=provider.api_base_url,
            model_name=model.name,
            messages=messages,
        )
        return ModelTestResult(**result)
