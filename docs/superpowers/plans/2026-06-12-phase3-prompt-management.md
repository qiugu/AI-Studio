# Phase 3: Prompt Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Prompt CRUD + version management + variable rendering (`{{var}}`) + LLM test-run for the AI-Studio platform.

**Architecture:** Three ORM models (Prompt, PromptVersion, PromptTestLog) backed by a PromptService that handles tenant-scoped CRUD, version creation/activation, variable extraction via regex, template rendering, and LLM invocation for test runs. A REST API layer exposes these capabilities. The frontend adds a list page, a Monaco-editor-based editor, and a detail page with version history and test panel.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Ant Design 6 + `@monaco-editor/react` (frontend), existing `LLMClient` for LLM calls.

---

## File Map

### Backend — create
| File | Responsibility |
|------|----------------|
| `backend/app/models/prompt.py` | Prompt ORM model (metadata, soft-delete) |
| `backend/app/models/prompt_version.py` | PromptVersion ORM model (content, variables JSON, is_current flag) |
| `backend/app/models/prompt_test_log.py` | PromptTestLog ORM model (run record) |
| `backend/app/schemas/prompt.py` | Pydantic request/response models |
| `backend/app/services/prompt.py` | Business logic: CRUD, versioning, rendering, test-run |
| `backend/app/api/prompt.py` | FastAPI router |

### Backend — modify
| File | Change |
|------|--------|
| `backend/app/models/__init__.py` | Add imports for 3 new models |
| `backend/app/main.py` | Register `/prompts` router |

### Frontend — create
| File | Responsibility |
|------|----------------|
| `frontend/src/types/prompt.ts` | TypeScript interfaces |
| `frontend/src/api/prompt.ts` | Axios API calls |
| `frontend/src/components/CodeEditor.tsx` | Thin Monaco Editor wrapper |
| `frontend/src/pages/Prompts/PromptList.tsx` | Table list with filters |
| `frontend/src/pages/Prompts/PromptEditor.tsx` | Create / edit prompt + version |
| `frontend/src/pages/Prompts/PromptDetail.tsx` | Version history + test-run panel |

### Frontend — modify
| File | Change |
|------|--------|
| `frontend/src/App.tsx` | Register Phase 3 routes |

---

## Task 1: Backend ORM Models

**Files:**
- Create: `backend/app/models/prompt.py`
- Create: `backend/app/models/prompt_version.py`
- Create: `backend/app/models/prompt_test_log.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create `backend/app/models/prompt.py`**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, JSON, Boolean, DateTime, func, Text
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # status: draft | published | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 2: Create `backend/app/models/prompt_version.py`**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Integer, Text, JSON, Boolean, DateTime, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # variables extracted from content: ["var1", "var2", ...]
    variables: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 3: Create `backend/app/models/prompt_test_log.py`**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Text, JSON, String, Integer, DateTime, func, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped

from app.core.database import Base


class PromptTestLog(Base):
    __tablename__ = "prompt_test_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    model_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    input_vars: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rendered_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # status: success | error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

Add the three new imports:

```python
from app.models.tenant import Tenant
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.user_role import user_role
from app.models.role_permission import role_permission
from app.models.api_key import ApiKey
from app.models.ai_provider import AIProvider
from app.models.ai_model import AIModel
from app.models.prompt import Prompt
from app.models.prompt_version import PromptVersion
from app.models.prompt_test_log import PromptTestLog

__all__ = [
    "Tenant",
    "User",
    "Role",
    "Permission",
    "user_role",
    "role_permission",
    "ApiKey",
    "AIProvider",
    "AIModel",
    "Prompt",
    "PromptVersion",
    "PromptTestLog",
]
```

- [ ] **Step 5: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add backend/app/models/prompt.py backend/app/models/prompt_version.py backend/app/models/prompt_test_log.py backend/app/models/__init__.py
git commit -m "feat(phase3): add Prompt/PromptVersion/PromptTestLog ORM models"
```

---

## Task 2: Alembic Migration

**Files:**
- Creates: `backend/alembic/versions/<hash>_phase3_add_prompt_tables.py` (auto-generated)

- [ ] **Step 1: Activate venv and generate migration**

