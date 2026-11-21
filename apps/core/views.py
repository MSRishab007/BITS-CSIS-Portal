from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.purchases.models import Purchase, PurchaseItem


def csrf_failure(request, reason=""):
    """Friendly handling of an expired form token (instead of Django's 403 page).

    Happens when a page was loaded before someone signed in/out in another tab
    (the token changes at every sign-in/out), after pressing Back, or on a
    double-submitted form.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    from django.urls import reverse

    login_url = reverse("accounts:login")
    if request.path == login_url:
        if request.user.is_authenticated:
            messages.info(request, f"You're already signed in as {request.user.full_name} in this browser. "
                                   "To use another account, sign out first or open a private window.")
            return redirect("core:home")
        messages.info(request, "That sign-in page had expired (you may have signed in or out in another tab). "
                               "Please sign in again.")
        return redirect(login_url)
    return render(request, "403_csrf.html", status=403)


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
    """Dashboard: this financial year at a glance."""
    from apps.analytics.charts import donut, monthly, rows
    from apps.purchases.filters import fy_label, period_range

    user = request.user
    today = timezone.localdate()
    fy_start, fy_end = period_range("this_fy", today)
    purchases = Purchase.objects.visible_to(user)
    items = PurchaseItem.objects.visible_to(user)
    fy_purchases = purchases.filter(purchase_date__gte=fy_start, purchase_date__lte=fy_end)
    fy_items = items.filter(purchase__in=fy_purchases.values("pk"))

    totals = fy_purchases.aggregate(count=Count("id"), spend=Sum("bill_amount"))
    bars, ticks = monthly(fy_purchases, "purchase_date", "bill_amount", fy_start, fy_end, today)
    by_category = rows(fy_items, "category__name", "amount", id_field="category_id")
    invoice_count = totals["count"] or 0
    spend = totals["spend"] or 0
    return render(request, "core/home.html", {
        "fy_label": fy_label(fy_start),
        "spend": spend,
        "invoice_count": invoice_count,
        "avg_invoice": (spend / invoice_count) if invoice_count else None,
        "units": fy_items.aggregate(u=Sum("quantity"))["u"] or 0,
        "item_count": fy_items.count(),
        "item_amount": fy_items.aggregate(a=Sum("amount"))["a"] or 0,
        "monthly": bars,
        "ticks": ticks,
        "by_category": by_category,
        "donut_category": donut(by_category),
        "expiring": items.warranty_expiring(60).select_related("purchase").order_by("warranty_end_date")[:5],
        "expiring_30": items.warranty_expiring(30).count(),
        "recent": purchases.select_related("vendor", "owner").annotate(item_count=Count("items"))
        .order_by("-created_at")[:6],
        "querystring": "period=this_fy",
    })


@require_GET
@login_required
def search_api(request):
    """Results for the Ctrl+K command menu. Respects who can see what."""
    from django.db.models import Q
    from django.urls import reverse

    from apps.accounts.models import User
    from apps.catalog.models import Vendor
    from apps.core.templatetags.portal_tags import inr

    q = request.GET.get("q", "").strip()
    results = []
    if len(q) < 2:
        return JsonResponse({"results": results})
    user = request.user

    invoices = (Purchase.objects.visible_to(user)
                .filter(Q(invoice_number__icontains=q) | Q(order_number__icontains=q) | Q(vendor__name__icontains=q))
                .select_related("vendor").order_by("-purchase_date")[:6])
    for p in invoices:
        results.append({"group": "Invoices", "icon": "receipt", "label": p.invoice_number,
                        "sub": f"{p.vendor.name} · {p.purchase_date:%d %b %Y} · ₹{inr(p.bill_amount)}",
                        "url": reverse("purchases:detail", args=[p.pk])})

    items = (PurchaseItem.objects.visible_to(user)
             .filter(Q(item_name__icontains=q) | Q(serial_numbers__icontains=q) | Q(asset_tag__icontains=q))
             .select_related("purchase").order_by("-purchase__purchase_date")[:6])
    for it in items:
        results.append({"group": "Items", "icon": "box", "label": it.item_name,
                        "sub": f"{it.purchase.invoice_number} · ×{it.quantity}",
                        "url": reverse("purchases:detail", args=[it.purchase_id])})

    vendor_url = reverse("purchases:list")
    for v in Vendor.objects.active().filter(name__icontains=q).order_by("name")[:4]:
        results.append({"group": "Vendors", "icon": "list", "label": v.name, "sub": "Show purchases",
                        "url": f"{vendor_url}?period=all&q={v.name}"})

    if user.can_manage_faculty:
        people = User.objects.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q))[:4]
        for u in people:
            results.append({"group": "People", "icon": "users", "label": u.full_name,
                            "sub": f"{u.get_role_display()} · {u.username}",
                            "url": reverse("administration:person_edit", args=[u.pk])})
    return JsonResponse({"results": results})
