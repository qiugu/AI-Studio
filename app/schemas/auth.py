from pydantic import BaseModel, Field
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


class LogoutForm(BaseModel):
    refresh_token: Optional[str] = None


class VerifyEmailForm(BaseModel):
    token: str


class ResendVerifyForm(BaseModel):
    email: str


class ChangePasswordForm(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)
