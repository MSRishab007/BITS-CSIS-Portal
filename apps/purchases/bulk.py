"""Bulk upload: Excel/CSV template and importer.

One spreadsheet row = one item. Rows with the same invoice number and
vendor (and faculty member) are grouped into one invoice.

The importer validates by doing the real import inside a database
transaction, using the same model checks as the entry form:
  * preview  -> everything is checked, then the transaction is rolled back
  * confirm  -> the same run, committed only if there are no errors at all
So what the preview shows is exactly what will be saved.
"""
import csv
import datetime
import io
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from apps.accounts.backends import find_user
from apps.catalog.models import (
    Category, CustomField, FundingSource, ItemType, Vendor, Venue, normalize_vendor_name,
)

from .models import Purchase, PurchaseItem

MAX_ROWS = 2000
TEMPLATE_ROWS = 1000  # rows that get dropdowns/formatting in the template
SHEET_NAME = "Purchases"


# --------------------------------------------------------------------------
# Columns
# --------------------------------------------------------------------------
@dataclass
class Column:
    key: str            # internal name, e.g. "invoice_number" or "extra_i:rack_position"
    header: str         # text shown in the template (without " *")
    required: bool = False
    help: str = ""
    width: int = 18
    kind: str = "text"  # text | date | money | int
    level: str = "invoice"  # invoice | item | owner
    custom: CustomField | None = None

    @property
    def title(self):
        return f"{self.header} *" if self.required else self.header


