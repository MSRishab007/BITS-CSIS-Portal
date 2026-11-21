"""Analytics: totals and breakdowns of spend, computed in the database.

What counts as "spend":
  * Normally the invoice **bill amount** (what was actually paid).
  * When filtering by category or funding source, bill totals would include
    other items on the same invoice, so the **item amounts** are used instead.
  * Category and funding breakdowns always use item amounts, since those are
    recorded per item. Items without an amount are counted in units only;
    the page shows how many items have an amount.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.purchases.filters import PurchaseFilter, fy_label
from apps.purchases.models import Purchase, PurchaseItem

TOP_N = 8


def _rows(qs, label_field, amount_field, top_n=None, link_param=None, id_field=None):
    """[{label, value, units/count, id}] sorted by value, optionally top N + 'Other'."""
    values = [label_field, id_field] if id_field else [label_field]
    data = list(qs.values(*values).annotate(value=Sum(amount_field), n=Count("pk", distinct=True))
                .order_by("-value", label_field))
    rows = [{"label": d[label_field] or "—", "value": d["value"] or Decimal("0"), "n": d["n"],
             "id": d.get(id_field) if id_field else None} for d in data]
    if top_n and len(rows) > top_n:
        rest = rows[top_n:]
        rows = rows[:top_n] + [{"label": f"Other ({len(rest)})", "value": sum(r["value"] for r in rest),
                                "n": sum(r["n"] for r in rest), "id": None, "other": True}]
    top = max((r["value"] for r in rows), default=0) or 1
    for r in rows:
        r["pct"] = round(float(r["value"]) * 100 / float(top), 2)
    return rows


def _nice_ceiling(v: float) -> float:
    """Round up to 1, 2, 2.5 or 5 × 10^n so axis labels are tidy."""
    if v <= 0:
        return 1
    exp = 10 ** (len(str(int(v))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if v <= step * exp:
            return step * exp
    return 10 * exp


def _months(start: datetime.date, end: datetime.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield datetime.date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


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
    if item_level:
        monthly_qs = items.annotate(month=TruncMonth("purchase__purchase_date")).values("month").annotate(v=Sum("amount"))
    else:
        monthly_qs = invoices.annotate(month=TruncMonth("purchase_date")).values("month").annotate(v=Sum("bill_amount"))
    by_month = {row["month"]: row["v"] or Decimal("0") for row in monthly_qs}
    today = timezone.localdate()
    months = []
    if by_month or f.date_from:
        start = f.date_from or min(by_month)
        end = min(f.date_to or today, today)  # no empty future months
        months = list(_months(start, end))[-36:]  # at most 3 years of bars
    month_max = _nice_ceiling(float(max(by_month.values(), default=0)))
    monthly = [{"month": m, "value": by_month.get(m, Decimal("0")),
                "pct": round(float(by_month.get(m, 0)) * 100 / month_max, 2)} for m in months]
    ticks = [month_max * i / 4 for i in range(4, -1, -1)]

    # ---- breakdowns ---------------------------------------------------------
    by_category = _rows(items, "category__name", "amount", id_field="category_id")
    by_funding = _rows(items, "funding_source__name", "amount", id_field="funding_source_id")
    if item_level:
        by_vendor = _rows(items, "purchase__vendor__name", "amount", top_n=TOP_N)
        by_faculty = _rows(items, "purchase__owner__full_name", "amount", top_n=TOP_N, id_field="purchase__owner_id")
    else:
        by_vendor = _rows(invoices, "vendor__name", "bill_amount", top_n=TOP_N)
        by_faculty = _rows(invoices, "owner__full_name", "bill_amount", top_n=TOP_N, id_field="owner_id")

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
        "invoice_count": invoice_count,
        "avg_invoice": (bill_total / invoice_count) if invoice_count else None,
        "units": item_stats["units"] or 0,
        "item_count": item_count,
        "with_amount": with_amount,
        "monthly": monthly,
        "ticks": ticks,
        "by_category": by_category,
        "by_funding": by_funding,
        "by_vendor": by_vendor,
        "by_faculty": by_faculty if user.can_view_all_records else None,
        "units_by_status": units_by_status,
        "expiring": expiring,
        "expiring_30": warranty_items.warranty_expiring(30).count(),
    })
