from sqlalchemy import Table, Column, BigInteger, ForeignKey

from app.core.database import Base

user_role = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', BigInteger, ForeignKey('users.id'), primary_key=True),
    Column('role_id', BigInteger, ForeignKey('roles.id'), primary_key=True),
)