def norm_header(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def build_columns(user) -> list[Column]:
    cols = []
    if user.can_view_all_records:
        cols.append(Column("owner", "Faculty email or username", level="owner", width=26,
                           help="Who the purchase belongs to. Leave blank for yourself."))
    cols += [
        Column("invoice_number", "Invoice number", True, "Same number + vendor on several rows = one invoice.", 18),
        Column("vendor", "Vendor", True, "Pick from the list or type a new vendor name.", 28),
        Column("order_number", "Order / PO number", help="Optional.", width=16),
        Column("purchase_date", "Purchase date", True, "DD-MM-YYYY", 15, "date"),
        Column("delivery_date", "Delivery date", help="DD-MM-YYYY, optional.", width=15, kind="date"),
        Column("bill_amount", "Bill amount", True, "Total on the bill in ₹, incl. tax. Same on every row of an invoice.",
               14, "money"),
        Column("invoice_remarks", "Invoice remarks", width=24),
    ]
    taken = {norm_header(c.header) for c in cols}
    for cf in CustomField.objects.active().filter(applies_to=CustomField.AppliesTo.PURCHASE):
        header = cf.label if norm_header(cf.label) not in taken else f"{cf.label} (invoice)"
        taken.add(norm_header(header))
        cols.append(Column(f"extra_p:{cf.key}", header, cf.required, cf.help_text, 18,
                           "date" if cf.field_type == "DATE" else "text", "invoice", cf))
    item_cols = [
        Column("category", "Category", True, "Choose from the list.", 22, level="item"),
        Column("item_type", "Type", True, "Must be a type of the chosen category.", 20, level="item"),
        Column("item_name", "Item name", True, "Make and model.", 28, level="item"),
        Column("quantity", "Quantity", True, "Whole number, 1 or more.", 10, "int", "item"),
        Column("amount", "Item amount", help="₹ for all units of this item. Optional.", width=13, kind="money",
               level="item"),
        Column("funding_source", "Funding source", True, "Choose from the list.", 20, level="item"),
        Column("project_number", "Project / grant no.", help="Required for Research Grant.", width=20, level="item"),
        Column("principal_investigator", "PI name", width=18, level="item"),
        Column("venue", "Venue", help="Where it's placed. Pick from the list or type a new lab/room. Optional.",
               width=18, level="item"),
        Column("serial_numbers", "Serial numbers", help="Separate several with commas.", width=22, level="item"),
        Column("asset_tag", "Asset tag", width=14, level="item"),
        Column("warranty_end_date", "Warranty end date", help="DD-MM-YYYY, optional.", width=17, kind="date",
               level="item"),
        Column("status", "Status", help="Blank = In use.", width=16, level="item"),
        Column("item_remarks", "Item remarks", width=24, level="item"),
    ]
    taken |= {norm_header(c.header) for c in item_cols}
    cols += item_cols
    for cf in CustomField.objects.active().filter(applies_to=CustomField.AppliesTo.ITEM).prefetch_related("categories"):
        header = cf.label if norm_header(cf.label) not in taken else f"{cf.label} (item)"
        taken.add(norm_header(header))
        cats = ", ".join(c.name for c in cf.categories.all())
        help_text = " ".join(filter(None, [cf.help_text, f"Only for: {cats}." if cats else ""]))
        # Required-ness can depend on category, so it's checked per row, not marked in the header.
        cols.append(Column(f"extra_i:{cf.key}", header, False, help_text, 18,
                           "date" if cf.field_type == "DATE" else "text", "item", cf))
    return cols


# Model field -> column key, to put validation errors under the right column
FIELD_TO_COLUMN = {
    "remarks": None,  # resolved per level below
    "owner": "owner", "vendor": "vendor", "invoice_number": "invoice_number", "order_number": "order_number",
    "purchase_date": "purchase_date", "delivery_date": "delivery_date", "bill_amount": "bill_amount",
    "category": "category", "item_type": "item_type", "item_name": "item_name", "quantity": "quantity",
    "amount": "amount", "funding_source": "funding_source", "project_number": "project_number",
    "principal_investigator": "principal_investigator", "venue": "venue", "serial_numbers": "serial_numbers",
    "asset_tag": "asset_tag", "warranty_end_date": "warranty_end_date", "status": "status",
}


# --------------------------------------------------------------------------
# Template
# --------------------------------------------------------------------------
REQ_FILL = PatternFill("solid", fgColor="4F46E5")
OPT_FILL = PatternFill("solid", fgColor="E5E7EB")
EXAMPLE_FILL = PatternFill("solid", fgColor="FFF7E6")


def _lookup_lists():
    return OrderedDict([
        ("Categories", [c.name for c in Category.objects.active()]),
        ("Types", sorted({t.name for t in ItemType.objects.active().filter(category__is_active=True)})),
        ("Funding sources", [f.name for f in FundingSource.objects.active()]),
        ("Venues", [v.name for v in Venue.objects.active()]),
        ("Statuses", [label for _, label in PurchaseItem.Status.choices]),
        ("Vendors", [v.name for v in Vendor.objects.active().order_by("name")]),
    ])


def _write_headers(ws, cols):
    for i, col in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=i, value=col.title)
        cell.font = Font(bold=True, color="FFFFFF" if col.required else "1F2937")
        cell.fill = REQ_FILL if col.required else OPT_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        if col.help:
            cell.comment = Comment(col.help, "Portal")
        ws.column_dimensions[get_column_letter(i)].width = col.width
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def build_template_xlsx(user) -> bytes:
    cols = build_columns(user)
    lists = _lookup_lists()
    wb = Workbook()

    # Instructions
    info = wb.active
    info.title = "Instructions"
    lines = [
        ("How to fill this template", True),
        ("1. Fill the 'Purchases' sheet: one row per item.", False),
        ("2. For an invoice with several items, repeat the invoice number, vendor, dates and bill amount on each row.", False),
        ("3. Blue columns are required. Hover over a header to see a hint.", False),
        ("4. Use the dropdowns for category, type, funding source, venue and status.", False),
        ("   Vendor and Venue have dropdowns of known names, but you can type a new one.", False),
        ("5. Dates as DD-MM-YYYY. Amounts in rupees without the ₹ sign.", False),
        ("6. Bills (PDF/images) can't go in the spreadsheet: attach them afterwards from each invoice's Edit page.", False),
        ("7. Upload the file on the Bulk upload page. You'll see a preview and any errors before anything is saved.", False),
        ("", False),
        ("See the 'Example' sheet for a filled-in sample. Don't upload the Example sheet: only 'Purchases' is read.", False),
    ]
    for r, (text, bold) in enumerate(lines, start=1):
        info.cell(row=r, column=1, value=text).font = Font(bold=bold, size=14 if bold else 11)
    info.column_dimensions["A"].width = 110

    # Data sheet
    ws = wb.create_sheet(SHEET_NAME)
    _write_headers(ws, cols)
    last = TEMPLATE_ROWS + 1

    # Hidden sheet with dropdown values
    ls = wb.create_sheet("Lists")
    ls.sheet_state = "hidden"
    list_ranges = {}
    col_idx = 1
    for name, values in lists.items():
        ls.cell(row=1, column=col_idx, value=name).font = Font(bold=True)
        for r, v in enumerate(values, start=2):
            ls.cell(row=r, column=col_idx, value=v)
        letter = get_column_letter(col_idx)
        list_ranges[name] = f"Lists!${letter}$2:${letter}${max(len(values), 1) + 1}"
        col_idx += 1
    for col in cols:  # dropdown custom fields
        if col.custom and col.custom.field_type in ("CHOICE", "BOOLEAN"):
            values = col.custom.choice_list if col.custom.field_type == "CHOICE" else ["Yes", "No"]
            ls.cell(row=1, column=col_idx, value=col.header).font = Font(bold=True)
            for r, v in enumerate(values, start=2):
                ls.cell(row=r, column=col_idx, value=v)
            letter = get_column_letter(col_idx)
            list_ranges[col.key] = f"Lists!${letter}$2:${letter}${len(values) + 1}"
            col_idx += 1

    dropdowns = {"category": "Categories", "item_type": "Types", "funding_source": "Funding sources",
                 "venue": "Venues", "status": "Statuses", "vendor": "Vendors"}
    for i, col in enumerate(cols, start=1):
        letter = get_column_letter(i)
        source = dropdowns.get(col.key) or (col.key if col.key in list_ranges else None)
        if source and source in list_ranges:
            dv = DataValidation(type="list", formula1=f"={list_ranges[source]}", allow_blank=True)
            if col.key in ("vendor", "venue"):
                dv.showErrorMessage = False  # allow typing a new vendor / venue
            else:
                dv.error = "Choose a value from the list."
                dv.errorTitle = "Not in the list"
            ws.add_data_validation(dv)
            dv.add(f"{letter}2:{letter}{last}")
        if col.kind == "date":
            for r in range(2, last + 1):
                ws.cell(row=r, column=i).number_format = "DD-MM-YYYY"
        elif col.kind == "money":
            for r in range(2, last + 1):
                ws.cell(row=r, column=i).number_format = "#,##0.00"

    # Example sheet
    ex = wb.create_sheet("Example")
    _write_headers(ex, cols)
    cats = {c.name: c for c in Category.objects.active().prefetch_related("types")}
    def first_type(cat_name, preferred):
        c = cats.get(cat_name)
        if not c:
            return ""
        names = [t.name for t in c.types.all()]
        return preferred if preferred in names else (names[0] if names else "")
    funding = lists["Funding sources"]
    grant = next((f.name for f in FundingSource.objects.active() if f.requires_project_details), funding[0] if funding else "")
    plain = next((f.name for f in FundingSource.objects.active() if not f.requires_project_details), grant)
    examples = [
        {"invoice_number": "DL/2026/0412", "vendor": "Dell India Pvt. Ltd.", "purchase_date": datetime.date(2026, 10, 14),
         "bill_amount": 214000, "category": "Computing Resources",
         "item_type": first_type("Computing Resources", "Workstation"), "item_name": "Dell Precision 3680",
         "quantity": 2, "amount": 210000, "funding_source": plain, "serial_numbers": "7XK2P34, 7XK2P35",
         "warranty_end_date": datetime.date(2029, 10, 13)},
        {"invoice_number": "DL/2026/0412", "vendor": "Dell India Pvt. Ltd.", "purchase_date": datetime.date(2026, 10, 14),
         "bill_amount": 214000, "category": "Gadgets", "item_type": first_type("Gadgets", "Keyboard"),
         "item_name": "Dell KB216 keyboard", "quantity": 2, "amount": 4000, "funding_source": plain},
        {"invoice_number": "NV-88213", "vendor": "NVIDIA Graphics Pvt Ltd", "purchase_date": datetime.date(2026, 9, 2),
         "bill_amount": 1185000, "category": "Server/GPU Resources",
         "item_type": first_type("Server/GPU Resources", "GPU"), "item_name": "NVIDIA RTX 6000 Ada", "quantity": 1,
         "amount": 1185000, "funding_source": grant, "project_number": "DST/ICPS/2025/118",
         "principal_investigator": "Dr. A. Sharma"},
    ]
    for r, row in enumerate(examples, start=2):
        for i, col in enumerate(cols, start=1):
            cell = ex.cell(row=r, column=i, value=row.get(col.key))
            cell.fill = EXAMPLE_FILL
            if col.kind == "date":
                cell.number_format = "DD-MM-YYYY"
            elif col.kind == "money":
                cell.number_format = "#,##0.00"

    wb.active = wb.index(ws)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_template_csv(user) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow([c.title for c in build_columns(user)])
    return "﻿" + buf.getvalue()  # BOM so Excel opens it as UTF-8


