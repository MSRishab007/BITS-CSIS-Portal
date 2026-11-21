"""Analytics: totals and breakdowns of spend, computed in the database.

What counts as "spend":
  * Normally the invoice **bill amount** (what was actually paid).
  * When filtering by category or funding source, bill totals would include
    other items on the same invoice, so the **item amounts** are used instead.
  * Category and funding breakdowns always use item amounts, since those are
    recorded per item. Items without an amount are counted in units only;
    the page shows how many items have an amount.
"""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.purchases.filters import PERIODS, PurchaseFilter, fy_label
from apps.purchases.models import Purchase, PurchaseItem

from .charts import donut, monthly, rows

TOP_N = 8


@login_required
@require_GET
def overview(request):
    user = request.user
    f = PurchaseFilter.from_request(request, default_period="this_fy")
    invoices = Purchase.objects.filter(pk__in=f.purchases(user).values("pk"))  # no duplicate rows
    items = f.items(user)
    item_level = f.item_level

    bill_total = invoices.aggregate(t=Sum("bill_amount"))["t"] or Decimal("0")
    item_stats = items.aggregate(amount=Sum("amount"), units=Sum("quantity"), n=Count("pk"))
    item_amount = item_stats["amount"] or Decimal("0")
    item_count = item_stats["n"] or 0
    with_amount = items.filter(amount__isnull=False).count()
    invoice_count = invoices.count()
    spend = item_amount if item_level else bill_total

    # ---- monthly spend ----------------------------------------------------
    today = timezone.localdate()
    if item_level:
        bars, ticks = monthly(items, "purchase__purchase_date", "amount", f.date_from, f.date_to, today)
    else:
        bars, ticks = monthly(invoices, "purchase_date", "bill_amount", f.date_from, f.date_to, today)

    # ---- breakdowns ---------------------------------------------------------
    by_category = rows(items, "category__name", "amount", id_field="category_id")
    by_funding = rows(items, "funding_source__name", "amount", id_field="funding_source_id")
    if item_level:
        by_vendor = rows(items, "purchase__vendor__name", "amount", top_n=TOP_N)
        by_faculty = rows(items, "purchase__owner__full_name", "amount", top_n=TOP_N, id_field="purchase__owner_id")
    else:
        by_vendor = rows(invoices, "vendor__name", "bill_amount", top_n=TOP_N)
        by_faculty = rows(invoices, "owner__full_name", "bill_amount", top_n=TOP_N, id_field="owner_id")

    units_by_status = [
        {"label": PurchaseItem.Status(row["status"]).label, "status": row["status"], "units": row["u"]}
        for row in items.values("status").annotate(u=Sum("quantity")).order_by("-u")
    ]

    warranty_items = PurchaseItem.objects.visible_to(user)
    if f.owner:
        warranty_items = warranty_items.filter(purchase__owner_id=f.owner)
    expiring = (warranty_items.warranty_expiring(90)
                .select_related("purchase", "purchase__owner").order_by("warranty_end_date")[:12])

    period_title = ("All time" if not (f.date_from or f.date_to)
                    else fy_label(f.date_from) if f.period in ("this_fy", "last_fy")
                    else "Last 12 months" if f.period == "last_12m" else "Selected dates")

    return render(request, "analytics/overview.html", {
        **f.form_context(user),
        "querystring": f.querystring(),
        "period_title": period_title,
        "item_level": item_level,
        "spend": spend,
        "bill_total": bill_total,
        "item_amount": item_amount,
        "invoice_count": invoice_count,
        "avg_invoice": (bill_total / invoice_count) if invoice_count else None,
        "units": item_stats["units"] or 0,
        "item_count": item_count,
        "with_amount": with_amount,
        "monthly": bars,
        "ticks": ticks,
        "donut_category": donut(by_category),
        "donut_funding": donut(by_funding),
        "periods": PERIODS,
        "period_links": [(v, l, f.querystring(period=v)) for v, l in PERIODS if v != "custom"],
        "by_category": by_category,
        "by_funding": by_funding,
        "by_vendor": by_vendor,
        "by_faculty": by_faculty if user.can_view_all_records else None,
        "units_by_status": units_by_status,
        "expiring": expiring,
        "expiring_30": warranty_items.warranty_expiring(30).count(),
    })
