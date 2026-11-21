from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.purchases.models import Purchase, PurchaseItem


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
    """Dashboard: headline numbers and recent invoices (full analytics later)."""
    purchases = Purchase.objects.visible_to(request.user)
    items = PurchaseItem.objects.visible_to(request.user)
    totals = purchases.aggregate(count=Count("id"), spend=Sum("bill_amount"))
    return render(request, "core/home.html", {
        "invoice_count": totals["count"],
        "total_spend": totals["spend"] or 0,
        "item_units": items.aggregate(units=Sum("quantity"))["units"] or 0,
        "expiring": items.warranty_expiring(30).select_related("purchase")[:5],
        "expiring_count": items.warranty_expiring(30).count(),
        "recent": purchases.select_related("vendor", "owner").annotate(item_count=Count("items"))
        .order_by("-purchase_date", "-id")[:6],
    })