```bash
cd /Volumes/Project/qiugu/AI-Studio/backend
source .venv/bin/activate
alembic revision --autogenerate -m "phase3_add_prompt_tables"
```

Expected: a new file created under `alembic/versions/` containing `create_table("prompts", ...)`, `create_table("prompt_versions", ...)`, `create_table("prompt_test_logs", ...)`.

- [ ] **Step 2: Apply migration**

```bash
alembic upgrade head
```

Expected output ends with: `Running upgrade <prev> -> <hash>, phase3_add_prompt_tables`

- [ ] **Step 3: Verify tables exist**

```bash
python -c "
from app.core.database import engine
from sqlalchemy import inspect
insp = inspect(engine)
print(insp.get_table_names())
"
```

Expected: output includes `'prompts'`, `'prompt_versions'`, `'prompt_test_logs'`.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add backend/alembic/versions/
git commit -m "feat(phase3): alembic migration for prompt tables"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `backend/app/schemas/prompt.py`

- [ ] **Step 1: Create `backend/app/schemas/prompt.py`**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PromptVersionOut(BaseModel):
    id: int
    prompt_id: int
    version_number: int
    content: str
    variables: Optional[list[str]]
    is_current: bool
    created_by: Optional[int]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PromptOut(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    category: Optional[str]
    tags: Optional[list[str]]
    status: str
    created_by: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    current_version: Optional[PromptVersionOut] = None

    model_config = {"from_attributes": True}


class PromptCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    content: str = Field(..., description="Initial prompt content, may contain {{variable}} placeholders")


class PromptUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    status: Optional[str] = Field(None, pattern="^(draft|published|archived)$")


class PromptVersionCreate(BaseModel):
    content: str = Field(..., description="New version content")


class PromptTestRequest(BaseModel):
    version_id: Optional[int] = None
    variables: dict[str, str] = Field(default_factory=dict)
    model_id: int


class PromptTestResult(BaseModel):
    rendered_content: str
    result_content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add backend/app/schemas/prompt.py
git commit -m "feat(phase3): add Prompt Pydantic schemas"
```

---

## Task 4: Prompt Service

**Files:**
- Create: `backend/app/services/prompt.py`

**Key methods:**
- `_extract_variables(content)` — returns `list[str]` of `{{var}}` names
- `render(content, variables)` — substitutes `{{var}}` → value, raises `ValidationException` for missing vars
- `list(...)` — paginated list, filters by category/status, respects soft-delete
- `get(id)` — fetch prompt with current version
- `create(data)` — create Prompt + first PromptVersion (v1)
- `update(id, data)` — update metadata
- `delete(id)` — soft-delete (set deleted_at)
- `list_versions(prompt_id)` — all versions for a prompt
- `create_version(prompt_id, data)` — new version, increment version_number, keep is_current=False
- `activate_version(prompt_id, version_id)` — set target version as current, unset others
- `test_run(prompt_id, data)` — render + LLM invoke + write PromptTestLog

- [ ] **Step 1: Create `backend/app/services/prompt.py`**

```python
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
        ).update({"is_current": False})
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
```

- [ ] **Step 2: Verify `ValidationException` exists in exceptions module**

```bash
grep -n "ValidationException" /Volumes/Project/qiugu/AI-Studio/backend/app/core/exceptions.py
```

Expected: at least one line with `class ValidationException`. If missing, add it (see note below).

> **Note:** If `ValidationException` is not defined, open `backend/app/core/exceptions.py` and add:
> ```python
> class ValidationException(AppException):
>     def __init__(self, detail: str):
>         super().__init__(status_code=422, detail=detail)
> ```

- [ ] **Step 3: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add backend/app/services/prompt.py
git commit -m "feat(phase3): add PromptService with CRUD, versioning, rendering, test-run"
```

---

## Task 5: API Router

