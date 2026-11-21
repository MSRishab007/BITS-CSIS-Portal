"""Excel export: one row per item, with its invoice details alongside."""
import io

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.catalog.models import CustomField

HEADER_FILL = PatternFill("solid", fgColor="4F46E5")


def _cf_value(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return value


def build_items_xlsx(f, user) -> bytes:
    items = (f.items(user)
             .select_related("purchase__vendor", "purchase__owner", "purchase__created_by", "category",
                             "item_type", "funding_source", "venue")
             .order_by("-purchase__purchase_date", "purchase_id", "id"))
    inv_fields = list(CustomField.objects.filter(applies_to=CustomField.AppliesTo.PURCHASE).order_by("sort_order", "label"))
    item_fields = list(CustomField.objects.filter(applies_to=CustomField.AppliesTo.ITEM).order_by("sort_order", "label"))

    columns = [
        # (header, width, number format, getter)
        ("Invoice number", 18, None, lambda i: i.purchase.invoice_number),
        ("Vendor", 26, None, lambda i: i.purchase.vendor.name),
        ("Vendor GSTIN", 17, None, lambda i: i.purchase.vendor.gstin),
        ("Order / PO number", 16, None, lambda i: i.purchase.order_number),
        ("Purchase date", 13, "DD-MM-YYYY", lambda i: i.purchase.purchase_date),
        ("Delivery date", 13, "DD-MM-YYYY", lambda i: i.purchase.delivery_date),
        ("Bill amount (₹)", 15, "#,##0.00", lambda i: i.purchase.bill_amount),
        ("Faculty", 20, None, lambda i: i.purchase.owner.full_name),
        ("Faculty email", 28, None, lambda i: i.purchase.owner.email),
        ("Invoice remarks", 24, None, lambda i: i.purchase.remarks),
    ]
    columns += [(cf.label, 16, None, (lambda i, k=cf.key: _cf_value(i.purchase.extra.get(k)))) for cf in inv_fields]
    columns += [
        ("Category", 22, None, lambda i: i.category.name),
        ("Type", 18, None, lambda i: i.item_type.name),
        ("Item", 28, None, lambda i: i.item_name),
        ("Quantity", 9, "0", lambda i: i.quantity),
        ("Item amount (₹)", 15, "#,##0.00", lambda i: i.amount),
        ("Funding source", 20, None, lambda i: i.funding_source.name),
        ("Project / grant no.", 20, None, lambda i: i.project_number),
        ("PI name", 18, None, lambda i: i.principal_investigator),
        ("Venue", 16, None, lambda i: i.venue.name if i.venue_id else ""),
        ("Serial numbers", 22, None, lambda i: ", ".join(i.serial_number_list)),
        ("Asset tag", 13, None, lambda i: i.asset_tag),
        ("Warranty end date", 15, "DD-MM-YYYY", lambda i: i.warranty_end_date),
        ("Status", 14, None, lambda i: i.get_status_display()),
        ("Item remarks", 24, None, lambda i: i.remarks),
    ]
    columns += [(cf.label, 16, None, (lambda i, k=cf.key: _cf_value(i.extra.get(k)))) for cf in item_fields]
    columns += [
        ("Recorded on", 17, "DD-MM-YYYY HH:MM", lambda i: timezone.localtime(i.purchase.created_at).replace(tzinfo=None)),
        ("Recorded by", 20, None, lambda i: i.purchase.created_by.full_name if i.purchase.created_by_id else ""),
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Items"
    for c, (header, width, _, _) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[1].height = 30

    r = 1
    for r, item in enumerate(items.iterator(chunk_size=500), start=2):
        for c, (_, _, fmt, getter) in enumerate(columns, start=1):
            cell = ws.cell(row=r, column=c, value=getter(item))
            if fmt:
                cell.number_format = fmt
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(r, 1)}"

    # About sheet: what this file contains
    info = wb.create_sheet("About")
    rows = [("Exported", timezone.localtime().strftime("%d %b %Y, %H:%M")),
            ("Exported by", user.full_name),
            ("Rows (items)", r - 1)]
    rows += f.describe() or [("Filters", "None: all records you can see")]
    rows.append(("Note", "One row per item. Invoice columns repeat for each item on the same invoice, "
                         "so add up 'Bill amount' per invoice, not per row."))
    for i, (k, v) in enumerate(rows, start=1):
        info.cell(row=i, column=1, value=k).font = Font(bold=True)
        info.cell(row=i, column=2, value=v)
    info.column_dimensions["A"].width = 16
    info.column_dimensions["B"].width = 90

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