# --------------------------------------------------------------------------
# Reading an uploaded file
# --------------------------------------------------------------------------
class FileError(Exception):
    """The file itself can't be used (wrong type, unreadable, too big…)."""


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_file(path: str, filename: str) -> tuple[list[str], list[tuple[int, list]]]:
    """Return (headers, [(row_number, values)]) from an .xlsx or .csv file."""
    name = filename.lower()
    if name.endswith(".xlsx"):
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception:
            raise FileError("This doesn't look like a valid Excel (.xlsx) file.")
        ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
        rows = ws.iter_rows(values_only=True)
        try:
            headers = [_cell_str(h) for h in next(rows)]
        except StopIteration:
            raise FileError("The sheet is empty.")
        data = []
        for n, values in enumerate(rows, start=2):
            if n > MAX_ROWS + 1:
                raise FileError(f"Too many rows: the limit is {MAX_ROWS} per upload.")
            data.append((n, list(values)))
        wb.close()
        return headers, data
    if name.endswith(".csv"):
        raw = open(path, "rb").read()
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise FileError("Couldn't read the CSV file's text encoding. Save it as 'CSV UTF-8'.")
        reader = csv.reader(io.StringIO(text))
        try:
            headers = [h.strip() for h in next(reader)]
        except StopIteration:
            raise FileError("The file is empty.")
        data = []
        for n, values in enumerate(reader, start=2):
            if n > MAX_ROWS + 1:
                raise FileError(f"Too many rows: the limit is {MAX_ROWS} per upload.")
            data.append((n, values))
        return headers, data
    raise FileError("Upload an .xlsx or .csv file.")