**Files:**
- Create: `backend/app/api/prompt.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `backend/app/api/prompt.py`**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import CurrentUser, CurrentTenantId
from app.schemas.prompt import (
    PromptCreate,
    PromptUpdate,
    PromptOut,
    PromptVersionCreate,
    PromptVersionOut,
    PromptTestRequest,
    PromptTestResult,
)
from app.schemas.common import ResponseBase, PaginatedData
from app.services.prompt import PromptService

router = APIRouter()


@router.get("", response_model=ResponseBase)
def list_prompts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = Query(None),
    status: str | None = Query(None),
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    items, total = svc.list(page=page, page_size=page_size, category=category, status=status)
    return ResponseBase.ok(
        data=PaginatedData(
            items=[PromptOut.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump()
    )


@router.post("", response_model=ResponseBase)
def create_prompt(
    data: PromptCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    user_id = current_user.id if current_user else None
    prompt = svc.create(data, user_id=user_id)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.get("/{prompt_id}", response_model=ResponseBase)
def get_prompt(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    prompt = svc.get(prompt_id)
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.put("/{prompt_id}", response_model=ResponseBase)
def update_prompt(
    prompt_id: int,
    data: PromptUpdate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    prompt = svc.update(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=PromptOut.model_validate(prompt).model_dump())


@router.delete("/{prompt_id}", response_model=ResponseBase)
def delete_prompt(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    svc.delete(prompt_id)
    db.commit()
    return ResponseBase.ok()


@router.get("/{prompt_id}/versions", response_model=ResponseBase)
def list_versions(
    prompt_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    versions = svc.list_versions(prompt_id)
    return ResponseBase.ok(data=[PromptVersionOut.model_validate(v) for v in versions])


@router.post("/{prompt_id}/versions", response_model=ResponseBase)
def create_version(
    prompt_id: int,
    data: PromptVersionCreate,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    user_id = current_user.id if current_user else None
    version = svc.create_version(prompt_id, data, user_id=user_id)
    db.commit()
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.put("/{prompt_id}/versions/{version_id}/activate", response_model=ResponseBase)
def activate_version(
    prompt_id: int,
    version_id: int,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    version = svc.activate_version(prompt_id, version_id)
    db.commit()
    return ResponseBase.ok(data=PromptVersionOut.model_validate(version).model_dump())


@router.post("/{prompt_id}/test", response_model=ResponseBase)
def test_prompt(
    prompt_id: int,
    data: PromptTestRequest,
    tenant_id: CurrentTenantId = None,
    db: Session = Depends(get_session),
    _current_user: CurrentUser = None,
):
    svc = PromptService(db, tenant_id)
    result = svc.test_run(prompt_id, data)
    db.commit()
    return ResponseBase.ok(data=result.model_dump())
```

- [ ] **Step 2: Register router in `backend/app/main.py`**

Add the import at the top (after existing imports):
```python
from app.api.prompt import router as prompt_router
```

Add the route registration after the existing `app.include_router` lines:
```python
app.include_router(prompt_router, prefix="/prompts", tags=["Prompt管理"])
```

- [ ] **Step 3: Start the server and verify**

```bash
cd /Volumes/Project/qiugu/AI-Studio/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Expected: server starts without import errors. Visit `http://localhost:8000/docs` and confirm `/prompts` routes appear.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add backend/app/api/prompt.py backend/app/main.py
git commit -m "feat(phase3): add Prompt API router and register in main.py"
```

---

## Task 6: Frontend — Install Monaco Editor

**Files:**
- Modify: `frontend/package.json` (via npm install)

- [ ] **Step 1: Install `@monaco-editor/react`**

```bash
cd /Volumes/Project/qiugu/AI-Studio/frontend
npm install @monaco-editor/react
```

Expected: package added to `dependencies` in `package.json`.

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(phase3): install @monaco-editor/react"
```

---

## Task 7: Frontend — Types and API Layer

**Files:**
- Create: `frontend/src/types/prompt.ts`
- Create: `frontend/src/api/prompt.ts`

- [ ] **Step 1: Create `frontend/src/types/prompt.ts`**

```typescript
export type PromptStatus = 'draft' | 'published' | 'archived'

export interface PromptVersion {
  id: number
  prompt_id: number
  version_number: number
  content: string
  variables: string[] | null
  is_current: boolean
  created_by: number | null
  created_at: string | null
}

export interface Prompt {
  id: number
  tenant_id: number
  name: string
  description: string | null
  category: string | null
  tags: string[] | null
  status: PromptStatus
  created_by: number | null
  created_at: string | null
  updated_at: string | null
  current_version: PromptVersion | null
}

export interface PromptCreateRequest {
  name: string
  description?: string
  category?: string
  tags?: string[]
  content: string
}

export interface PromptUpdateRequest {
  name?: string
  description?: string
  category?: string
  tags?: string[]
  status?: PromptStatus
}

export interface PromptVersionCreateRequest {
  content: string
}

export interface PromptTestRequest {
  version_id?: number
  variables: Record<string, string>
  model_id: number
}

export interface PromptTestResult {
  rendered_content: string
  result_content: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
}
```

