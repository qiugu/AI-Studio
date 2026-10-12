"""极简邮件发送（标准库实现，无第三方依赖）。

仅用于发送邮箱验证邮件。SMTP 未配置时 ``send_verification_email`` 直接返回
``False``，由调用方走开发态回退（在接口响应中返回 token）。发送失败不抛异常，
避免因邮件服务异常阻断注册主流程。
"""
from typing import Optional

from app.core.config import config


def build_verification_link(token: str) -> str:
    base = config.app_frontend_base_url.rstrip("/")
    return f"{base}/verify-email?token={token}"


def send_verification_email(email: str, token: str) -> bool:
    """发送验证邮件。SMTP 未配置或发送失败返回 False。"""
    if not config.smtp_host:
        return False

    link = build_verification_link(token)
    subject = "请验证您的邮箱以激活 AI Studio 账号"
    body = (
        f"您好，\n\n"
        f"感谢注册 AI Studio。请点击以下链接验证邮箱并激活账号"
        f"（{config.email_verification_ttl_hours} 小时内有效）：\n"
        f"{link}\n\n"
        f"若非本人操作，请忽略本邮件。\n"
    )

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = config.email_from
        msg["To"] = email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as server:
            if config.smtp_use_tls:
                server.starttls()
            user = config.smtp_user
            password = config.smtp_password.get_secret_value()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception:
        # 邮件发送失败不应阻断注册流程
        return False
