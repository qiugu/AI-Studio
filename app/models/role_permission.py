from sqlalchemy import Table, Column, ForeignKey, String

from app.core.database import Base

role_permission = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', String(36), ForeignKey('roles.id'), primary_key=True),
    Column('permission_id', String(36), ForeignKey('permissions.id'), primary_key=True),
)