- [ ] **Step 2: Create `frontend/src/api/prompt.ts`**

```typescript
import apiClient from './client'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/api'
import type {
  Prompt,
  PromptVersion,
  PromptCreateRequest,
  PromptUpdateRequest,
  PromptVersionCreateRequest,
  PromptTestRequest,
  PromptTestResult,
} from '@/types/prompt'

export async function listPrompts(
  params?: PageParams & { category?: string; status?: string }
): Promise<ApiResponse<PaginatedData<Prompt>>> {
  const response = await apiClient.get('/prompts', { params })
  return response as unknown as ApiResponse<PaginatedData<Prompt>>
}

export async function getPrompt(id: number): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.get(`/prompts/${id}`)
  return response as unknown as ApiResponse<Prompt>
}

export async function createPrompt(data: PromptCreateRequest): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.post('/prompts', data)
  return response as unknown as ApiResponse<Prompt>
}

export async function updatePrompt(
  id: number,
  data: PromptUpdateRequest
): Promise<ApiResponse<Prompt>> {
  const response = await apiClient.put(`/prompts/${id}`, data)
  return response as unknown as ApiResponse<Prompt>
}

export async function deletePrompt(id: number): Promise<ApiResponse<null>> {
  const response = await apiClient.delete(`/prompts/${id}`)
  return response as unknown as ApiResponse<null>
}

export async function listVersions(promptId: number): Promise<ApiResponse<PromptVersion[]>> {
  const response = await apiClient.get(`/prompts/${promptId}/versions`)
  return response as unknown as ApiResponse<PromptVersion[]>
}

export async function createVersion(
  promptId: number,
  data: PromptVersionCreateRequest
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.post(`/prompts/${promptId}/versions`, data)
  return response as unknown as ApiResponse<PromptVersion>
}

export async function activateVersion(
  promptId: number,
  versionId: number
): Promise<ApiResponse<PromptVersion>> {
  const response = await apiClient.put(`/prompts/${promptId}/versions/${versionId}/activate`, {})
  return response as unknown as ApiResponse<PromptVersion>
}

export async function testPrompt(
  promptId: number,
  data: PromptTestRequest
): Promise<ApiResponse<PromptTestResult>> {
  const response = await apiClient.post(`/prompts/${promptId}/test`, data)
  return response as unknown as ApiResponse<PromptTestResult>
}
```

- [ ] **Step 3: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/types/prompt.ts frontend/src/api/prompt.ts
git commit -m "feat(phase3): add Prompt TypeScript types and API client"
```

---

## Task 8: Frontend — CodeEditor Component

**Files:**
- Create: `frontend/src/components/CodeEditor.tsx`

- [ ] **Step 1: Create `frontend/src/components/CodeEditor.tsx`**

```tsx
import Editor from '@monaco-editor/react'

interface Props {
  value: string
  onChange?: (value: string) => void
  language?: string
  height?: string | number
  readOnly?: boolean
}

