from sqlalchemy import Table, Column, ForeignKey, String

from app.core.database import Base

user_role = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', String(36), ForeignKey('users.id'), primary_key=True),
    Column('role_id', String(36), ForeignKey('roles.id'), primary_key=True),
)