# --------------------------------------------------------------------------
# Value parsing
# --------------------------------------------------------------------------
class CellError(Exception):
    pass


def parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise CellError(f"'{s}' is not a date. Use DD-MM-YYYY.")


def parse_money(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip())
    except InvalidOperation:
        raise CellError(f"'{v}' is not an amount.")
    return d.quantize(Decimal("0.01"))


def parse_int(v):
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        raise CellError(f"'{v}' is not a whole number.")
    if d != d.to_integral_value():
        raise CellError(f"'{v}' is not a whole number.")
    return int(d)


class Lookups:
    """Case-insensitive name -> object maps, loaded once per import."""

    def __init__(self):
        self.categories = {c.name.lower(): c for c in Category.objects.active()}
        self.types = {}
        for t in ItemType.objects.active().select_related("category"):
            self.types[(t.category_id, t.name.lower())] = t
        self.funding = {f.name.lower(): f for f in FundingSource.objects.active()}
        self.new_venues = []
        self.statuses = {}
        for value, label in PurchaseItem.Status.choices:
            self.statuses[value.lower()] = value
            self.statuses[label.lower()] = value

    @staticmethod
    def _get(mapping, value, what):
        obj = mapping.get(str(value).strip().lower())
        if obj is None:
            raise CellError(f"'{value}' is not a known {what}.")
        return obj

    def category(self, v):
        return self._get(self.categories, v, "category")

    def item_type(self, category, v):
        t = self.types.get((category.id, str(v).strip().lower()))
        if t is None:
            raise CellError(f"'{v}' is not a type under {category.name}.")
        return t

    def funding_source(self, v):
        return self._get(self.funding, v, "funding source")

    def venue(self, v):
        """Existing venue, or a new one (added inside the import transaction)."""
        venue, created = Venue.get_or_create_by_name(str(v))
        if created:
            self.new_venues.append(venue.name)
        return venue

    def status(self, v):
        return self._get(self.statuses, v, "status")


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------
@dataclass
class RowError:
    row: int
    column: str
    message: str


@dataclass
class ImportResult:
    errors: list[RowError] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    new_vendors: list[str] = field(default_factory=list)
    new_venues: list[str] = field(default_factory=list)
    row_count: int = 0
    committed: bool = False

    @property
    def item_count(self):
        return sum(len(i["items"]) for i in self.invoices)

    @property
    def ok(self):
        return not self.errors

    @property
    def total_amount(self):
        return sum((i["bill_amount"] or 0) for i in self.invoices)


