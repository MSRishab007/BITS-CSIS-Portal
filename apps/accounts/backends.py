from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


def find_user(identifier: str):
    """Look a user up by email (if it contains '@') or by username.

    Case-insensitive. Returns None when there is no match.
    """
    identifier = (identifier or "").strip().lower()
    if not identifier:
        return None
    field = "email" if "@" in identifier else "username"
    try:
        return UserModel.objects.get(**{field: identifier})
    except UserModel.DoesNotExist:
        return None


class EmailOrUsernameBackend(ModelBackend):
    """Sign in with either the institute email or the short username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        user = find_user(username)
        if user is None:
            # Hash anyway so a wrong username takes as long as a wrong
            # password (stops attackers learning which accounts exist).
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


def axes_username(request, credentials):
    """Key used by django-axes to count failed attempts.

    Email and username of the same person count together, so 5 wrong
    attempts lock the account whichever way someone tries to sign in.
    """
    raw = (credentials or {}).get("username") or request.POST.get("username", "")
    user = find_user(raw)
    return user.email if user else (raw or "").strip().lower()
