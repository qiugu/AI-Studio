import pytest

from app.core.exceptions import ForbiddenException
from app.core.security import hash_password
from app.core.reauthentication import require_current_password
from app.models.user import User


def test_current_password_confirmation_accepts_the_authenticated_password():
    actor = User(
        id="reauth-user",
        tenant_id="reauth-tenant",
        email="reauth@example.com",
        password_hash=hash_password("correct-password"),
    )

    assert require_current_password(actor, "correct-password", "role_update") is None


@pytest.mark.parametrize("password", [None, "", "wrong-password"])
def test_current_password_confirmation_fails_closed(password):
    actor = User(
        id="reauth-user",
        tenant_id="reauth-tenant",
        email="reauth@example.com",
        password_hash=hash_password("correct-password"),
    )

    with pytest.raises(ForbiddenException):
        require_current_password(actor, password, "role_update")
