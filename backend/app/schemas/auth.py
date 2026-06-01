from pydantic import BaseModel
from typing import Optional


class LoginForm(BaseModel):
    email: str
    password: str


class RegisterForm(BaseModel):
    email: str
    nickname: Optional[str] = None
    password: str
    password_repeat: str


class RefreshForm(BaseModel):
    refresh_token: str
