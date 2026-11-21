"""Filters shared by the purchase list, Excel export and analytics.

All three read the same query-string parameters, so a filtered view can be
exported, or analysed, exactly as it is shown:

  q         search text (invoice, PO, vendor, item, serial no., faculty)
  category  category id         funding   funding source id
  owner     faculty id (Admin/HoD only)
  period    this_fy | last_fy | last_12m | all | custom
  from, to  YYYY-MM-DD (used when period is custom, or set directly)
"""
import datetime
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Category, FundingSource

from .models import Purchase, PurchaseItem

PERIODS = [
    ("this_fy", "This financial year"),
    ("last_fy", "Last financial year"),
    ("last_12m", "Last 12 months"),
    ("all", "All time"),
    ("custom", "Custom dates"),
]


def financial_year_start(day: datetime.date) -> datetime.date:
    """Indian financial year starts on 1 April."""
    return datetime.date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def fy_label(start: datetime.date) -> str:
    return f"FY {start.year}–{str(start.year + 1)[-2:]}"


def period_range(period: str, today: datetime.date | None = None):
    today = today or timezone.localdate()
    if period == "this_fy":
        start = financial_year_start(today)
        return start, datetime.date(start.year + 1, 3, 31)
    if period == "last_fy":
        this_start = financial_year_start(today)
        start = this_start.replace(year=this_start.year - 1)
        return start, datetime.date(start.year + 1, 3, 31)
    if period == "last_12m":
        # From the 1st of the month 11 months ago, through today (12 calendar months).
        y, m = today.year, today.month - 11
        if m <= 0:
            m += 12
            y -= 1
        return datetime.date(y, m, 1), today
    return None, None


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass
class PurchaseFilter:
    q: str = ""
    category: int | None = None
    funding: int | None = None
    owner: int | None = None
    period: str = "all"
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    errors: list = field(default_factory=list)

    @classmethod
    def from_request(cls, request, default_period="all"):
        g = request.GET
        f = cls(q=g.get("q", "").strip())
        for name in ("category", "funding"):
            v = g.get(name, "")
            if v.isdigit():
                setattr(f, name, int(v))
        if request.user.can_view_all_records and g.get("owner", "").isdigit():
            f.owner = int(g["owner"])
        f.period = g.get("period") or default_period
        if f.period not in dict(PERIODS):
            f.period = default_period
        if g.get("from") or g.get("to"):
            if "period" not in g:
                f.period = "custom"
        if f.period == "custom":
            f.date_from, f.date_to = _parse_date(g.get("from")), _parse_date(g.get("to"))
        else:
            f.date_from, f.date_to = period_range(f.period)
        return f

    # ---- applying -----------------------------------------------------------
    def purchases(self, user):
        qs = Purchase.objects.visible_to(user)
        if self.q:
            qs = qs.filter(Q(invoice_number__icontains=self.q) | Q(order_number__icontains=self.q)
                           | Q(vendor__name__icontains=self.q) | Q(items__item_name__icontains=self.q)
                           | Q(items__serial_numbers__icontains=self.q) | Q(owner__full_name__icontains=self.q))
        if self.category:
            qs = qs.filter(items__category_id=self.category)
        if self.funding:
            qs = qs.filter(items__funding_source_id=self.funding)
        if self.owner:
            qs = qs.filter(owner_id=self.owner)
        if self.date_from:
            qs = qs.filter(purchase_date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(purchase_date__lte=self.date_to)
        if self.q or self.category or self.funding:
            qs = qs.distinct()
        return qs

    def items(self, user):
        """Items on matching invoices; category/funding filters apply per item."""
        qs = PurchaseItem.objects.visible_to(user).filter(
            purchase__in=self.purchases(user).values("pk"))
        if self.category:
            qs = qs.filter(category_id=self.category)
        if self.funding:
            qs = qs.filter(funding_source_id=self.funding)
        return qs

    # ---- describing -----------------------------------------------------------
    @property
    def item_level(self) -> bool:
        """True when filtering by item properties (so bill totals would overstate)."""
        return bool(self.category or self.funding)

    @property
    def is_filtered(self):
        return bool(self.q or self.category or self.funding or self.owner or self.date_from or self.date_to)

    def describe(self) -> list[tuple[str, str]]:
        """Human-readable list of active filters (for exports and headings)."""
        out = []
        if self.date_from or self.date_to:
            label = dict(PERIODS).get(self.period, "Dates")
            if self.period in ("this_fy", "last_fy") and self.date_from:
                label = fy_label(self.date_from)
            rng = f"{self.date_from:%d %b %Y}" if self.date_from else "…"
            rng += f" – {self.date_to:%d %b %Y}" if self.date_to else " onwards"
            out.append(("Period", f"{label} ({rng})" if self.period != "custom" else rng))
        if self.category:
            out.append(("Category", Category.objects.filter(pk=self.category).values_list("name", flat=True).first() or "?"))
        if self.funding:
            out.append(("Funding", FundingSource.objects.filter(pk=self.funding).values_list("name", flat=True).first() or "?"))
        if self.owner:
            out.append(("Faculty", get_user_model().objects.filter(pk=self.owner)
                        .values_list("full_name", flat=True).first() or "?"))
        if self.q:
            out.append(("Search", self.q))
        return out

    def querystring(self) -> str:
        from urllib.parse import urlencode
        params = {"period": self.period}
        if self.period == "custom":
            if self.date_from:
                params["from"] = self.date_from.isoformat()
            if self.date_to:
                params["to"] = self.date_to.isoformat()
        for k in ("q", "category", "funding", "owner"):
            v = getattr(self, k)
            if v:
                params[k] = v
        return urlencode(params)

    def form_context(self, user):
        return {
            "f": self,
            "periods": PERIODS,
            "categories": Category.objects.active(),
            "funding_sources": FundingSource.objects.active(),
            "owners": get_user_model().objects.filter(purchases__isnull=False).distinct().order_by("full_name")
            if user.can_view_all_records else None,
        }
