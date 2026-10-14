"""极简邮件发送（标准库实现，无第三方依赖）。"""

from app.core.config import config


def _send_email(to: str, subject: str, body: str) -> bool:
    """发送邮件；SMTP 未配置或发送失败时返回 False。"""
    if not config.smtp_host:
        return False

    try:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = config.email_from
        msg["To"] = to
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
        return False


def build_verification_link(token: str) -> str:
    base = config.app_frontend_base_url.rstrip("/")
    return f"{base}/verify-email?token={token}"


def send_verification_email(email: str, token: str) -> bool:
    body = (
        f"您好，\n\n"
        f"感谢注册 AI Studio。请点击以下链接验证您的邮箱并激活账号"
        f"（{config.email_verification_ttl_hours} 小时内有效）：\n"
        f"{build_verification_link(token)}\n\n"
        f"若非本人操作，请忽略本邮件。\n"
    )
    return _send_email(email, "请验证您的邮箱以激活 AI Studio 账号", body)


def build_password_reset_link(token: str) -> str:
    base = config.app_frontend_base_url.rstrip("/")
    return f"{base}/reset-password?token={token}"


def send_password_reset_email(email: str, token: str) -> bool:
    """发送密码重置邮件；不返回令牌。"""
    body = (
        f"您好，\n\n"
        f"管理员已为您的账号发起密码重置。请在 1 小时内打开以下链接设置新密码：\n"
        f"{build_password_reset_link(token)}\n\n"
        f"如果您没有发起或预期这次操作，请联系租户管理员。\n"
    )
    return _send_email(email, "重置您的 AI Studio 密码", body)