export default function CodeEditor({
  value,
  onChange,
  language = 'markdown',
  height = 400,
  readOnly = false,
}: Props) {
  return (
    <Editor
      height={height}
      language={language}
      value={value}
      options={{
        minimap: { enabled: false },
        wordWrap: 'on',
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        readOnly,
        fontSize: 14,
      }}
      onChange={(v) => onChange?.(v ?? '')}
    />
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/components/CodeEditor.tsx
git commit -m "feat(phase3): add Monaco Editor wrapper component"
```

---

## Task 9: Frontend — PromptList Page

**Files:**
- Create: `frontend/src/pages/Prompts/PromptList.tsx`

- [ ] **Step 1: Create `frontend/src/pages/Prompts/PromptList.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Select,
  Typography,
  Badge,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { listPrompts, deletePrompt } from '@/api/prompt'
import type { Prompt, PromptStatus } from '@/types/prompt'

const { Title } = Typography

const STATUS_COLORS: Record<PromptStatus, string> = {
  draft: 'default',
  published: 'success',
  archived: 'warning',
}

const STATUS_LABELS: Record<PromptStatus, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

export default function PromptList() {
  const navigate = useNavigate()
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<{ category?: string; status?: string }>({})

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listPrompts({ page: 1, page_size: 100, ...filters })
      setPrompts(res.data?.items ?? [])
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const handleDelete = async (id: number) => {
    try {
      await deletePrompt(id)
      message.success('删除成功')
      fetchAll()
    } catch {
      // interceptor handles error toast
    }
  }

  const columns: ColumnsType<Prompt> = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      render: (cat) => cat ? <Tag>{cat}</Tag> : '—',
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[] | null) =>
        tags?.length ? tags.map((t) => <Tag key={t}>{t}</Tag>) : '—',
    },
    {
      title: '变量',
      key: 'variables',
      render: (_, record) => {
        const vars = record.current_version?.variables ?? []
        return vars.length ? vars.map((v) => <Tag color="blue" key={v}>{`{{${v}}}`}</Tag>) : '—'
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: PromptStatus) => (
        <Badge status={STATUS_COLORS[status] as any} text={STATUS_LABELS[status]} />
      ),
    },
    {
      title: '版本',
      key: 'version',
      render: (_, record) =>
        record.current_version ? `v${record.current_version.version_number}` : '—',
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/prompts/${record.id}`)}
          />
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/prompts/${record.id}/edit`)}
          />
          <Popconfirm
            title="确认删除此 Prompt？"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
          >
            <Button size="small" icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>Prompt 管理</Title>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/prompts/new')}
        >
          新建 Prompt
        </Button>
      </div>

      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="筛选分类"
          allowClear
          style={{ width: 160 }}
          options={[
            { value: 'system', label: '系统提示' },
            { value: 'user', label: '用户指令' },
            { value: 'few-shot', label: 'Few-shot' },
            { value: 'chain', label: '链式调用' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, category: v }))}
        />
        <Select
          placeholder="筛选状态"
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'draft', label: '草稿' },
            { value: 'published', label: '已发布' },
            { value: 'archived', label: '已归档' },
          ]}
          onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
        />
      </Space>

      <Table
        columns={columns}
        dataSource={prompts}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/pages/Prompts/PromptList.tsx
git commit -m "feat(phase3): add PromptList page"
```

---

## Task 10: Frontend — PromptEditor Page

**Files:**
- Create: `frontend/src/pages/Prompts/PromptEditor.tsx`

This page handles both **create** (`/prompts/new`) and **edit** (`/prompts/:id/edit`). In edit mode it loads the current version content into the editor and supports saving as a new version.

- [ ] **Step 1: Create `frontend/src/pages/Prompts/PromptEditor.tsx`**

```tsx
import { useEffect, useState } from 'react'
import {
  Form,
  Input,
  Select,
  Button,
  Space,
  Typography,
  Card,
  Tag,
  message,
  Row,
  Col,
} from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import CodeEditor from '@/components/CodeEditor'
import { createPrompt, getPrompt, updatePrompt, createVersion } from '@/api/prompt'
import type { Prompt } from '@/types/prompt'

const { Title, Text } = Typography

/** Extract {{variable}} names from content */
function extractVars(content: string): string[] {
  const matches = content.match(/\{\{(\w+)\}\}/g) ?? []
  return [...new Set(matches.map((m) => m.slice(2, -2)))]
}

