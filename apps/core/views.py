from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    """Lightweight check for monitoring: confirms the app and database respond."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # pragma: no cover - only reached if the DB is down
        return JsonResponse({"status": "error"}, status=503)


@require_GET
@login_required
def home(request):
    # Placeholder home page; becomes the dashboard in a later commit.
    return render(request, "core/home.html")
