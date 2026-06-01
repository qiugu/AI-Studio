from typing import Generic, TypeVar, Type, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    泛型 Repository 基类，自动注入 tenant_id 过滤，防止跨租户数据泄露。
    所有业务 Repository 应继承此类。
    """

    def __init__(self, model: Type[ModelType], db: Session, tenant_id: int):
        self.model = model
        self.db = db
        self.tenant_id = tenant_id

    def _tenant_filter(self) -> Any:
        """仅过滤当前租户数据"""
        return and_(
            self.model.tenant_id == self.tenant_id,  # type: ignore[attr-defined]
            self.model.deleted_at.is_(None) if hasattr(self.model, 'deleted_at') else True,  # type: ignore[attr-defined]
        )

    def _tenant_or_public_filter(self) -> Any:
        """过滤当前租户数据或公共数据（tenant_id=NULL）"""
        from sqlalchemy import or_
        base_condition = or_(
            self.model.tenant_id == self.tenant_id,  # type: ignore[attr-defined]
            self.model.tenant_id.is_(None),  # type: ignore[attr-defined]
        )
        if hasattr(self.model, 'deleted_at'):
            return and_(base_condition, self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return base_condition

    def get_by_id(self, resource_id: int) -> Optional[ModelType]:
        return (
            self.db.query(self.model)
            .filter(self._tenant_filter(), self.model.id == resource_id)  # type: ignore[attr-defined]
            .first()
        )

    def list(
        self,
        page: int = 1,
        page_size: int = 20,
        **filters: Any,
    ) -> list[ModelType]:
        query = self.db.query(self.model).filter(self._tenant_filter())
        for key, value in filters.items():
            if value is not None and hasattr(self.model, key):
                query = query.filter(getattr(self.model, key) == value)
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count(self, **filters: Any) -> int:
        query = self.db.query(self.model).filter(self._tenant_filter())
        for key, value in filters.items():
            if value is not None and hasattr(self.model, key):
                query = query.filter(getattr(self.model, key) == value)
        return query.count()

    def create(self, **kwargs: Any) -> ModelType:
        kwargs.setdefault('tenant_id', self.tenant_id)
        instance = self.model(**kwargs)
        self.db.add(instance)
        self.db.flush()
        return instance

    def update(self, instance: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        self.db.flush()
        return instance

    def delete(self, instance: ModelType) -> None:
        """软删除"""
        from datetime import datetime, timezone
        if hasattr(instance, 'deleted_at'):
            instance.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
            self.db.flush()
        else:
            self.db.delete(instance)
            self.db.flush()