export default function PromptEditor() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [content, setContent] = useState('')
  const [variables, setVariables] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [prompt, setPrompt] = useState<Prompt | null>(null)

  useEffect(() => {
    if (isEdit && id) {
      getPrompt(Number(id)).then((res) => {
        const p = res.data!
        setPrompt(p)
        form.setFieldsValue({
          name: p.name,
          description: p.description,
          category: p.category,
          tags: p.tags,
          status: p.status,
        })
        const c = p.current_version?.content ?? ''
        setContent(c)
        setVariables(extractVars(c))
      })
    }
  }, [id, isEdit, form])

  const handleContentChange = (val: string) => {
    setContent(val)
    setVariables(extractVars(val))
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (!isEdit) {
        const res = await createPrompt({ ...values, content })
        message.success('Prompt 创建成功')
        navigate(`/prompts/${res.data!.id}`)
      } else {
        await updatePrompt(Number(id), {
          name: values.name,
          description: values.description,
          category: values.category,
          tags: values.tags,
          status: values.status,
        })
        // if content changed from current version, create new version
        if (prompt?.current_version?.content !== content) {
          await createVersion(Number(id), { content })
          message.success('已保存元数据并创建新版本')
        } else {
          message.success('Prompt 更新成功')
        }
        navigate(`/prompts/${id}`)
      }
    } catch {
      // interceptor handles error toast
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          {isEdit ? '编辑 Prompt' : '新建 Prompt'}
        </Title>
        <Space>
          <Button onClick={() => navigate(-1)}>取消</Button>
          <Button type="primary" loading={loading} onClick={handleSubmit}>
            {isEdit ? '保存' : '创建'}
          </Button>
        </Space>
      </div>

      <Row gutter={16}>
        {/* Left: variables panel */}
        <Col span={5}>
          <Card title="变量列表" size="small" style={{ minHeight: 500 }}>
            {variables.length === 0 ? (
              <Text type="secondary">在内容中使用 {'{{变量名}}'} 语法添加变量</Text>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {variables.map((v) => (
                  <Tag color="blue" key={v}>{`{{${v}}}`}</Tag>
                ))}
              </Space>
            )}
          </Card>
        </Col>

        {/* Right: editor + meta form */}
        <Col span={19}>
          <Card title="Prompt 内容" size="small" style={{ marginBottom: 16 }}>
            <CodeEditor value={content} onChange={handleContentChange} height={360} />
          </Card>

          <Card title="基本信息" size="small">
            <Form form={form} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                    <Input placeholder="例：客服欢迎语" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="category" label="分类">
                    <Select
                      allowClear
                      placeholder="选择分类"
                      options={[
                        { value: 'system', label: '系统提示' },
                        { value: 'user', label: '用户指令' },
                        { value: 'few-shot', label: 'Few-shot' },
                        { value: 'chain', label: '链式调用' },
                      ]}
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="description" label="描述">
                <Input.TextArea rows={2} placeholder="可选描述" />
              </Form.Item>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="tags" label="标签">
                    <Select mode="tags" placeholder="输入后回车添加" />
                  </Form.Item>
                </Col>
                {isEdit && (
                  <Col span={12}>
                    <Form.Item name="status" label="状态">
                      <Select
                        options={[
                          { value: 'draft', label: '草稿' },
                          { value: 'published', label: '已发布' },
                          { value: 'archived', label: '已归档' },
                        ]}
                      />
                    </Form.Item>
                  </Col>
                )}
              </Row>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/pages/Prompts/PromptEditor.tsx
git commit -m "feat(phase3): add PromptEditor page with Monaco editor and variable detection"
```

---

## Task 11: Frontend — PromptDetail Page

**Files:**
- Create: `frontend/src/pages/Prompts/PromptDetail.tsx`

This page shows version history and a test-run panel. The test panel lets users fill in variable values, choose a model, and invoke the LLM.

- [ ] **Step 1: Create `frontend/src/pages/Prompts/PromptDetail.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Space,
  Typography,
  Card,
  Tag,
  Table,
  Form,
  Input,
  Select,
  Divider,
  message,
  Spin,
  Row,
  Col,
  Badge,
} from 'antd'
import { EditOutlined, PlayCircleOutlined, CheckOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import CodeEditor from '@/components/CodeEditor'
import { getPrompt, listVersions, activateVersion, testPrompt } from '@/api/prompt'
import { listModels } from '@/api/ai-model'
import type { Prompt, PromptVersion, PromptTestResult } from '@/types/prompt'
import type { AIModel } from '@/types/ai-model'

const { Title, Text } = Typography

export default function PromptDetail() {
  const { id } = useParams<{ id: string }>()
  const promptId = Number(id)
  const navigate = useNavigate()

  const [prompt, setPrompt] = useState<Prompt | null>(null)
  const [versions, setVersions] = useState<PromptVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<PromptVersion | null>(null)
  const [models, setModels] = useState<AIModel[]>([])
  const [testResult, setTestResult] = useState<PromptTestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    const [pRes, vRes, mRes] = await Promise.all([
      getPrompt(promptId),
      listVersions(promptId),
      listModels({ page: 1, page_size: 100, model_type: 'chat' }),
    ])
    const p = pRes.data!
    setPrompt(p)
    setVersions(vRes.data ?? [])
    setModels(mRes.data?.items ?? [])
    const current = (vRes.data ?? []).find((v) => v.is_current) ?? (vRes.data ?? [])[0] ?? null
    setSelectedVersion(current)
  }, [promptId])

  useEffect(() => {
    load()
  }, [load])

  const handleActivate = async (versionId: number) => {
    try {
      await activateVersion(promptId, versionId)
      message.success('版本已激活')
      load()
    } catch {
      // interceptor handles error toast
    }
  }

  const handleTest = async () => {
    const values = await form.validateFields()
    const vars: Record<string, string> = {}
    const varNames = selectedVersion?.variables ?? []
    varNames.forEach((v) => { vars[v] = values[`var_${v}`] ?? '' })
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testPrompt(promptId, {
        version_id: selectedVersion?.id,
        variables: vars,
        model_id: values.model_id,
      })
      setTestResult(res.data!)
    } catch {
      // interceptor handles error toast
    } finally {
      setTesting(false)
    }
  }

  const versionColumns: ColumnsType<PromptVersion> = [
    {
      title: '版本',
      key: 'v',
      render: (_, r) => (
        <Space>
          <span>{`v${r.version_number}`}</span>
          {r.is_current && <Tag color="green">当前</Tag>}
        </Space>
      ),
    },
    {
      title: '变量',
      key: 'vars',
      render: (_, r) => r.variables?.map((v) => <Tag key={v} color="blue">{`{{${v}}}`}</Tag>) ?? '—',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v) => v?.slice(0, 16) ?? '—' },
    {
      title: '操作',
      key: 'actions',
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => setSelectedVersion(r)}>查看</Button>
          {!r.is_current && (
            <Button
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handleActivate(r.id)}
            >
              激活
            </Button>
          )}
        </Space>
      ),
    },
  ]

  if (!prompt) return <Spin />

  const varNames = selectedVersion?.variables ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>{prompt.name}</Title>
          <Badge
            status={prompt.status === 'published' ? 'success' : prompt.status === 'archived' ? 'warning' : 'default'}
            text={prompt.status === 'published' ? '已发布' : prompt.status === 'archived' ? '已归档' : '草稿'}
          />
        </Space>
        <Button
          icon={<EditOutlined />}
          onClick={() => navigate(`/prompts/${promptId}/edit`)}
        >
          编辑
        </Button>
      </div>

      <Row gutter={16}>
        <Col span={14}>
          {/* Version history */}
          <Card title="版本历史" size="small" style={{ marginBottom: 16 }}>
            <Table
              columns={versionColumns}
              dataSource={versions}
              rowKey="id"
              size="small"
              pagination={false}
            />
          </Card>

          {/* Selected version content preview */}
          {selectedVersion && (
            <Card
              title={`版本内容 — v${selectedVersion.version_number}`}
              size="small"
            >
              <CodeEditor value={selectedVersion.content} readOnly height={300} />
            </Card>
          )}
        </Col>

        <Col span={10}>
          {/* Test run panel */}
          <Card title={<Space><PlayCircleOutlined />测试运行</Space>} size="small">
            <Form form={form} layout="vertical">
              <Form.Item
                name="model_id"
                label="选择模型"
                rules={[{ required: true, message: '请选择模型' }]}
              >
                <Select
                  placeholder="选择 Chat 模型"
                  options={models.map((m) => ({ value: m.id, label: m.display_name }))}
                />
              </Form.Item>

              {varNames.length > 0 && (
                <>
                  <Divider orientation="left" plain>变量值</Divider>
                  {varNames.map((v) => (
                    <Form.Item
                      key={v}
                      name={`var_${v}`}
                      label={`{{${v}}}`}
                    >
                      <Input placeholder={`输入 ${v} 的值`} />
                    </Form.Item>
                  ))}
                </>
              )}

              <Button
                type="primary"
                block
                icon={<PlayCircleOutlined />}
                loading={testing}
                onClick={handleTest}
              >
                运行测试
              </Button>
            </Form>

            {testResult && (
              <>
                <Divider />
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">
                    {`Tokens: ${testResult.prompt_tokens} + ${testResult.completion_tokens} | 耗时: ${testResult.latency_ms}ms`}
                  </Text>
                </div>
                <Card size="small" title="渲染后内容" style={{ marginBottom: 8 }}>
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                    {testResult.rendered_content}
                  </pre>
                </Card>
                <Card size="small" title="模型返回">
                  <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                    {testResult.result_content}
                  </pre>
                </Card>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/pages/Prompts/PromptDetail.tsx
git commit -m "feat(phase3): add PromptDetail page with version history and test panel"
```

---

## Task 12: Frontend — Register Routes

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update `frontend/src/App.tsx`**

Add imports after the existing Phase 2 imports:
```tsx
import PromptList from '@/pages/Prompts/PromptList'
import PromptEditor from '@/pages/Prompts/PromptEditor'
import PromptDetail from '@/pages/Prompts/PromptDetail'
```

Add routes inside the authenticated layout route (after the AI model routes):
```tsx
{/* Phase 3: Prompt 管理 */}
<Route path="prompts" element={<PromptList />} />
<Route path="prompts/new" element={<PromptEditor />} />
<Route path="prompts/:id/edit" element={<PromptEditor />} />
<Route path="prompts/:id" element={<PromptDetail />} />
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add frontend/src/App.tsx
git commit -m "feat(phase3): register Prompt routes in App.tsx"
```

---

## Task 13: End-to-End Verification

- [ ] **Step 1: Start backend**

```bash
cd /Volumes/Project/qiugu/AI-Studio/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Get a JWT token (login)**

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@example.com","password":"password"}' | python3 -m json.tool
```

Expected: `{"code":0,"data":{"access_token":"...","token_type":"bearer",...}}`

Set token: `TOKEN=<access_token>`

- [ ] **Step 3: Create a Prompt**

```bash
curl -s -X POST http://localhost:8000/prompts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"欢迎语","category":"system","content":"你好，{{name}}！欢迎使用 {{product}}。"}' \
  | python3 -m json.tool
```

Expected: `{"code":0,"data":{"id":1,"name":"欢迎语","current_version":{"variables":["name","product"],...},...}}`

- [ ] **Step 4: List prompts**

```bash
curl -s http://localhost:8000/prompts \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `{"code":0,"data":{"items":[...],"total":1,...}}`

- [ ] **Step 5: Create new version**

```bash
curl -s -X POST http://localhost:8000/prompts/1/versions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"亲爱的 {{name}}，感谢使用 {{product}}！有任何问题请联系 {{support}}。"}' \
  | python3 -m json.tool
```

Expected: `{"code":0,"data":{"version_number":2,"is_current":false,...}}`

- [ ] **Step 6: Activate new version**

```bash
curl -s -X PUT http://localhost:8000/prompts/1/versions/2/activate \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `{"code":0,"data":{"is_current":true,...}}`

- [ ] **Step 7: Start frontend and verify UI**

```bash
cd /Volumes/Project/qiugu/AI-Studio/frontend
npm run dev
```

Open `http://localhost:5173`. Log in, then navigate to **Prompt 管理** in the sidebar:
- [ ] Prompt list page loads with empty state
- [ ] "新建 Prompt" button opens editor
- [ ] Monaco editor renders in editor page, variable list updates as you type `{{var}}`
- [ ] After creating a prompt, detail page shows version history table
- [ ] Test panel visible with model selector and variable inputs

- [ ] **Step 8: Lint check**

```bash
cd /Volumes/Project/qiugu/AI-Studio/frontend
npm run lint
```

Expected: no errors.

- [ ] **Step 9: Final commit**

```bash
cd /Volumes/Project/qiugu/AI-Studio
git add -A
git commit -m "feat(phase3): complete Phase 3 Prompt Management - backend + frontend"
```
