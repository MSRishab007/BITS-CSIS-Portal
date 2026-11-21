"""Chart data helpers shared by the analytics page and the dashboard."""
import datetime
import math
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth

DONUT_RADIUS = 70
DONUT_SLOTS = 4  # brand hues validated together for colour-blind safety; the rest folds into "Other"


def rows(qs, label_field, amount_field, top_n=None, id_field=None):
    """[{label, value, n, pct, id}] sorted by value, optionally top N + 'Other'."""
    values = [label_field, id_field] if id_field else [label_field]
    data = list(qs.values(*values).annotate(value=Sum(amount_field), n=Count("pk", distinct=True))
                .order_by("-value", label_field))
    out = [{"label": d[label_field] or "—", "value": d["value"] or Decimal("0"), "n": d["n"],
            "id": d.get(id_field) if id_field else None} for d in data]
    if top_n and len(out) > top_n:
        rest = out[top_n:]
        out = out[:top_n] + [{"label": f"Other ({len(rest)})", "value": sum(r["value"] for r in rest),
                              "n": sum(r["n"] for r in rest), "id": None, "other": True}]
    top = max((r["value"] for r in out), default=0) or 1
    for r in out:
        r["pct"] = round(float(r["value"]) * 100 / float(top), 2)
    return out


def donut(data):
    """Turn rows into SVG donut segments.

    Up to 4 slices get the BITS hues (in a fixed order, so a colour always
    means the same rank on screen); anything beyond folds into a grey 'Other'.
    Slices with no amount are left out; returns [] if there's nothing to draw.
    """
    data = [r for r in data if r["value"] and r["value"] > 0]
    total = sum(float(r["value"]) for r in data)
    if not total:
        return []
    if len(data) > DONUT_SLOTS + 1:
        head, rest = data[:DONUT_SLOTS], data[DONUT_SLOTS:]
        data = head + [{"label": f"Other ({len(rest)})", "value": sum(r["value"] for r in rest),
                        "n": sum(r["n"] for r in rest), "id": None, "other": True}]
    circumference = 2 * math.pi * DONUT_RADIUS
    gap = 2.0 if len(data) > 1 else 0
    segs, offset = [], 0.0
    for i, r in enumerate(data):
        share = float(r["value"]) / total
        length = share * circumference
        segs.append({
            **r,
            "share": round(share * 100, 1),
            "len": round(max(length - gap, 0.5), 2),
            "offset": round(-offset, 2),
            "color": "var(--viz-other)" if (r.get("other") or i >= DONUT_SLOTS) else f"var(--donut-{i + 1})",
            "i": i,
        })
        offset += length
    return segs


def nice_ceiling(v: float) -> float:
    """Round up to 1, 2, 2.5 or 5 × 10^n so axis labels are tidy."""
    if v <= 0:
        return 1
    exp = 10 ** (len(str(int(v))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if v <= step * exp:
            return step * exp
    return 10 * exp


def month_starts(start: datetime.date, end: datetime.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield datetime.date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def monthly(qs, date_field, amount_field, date_from, date_to, today, max_months=36):
    """({month: value}, bars, ticks) for a vertical monthly chart."""
    by_month = {r["month"]: r["v"] or Decimal("0")
                for r in qs.annotate(month=TruncMonth(date_field)).values("month").annotate(v=Sum(amount_field))}
    months = []
    if by_month or date_from:
        start = date_from or min(by_month)
        end = min(date_to or today, today)
        months = list(month_starts(start, end))[-max_months:]
    top = nice_ceiling(float(max(by_month.values(), default=0)))
    bars = [{"month": m, "value": by_month.get(m, Decimal("0")),
             "pct": round(float(by_month.get(m, 0)) * 100 / top, 2)} for m in months]
    ticks = [top * i / 4 for i in range(4, -1, -1)]
    return bars, ticks
