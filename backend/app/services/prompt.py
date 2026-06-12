from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.prompt import Prompt
from app.models.prompt_version import PromptVersion
from app.models.prompt_test_log import PromptTestLog
from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.schemas.prompt import (
    PromptCreate,
    PromptUpdate,
    PromptVersionCreate,
    PromptTestRequest,
    PromptTestResult,
)
from app.core.exceptions import NotFoundException, ValidationException
from app.utils import llm as llm_utils
from app.utils.encryption import decrypt

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptService:
    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id

    # ── helpers ──────────────────────────────────────────────────────────────

    def _base_query(self):
        return (
            self.db.query(Prompt)
            .filter(
                Prompt.tenant_id == self.tenant_id,
                Prompt.deleted_at.is_(None),
            )
        )

    def _get_or_404(self, prompt_id: int) -> Prompt:
        p = self._base_query().filter(Prompt.id == prompt_id).first()
        if not p:
            raise NotFoundException("Prompt", prompt_id)
        return p

    def _get_version_or_404(self, prompt_id: int, version_id: int) -> PromptVersion:
        v = (
            self.db.query(PromptVersion)
            .filter(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.id == version_id,
            )
            .first()
        )
        if not v:
            raise NotFoundException("PromptVersion", version_id)
        return v

    @staticmethod
    def _extract_variables(content: str) -> list[str]:
        return list(dict.fromkeys(_VAR_RE.findall(content)))

    @staticmethod
    def render(content: str, variables: dict[str, str]) -> str:
        """Replace {{var}} placeholders. Raises ValidationException for missing vars."""
        needed = list(dict.fromkeys(_VAR_RE.findall(content)))
        missing = [v for v in needed if v not in variables]
        if missing:
            raise ValidationException(f"Missing variables: {', '.join(missing)}")
        result = content
        for k, v in variables.items():
            result = result.replace(f"{{{{{k}}}}}", v)
        return result

    def _current_version(self, prompt_id: int) -> PromptVersion | None:
        return (
            self.db.query(PromptVersion)
            .filter(
                PromptVersion.prompt_id == prompt_id,
                PromptVersion.is_current.is_(True),
            )
            .first()
        )

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Prompt], int]:
        q = self._base_query()
        if category:
            q = q.filter(Prompt.category == category)
        if status:
            q = q.filter(Prompt.status == status)
        total = q.count()
        items = q.order_by(Prompt.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        # attach current_version to each prompt
        for p in items:
            p.current_version = self._current_version(p.id)
        return items, total

    def get(self, prompt_id: int) -> Prompt:
        p = self._get_or_404(prompt_id)
        p.current_version = self._current_version(prompt_id)
        return p

    def create(self, data: PromptCreate, user_id: int | None = None) -> Prompt:
        prompt = Prompt(
            tenant_id=self.tenant_id,
            name=data.name,
            description=data.description,
            category=data.category,
            tags=data.tags,
            status="draft",
            created_by=user_id,
        )
        self.db.add(prompt)
        self.db.flush()  # get prompt.id

        variables = self._extract_variables(data.content)
        version = PromptVersion(
            prompt_id=prompt.id,
            version_number=1,
            content=data.content,
            variables=variables,
            is_current=True,
            created_by=user_id,
        )
        self.db.add(version)
        self.db.flush()
        prompt.current_version = version
        return prompt

    def update(self, prompt_id: int, data: PromptUpdate) -> Prompt:
        p = self._get_or_404(prompt_id)
        update_fields = data.model_dump(exclude_none=True)
        for k, v in update_fields.items():
            setattr(p, k, v)
        self.db.flush()
        p.current_version = self._current_version(prompt_id)
        return p

    def delete(self, prompt_id: int) -> None:
        p = self._get_or_404(prompt_id)
        p.deleted_at = datetime.now(timezone.utc)
        self.db.flush()

    # ── versioning ────────────────────────────────────────────────────────────

    def list_versions(self, prompt_id: int) -> list[PromptVersion]:
        self._get_or_404(prompt_id)
        return (
            self.db.query(PromptVersion)
            .filter(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version_number.desc())
            .all()
        )

    def create_version(
        self,
        prompt_id: int,
        data: PromptVersionCreate,
        user_id: int | None = None,
    ) -> PromptVersion:
        self._get_or_404(prompt_id)
        last = (
            self.db.query(PromptVersion)
            .filter(PromptVersion.prompt_id == prompt_id)
            .order_by(PromptVersion.version_number.desc())
            .first()
        )
        next_num = (last.version_number + 1) if last else 1
        variables = self._extract_variables(data.content)
        version = PromptVersion(
            prompt_id=prompt_id,
            version_number=next_num,
            content=data.content,
            variables=variables,
            is_current=False,
            created_by=user_id,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def activate_version(self, prompt_id: int, version_id: int) -> PromptVersion:
        self._get_or_404(prompt_id)
        target = self._get_version_or_404(prompt_id, version_id)
        # deactivate all versions for this prompt
        self.db.query(PromptVersion).filter(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.is_current.is_(True),
        ).update({"is_current": False}, synchronize_session="evaluate")
        target.is_current = True
        self.db.flush()
        return target

    # ── test run ──────────────────────────────────────────────────────────────

    def test_run(self, prompt_id: int, data: PromptTestRequest) -> PromptTestResult:
        self._get_or_404(prompt_id)
        if data.version_id:
            version = self._get_version_or_404(prompt_id, data.version_id)
        else:
            version = self._current_version(prompt_id)
            if not version:
                raise NotFoundException("PromptVersion (current)", prompt_id)

        rendered = self.render(version.content, data.variables)

        model = (
            self.db.query(AIModel)
            .filter(AIModel.id == data.model_id)
            .first()
        )
        if not model:
            raise NotFoundException("AIModel", data.model_id)

        provider = (
            self.db.query(AIProvider)
            .filter(AIProvider.id == model.provider_id)
            .first()
        )
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)

        api_key = decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else ""
        try:
            raw = llm_utils.invoke_model(
                provider_type=provider.provider_type,
                api_key=api_key,
                api_base_url=provider.api_base_url,
                model_name=model.name,
                messages=[{"role": "user", "content": rendered}],
            )
            log = PromptTestLog(
                prompt_id=prompt_id,
                version_id=version.id,
                tenant_id=self.tenant_id,
                model_id=data.model_id,
                input_vars=data.variables,
                rendered_content=rendered,
                result_content=raw["content"],
                prompt_tokens=raw["prompt_tokens"],
                completion_tokens=raw["completion_tokens"],
                latency_ms=raw["latency_ms"],
                status="success",
            )
            self.db.add(log)
            self.db.flush()
            return PromptTestResult(
                rendered_content=rendered,
                result_content=raw["content"],
                prompt_tokens=raw["prompt_tokens"],
                completion_tokens=raw["completion_tokens"],
                latency_ms=raw["latency_ms"],
            )
        except Exception:
            err_log = PromptTestLog(
                prompt_id=prompt_id,
                version_id=version.id,
                tenant_id=self.tenant_id,
                model_id=data.model_id,
                input_vars=data.variables,
                rendered_content=rendered,
                result_content=None,
                status="error",
            )
            self.db.add(err_log)
            self.db.flush()
            raise
