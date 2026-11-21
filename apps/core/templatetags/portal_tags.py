from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """{{ mydict|get_item:key }} — dictionary lookup with a variable key."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def inr(value):
    """Format a number the Indian way: 1234567.5 -> 12,34,567.50"""
    try:
        amount = f"{float(value):.2f}"
    except (TypeError, ValueError):
        return value
    whole, frac = amount.split(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}{whole}.{frac}"


@register.filter
def history_changes(record):
    """Names of fields changed in this history record compared with the previous one."""
    prev = getattr(record, "prev_record", None)
    if prev is None:
        return []
    skip = {"updated_at", "deactivated_at", "name_key"}
    return [c.field.replace("_", " ") for c in record.diff_against(prev).changes if c.field not in skip]


@register.filter
def inr_compact(value):
    """Short Indian-style amount for axes and tiles: 950 -> ₹950, 125000 -> ₹1.25L, 23400000 -> ₹2.34Cr."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e7:
        s, unit = v / 1e7, "Cr"
    elif v >= 1e5:
        s, unit = v / 1e5, "L"
    elif v >= 1e3:
        s, unit = v / 1e3, "K"
    else:
        return f"{sign}₹{v:,.0f}"
    text = f"{s:.2f}".rstrip("0").rstrip(".")
    return f"{sign}₹{text}{unit}"


@register.filter
def percent_of(value, total):
    try:
        return 0 if not total else round(float(value) * 100 / float(total), 1)
    except (TypeError, ValueError):
        return 0
