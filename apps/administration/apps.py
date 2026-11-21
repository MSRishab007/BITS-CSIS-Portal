from django.apps import AppConfig


class AdministrationConfig(AppConfig):
    """Portal screens for Admin/HoD: people and lookup lists (no /admin/ needed)."""

    name = "apps.administration"
    label = "administration"
    verbose_name = "Department administration"
