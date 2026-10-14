"""Second-factor style confirmation for high-risk tenant mutations."""

from app.core.config import config
from app.core.exceptions import ForbiddenException
from app.core.security import verify_password
from app.models.user import User


def require_current_password(
    actor: User,
    current_password: str | None,
    operation: str,
) -> None:
    """Require a fresh password confirmation before a sensitive mutation.

    The switch is intentionally server-side so deployments can temporarily
    phase the policy in during migration. Missing, malformed, or incorrect
    credentials always fail closed while the policy is enabled.
    """
    if not config.require_reauth_for_sensitive_actions:
        return
    try:
        valid = bool(current_password) and verify_password(
            current_password, actor.password_hash
        )
    except Exception:
        valid = False
    if not valid:
        raise ForbiddenException("reauthentication", operation)