def run_import(headers: list[str], data: list[tuple[int, list]], user, commit: bool) -> ImportResult:
    result = ImportResult()
    cols = build_columns(user)
    by_header = {norm_header(c.header): c for c in cols}

    # ---- match header row --------------------------------------------------
    index = {}  # column key -> position in row
    for pos, h in enumerate(headers):
        col = by_header.get(norm_header(h))
        if col and col.key not in index:
            index[col.key] = pos
    missing = [c.header for c in cols if c.required and c.key not in index]
    if missing:
        result.errors.append(RowError(1, "", "Missing required column(s): " + ", ".join(missing)
                                      + ". Download a fresh template."))
        return result
    col_by_key = {c.key: c for c in cols}

    def cell(values, key):
        pos = index.get(key)
        if pos is None or pos >= len(values):
            return None
        v = values[pos]
        return v.strip() if isinstance(v, str) else v

    seen = set()

    def err(row, key, message):
        """Record an error; only the first one per cell is kept.

        message=None silences a cell (e.g. Type, when the category is wrong).
        """
        header = col_by_key[key].header if key in col_by_key else ""
        if header and (row, header) in seen:
            return
        seen.add((row, header))
        if message is None:
            return
        result.errors.append(RowError(row, header, message))

    lookups = Lookups()
    invoice_keys = ("owner", "invoice_number", "vendor", "order_number", "purchase_date", "delivery_date",
                    "bill_amount", "invoice_remarks") + tuple(c.key for c in cols if c.key.startswith("extra_p:"))

    # ---- group rows into invoices ------------------------------------------
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for row_no, values in data:
        if all(_cell_str(v) == "" for v in values):
            continue  # blank row
        result.row_count += 1
        owner_raw = _cell_str(cell(values, "owner"))
        inv = _cell_str(cell(values, "invoice_number"))
        vendor_raw = _cell_str(cell(values, "vendor"))
        key = (owner_raw.lower(), normalize_vendor_name(vendor_raw), inv.lower())
        g = groups.setdefault(key, {"rows": [], "header": {}, "header_row": {}})
        g["rows"].append((row_no, values))
        for k in invoice_keys:
            v = cell(values, k)
            if _cell_str(v) == "":
                continue
            if k not in g["header"]:
                g["header"][k] = v
                g["header_row"][k] = row_no
            elif _cell_str(g["header"][k]) != _cell_str(v):
                err(row_no, k, f"Differs from row {g['header_row'][k]} for the same invoice "
                               f"('{_cell_str(g['header'][k])}' vs '{_cell_str(v)}').")

    if result.row_count == 0:
        result.errors.append(RowError(2, "", "The file has no data rows."))
        return result

    # ---- validate & save, inside one transaction ---------------------------
    with transaction.atomic():
        for g in groups.values():
            first_row = g["rows"][0][0]
            h = g["header"]
            hrow = lambda k: g["header_row"].get(k, first_row)  # noqa: E731

            # Owner
            owner = user
            owner_raw = _cell_str(h.get("owner"))
            if owner_raw:
                found = find_user(owner_raw)
                if found is None:
                    err(hrow("owner"), "owner", f"No user '{owner_raw}'.")
                    continue
                if not found.is_active:
                    err(hrow("owner"), "owner", f"{found.full_name} is deactivated.")
                    continue
                owner = found

            # Vendor (existing, or created inside this transaction)
            vendor_raw = _cell_str(h.get("vendor"))
            vendor = None
            if not normalize_vendor_name(vendor_raw):
                err(first_row, "vendor", "Vendor is required.")
            else:
                vendor, created = Vendor.get_or_create_by_name(vendor_raw, user=user)
                if created:
                    result.new_vendors.append(vendor.name)

            # Invoice values
            p = Purchase(owner=owner, vendor=vendor, created_by=user,
                         invoice_number=_cell_str(h.get("invoice_number")),
                         order_number=_cell_str(h.get("order_number")),
                         remarks=_cell_str(h.get("invoice_remarks")))
            ok = vendor is not None
            for k, parser in (("purchase_date", parse_date), ("delivery_date", parse_date),
                              ("bill_amount", parse_money)):
                try:
                    setattr(p, k, parser(h.get(k)))
                except CellError as e:
                    err(hrow(k), k, str(e))
                    ok = False
            p.extra = {c.key.split(":", 1)[1]: (h.get(c.key) if c.kind == "date" else _cell_str(h.get(c.key)))
                       for c in cols if c.key.startswith("extra_p:")}

            if ok:
                try:
                    p.full_clean()
                    p.save()
                except ValidationError as e:
                    _map_errors(e, err, hrow, level="invoice", fallback_row=first_row)
                    ok = False

            summary = {"row": first_row, "invoice_number": p.invoice_number,
                       "vendor": vendor.name if vendor else vendor_raw,
                       "vendor_new": bool(vendor and vendor.name in result.new_vendors),
                       "owner": owner.full_name, "purchase_date": p.purchase_date,
                       "bill_amount": p.bill_amount, "items": []}

            # Items
            for row_no, values in g["rows"]:
                item, item_ok = _build_item(values, cell, cols, lookups, lambda k, m, r=row_no: err(r, k, m))
                if item is None:
                    continue
                if ok:
                    item.purchase = p
                try:
                    item.full_clean(exclude=None if ok else ["purchase"])
                except ValidationError as e:
                    _map_errors(e, err, lambda k, r=row_no: r, level="item", fallback_row=row_no)
                    item_ok = False
                if ok and item_ok:
                    item.save()
                summary["items"].append({"row": row_no, "name": item.item_name, "quantity": item.quantity,
                                         "amount": item.amount,
                                         "category": item.category.name if item.category_id else "",
                                         "type": item.item_type.name if item.item_type_id else "",
                                         "funding": item.funding_source.name if item.funding_source_id else ""})
            result.invoices.append(summary)

        result.new_venues = lookups.new_venues
        if result.errors or not commit:
            transaction.set_rollback(True)
        else:
            result.committed = True

    result.errors.sort(key=lambda e: (e.row, e.column))
    return result


