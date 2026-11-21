"""Who may manage whom.

* Admin and HoD can open the management screens.
* Only an Admin (or superuser) can create, edit or reset an Admin account,
  or give someone the Admin role.
* Nobody can deactivate themselves or change their own role here, so the
  last manager can't lock themselves out by accident.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.accounts.models import Role


def manager_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not request.user.can_manage_faculty:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def can_manage_user(actor, target) -> bool:
    if target.is_superuser or target.role == Role.ADMIN:
        return actor.is_portal_admin
    return actor.can_manage_faculty


def assignable_roles(actor):
    roles = Role.choices
    if not actor.is_portal_admin:
        roles = [(v, l) for v, l in roles if v != Role.ADMIN]
    return roles
