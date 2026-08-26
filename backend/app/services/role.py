"""角色与权限管理服务（租户维度）。"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import role_permission
from app.schemas.role import RoleCreate, RoleUpdate
from app.core.exceptions import NotFoundException, ValidationException

import uuid


def get_role(role_id: str, tenant_id: str, db: Session) -> Role:
    role = db.query(Role).filter(Role.id == role_id, Role.tenant_id == tenant_id).first()
    if not role:
        raise NotFoundException("Role", role_id)
    return role


def list_roles(tenant_id: str, db: Session, page: int = 1, page_size: int = 100):
    query = db.query(Role).filter(Role.tenant_id == tenant_id)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def create_role(data: RoleCreate, tenant_id: str, db: Session) -> Role:
    # 内置角色 code 受保护，禁止创建同名角色
    role = Role(
        tenant_id=tenant_id,
        name=data.name,
        code=f"custom_{uuid.uuid4().hex[:12]}",
        description=data.description,
        status=True,
    )
    db.add(role)
    db.flush()
    if data.permission_ids:
        set_role_permissions(role.id, data.permission_ids, tenant_id, db)
    return role


def update_role(role_id: str, data: RoleUpdate, tenant_id: str, db: Session) -> Role:
    role = get_role(role_id, tenant_id, db)
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.status is not None:
        role.status = data.status
    db.flush()
    return role


def delete_role(role_id: str, tenant_id: str, db: Session) -> None:
    role = get_role(role_id, tenant_id, db)
    # 保护内置管理员角色，避免误删导致租户失控
    if role.code.startswith("tenant_admin"):
        raise ValidationException("内置管理员角色不可删除")
    db.execute(role_permission.delete().where(role_permission.c.role_id == role_id))
    db.delete(role)
    db.flush()


def set_role_permissions(
    role_id: str, permission_ids: List[str], tenant_id: str, db: Session
) -> Role:
    role = get_role(role_id, tenant_id, db)
    perms = db.query(Permission).filter(Permission.id.in_(permission_ids)).all()
    valid_ids = {p.id for p in perms}
    db.execute(role_permission.delete().where(role_permission.c.role_id == role_id))
    for pid in valid_ids:
        db.execute(role_permission.insert().values(role_id=role_id, permission_id=pid))
    db.flush()
    return role


def list_permissions(db: Session) -> List[Permission]:
    return (
        db.query(Permission)
        .order_by(Permission.resource, Permission.action)
        .all()
    )
