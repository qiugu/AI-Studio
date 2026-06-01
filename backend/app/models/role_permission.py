from sqlalchemy import Table, Column, BigInteger, ForeignKey

from app.core.database import Base

role_permission = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', BigInteger, ForeignKey('roles.id'), primary_key=True),
    Column('permission_id', BigInteger, ForeignKey('permissions.id'), primary_key=True),
)