def _build_item(values, cell, cols, lookups, err):
    """Create an unsaved PurchaseItem from a row. Returns (item, ok)."""
    item = PurchaseItem()
    ok = True

    def parse(key, fn, *args):
        nonlocal ok
        raw = cell(values, key)
        if _cell_str(raw) == "":
            return None
        try:
            return fn(*args, raw)
        except CellError as e:
            err(key, str(e))
            ok = False
            return None

    # Blank required cells are reported by the model's own checks (full_clean).
    category = parse("category", lookups.category)
    item.category = category
    if category is not None:
        item.item_type = parse("item_type", lookups.item_type, category)
    elif _cell_str(cell(values, "category")):
        err("item_type", None)  # can't check the type until the category is fixed
    item.item_name = _cell_str(cell(values, "item_name"))
    item.quantity = parse("quantity", lambda v: parse_int(v))
    item.amount = parse("amount", lambda v: parse_money(v))
    item.funding_source = parse("funding_source", lookups.funding_source)
    item.project_number = _cell_str(cell(values, "project_number"))
    item.principal_investigator = _cell_str(cell(values, "principal_investigator"))
    item.venue = parse("venue", lookups.venue)
    serials = re.split(r"[,;\n]+", _cell_str(cell(values, "serial_numbers")))
    item.serial_numbers = "\n".join(s.strip() for s in serials if s.strip())
    item.asset_tag = _cell_str(cell(values, "asset_tag"))
    item.warranty_end_date = parse("warranty_end_date", lambda v: parse_date(v))
    item.status = parse("status", lookups.status) or PurchaseItem.Status.IN_USE
    item.remarks = _cell_str(cell(values, "item_remarks"))
    item.extra = {c.key.split(":", 1)[1]: (cell(values, c.key) if c.kind == "date" else _cell_str(cell(values, c.key)))
                  for c in cols if c.key.startswith("extra_i:")}
    return item, ok


def _map_errors(exc: ValidationError, err, row_for, level, fallback_row):
    """Send each model validation message to the right row and column."""
    for fld, messages in exc.message_dict.items():
        if fld == "remarks":
            key = "invoice_remarks" if level == "invoice" else "item_remarks"
        elif fld == "extra":
            key = ""
        else:
            key = FIELD_TO_COLUMN.get(fld, "")
        for m in messages:
            if "cannot be null" in m or "cannot be blank" in m or m == "This field is required.":
                m = "This is required."
            err(row_for(key) if key else fallback_row, key, m)
