"""Create the first platform administrator from deployment-provided credentials.

Safe to run on every deployment: an existing matching platform admin is never
modified, and a conflicting email aborts instead of escalating privileges.
"""
import logging

from app.core.config import config
from app.core.database import sessionLocal
from app.core.security import hash_password
from app.core.tenant_scope import tenant_scope_context
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger("platform_admin_bootstrap")


def bootstrap_platform_admin() -> str:
    email = config.platform_admin_email.strip().lower()
    password = config.platform_admin_password.get_secret_value()

    if not email and not password:
        return "skipped: PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD are unset"
    if not email or not password:
        raise RuntimeError("PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD must be set together")
    if len(password) < 12:
        raise RuntimeError("PLATFORM_ADMIN_PASSWORD must contain at least 12 characters")

    db = sessionLocal()
    try:
        # Bootstrap is an explicit platform maintenance operation.  It may
        # inspect the system tenant before a tenant scope exists, so state
        # that cross-tenant context rather than relying on an absent ContextVar.
        with tenant_scope_context(
            "platform-bootstrap",
            is_platform_admin=True,
            allow_cross_tenant=True,
        ):
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                if not existing.is_platform_admin:
                    raise RuntimeError(
                        "PLATFORM_ADMIN_EMAIL is already used by a non-platform account; "
                        "choose a different email or promote the account through a controlled procedure"
                    )
                return "unchanged: configured platform administrator already exists"

            tenant = db.query(Tenant).filter(
                Tenant.is_system_init.is_(True), Tenant.deleted_at.is_(None)
            ).order_by(Tenant.created_at.asc()).first()
            if tenant is None:
                tenant = Tenant(
                    name="AI-Studio 平台",
                    description="平台管理员系统归属租户",
                    plan="free",
                    max_users=1,
                    max_models=0,
                    is_system_init=True,
                )
                db.add(tenant)
                db.flush()

            user = User(
                tenant_id=tenant.id,
                email=email,
                password_hash=hash_password(password),
                nickname="平台管理员",
                status=True,
                email_verified=True,
                is_platform_admin=True,
            )
            db.add(user)
            db.flush()
            tenant.owner_id = user.id
            db.commit()
            return "created: initial platform administrator account"
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Never print email or secret values in deployment logs.
    logger.info(bootstrap_platform_admin())
