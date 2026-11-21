from django.conf import settings


def portal(request):
    """Make portal and department names available in every template."""
    return {
        "PORTAL_NAME": settings.PORTAL_NAME,
        "DEPARTMENT_NAME": settings.DEPARTMENT_NAME,
    }
