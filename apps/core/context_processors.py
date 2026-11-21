from django.conf import settings
from django.urls import reverse


def portal(request):
    """Portal names everywhere, plus the command-menu page list for signed-in users."""
    context = {
        "PORTAL_NAME": settings.PORTAL_NAME,
        "DEPARTMENT_NAME": settings.DEPARTMENT_NAME,
        "DEPARTMENT_SHORT": getattr(settings, "DEPARTMENT_SHORT", ""),
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        pages = [
            {"label": "Dashboard", "url": reverse("core:home"), "icon": "home", "keywords": "home"},
            {"label": "New purchase", "url": reverse("purchases:create"), "icon": "plus", "keywords": "add invoice record"},
            {"label": "All purchases" if user.can_view_all_records else "My purchases", "url": reverse("purchases:list"),
             "icon": "list", "keywords": "invoices list"},
            {"label": "Analytics", "url": reverse("analytics:overview"), "icon": "chart", "keywords": "charts reports spend"},
            {"label": "Bulk upload", "url": reverse("purchases:bulk_upload"), "icon": "file", "keywords": "excel import csv"},
            {"label": "Change password", "url": reverse("accounts:password_change"), "icon": "key", "keywords": "password"},
        ]
        if user.can_manage_faculty:
            pages += [
                {"label": "People", "url": reverse("administration:people"), "icon": "users", "keywords": "faculty users"},
                {"label": "Add person", "url": reverse("administration:person_add"), "icon": "plus", "keywords": "faculty user new"},
                {"label": "Categories & types", "url": reverse("administration:lookups", args=["categories"]),
                 "icon": "settings", "keywords": "lists"},
                {"label": "Vendors", "url": reverse("administration:lookups", args=["vendors"]), "icon": "settings",
                 "keywords": "lists"},
                {"label": "Custom fields", "url": reverse("administration:lookups", args=["fields"]), "icon": "settings",
                 "keywords": "lists"},
            ]
        context["CMDK_PAGES"] = pages
    return context
