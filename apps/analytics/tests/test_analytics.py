import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import Role, User
from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor
from apps.purchases.filters import period_range
from apps.purchases.models import Purchase, PurchaseItem

DOMAIN = "pilani.bits-pilani.ac.in"


class PeriodTests(TestCase):
    def test_financial_years(self):
        nov = datetime.date(2026, 11, 21)
        self.assertEqual(period_range("this_fy", nov), (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31)))
        self.assertEqual(period_range("last_fy", nov), (datetime.date(2025, 4, 1), datetime.date(2026, 3, 31)))
        feb = datetime.date(2027, 2, 10)  # still FY 2026-27
        self.assertEqual(period_range("this_fy", feb)[0], datetime.date(2026, 4, 1))
        self.assertEqual(period_range("all", nov), (None, None))

    def test_last_12_months(self):
        self.assertEqual(period_range("last_12m", datetime.date(2026, 11, 21)),
                         (datetime.date(2025, 12, 1), datetime.date(2026, 11, 21)))
        self.assertEqual(period_range("last_12m", datetime.date(2026, 3, 5)),
                         (datetime.date(2025, 4, 1), datetime.date(2026, 3, 5)))


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class AnalyticsTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "x", full_name="Faculty One")
        cls.f2 = User.objects.create_user(f"f2@{DOMAIN}", "x", full_name="Faculty Two")
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        cls.dell, _ = Vendor.get_or_create_by_name("Dell")
        cls.hp, _ = Vendor.get_or_create_by_name("HP")
        cls.gadgets = Category.objects.get(name="Gadgets")
        cls.servers = Category.objects.get(name="Server/GPU Resources")
        cls.keyboard = ItemType.objects.get(category=cls.gadgets, name="Keyboard")
        cls.gpu = ItemType.objects.get(category=cls.servers, name="GPU")
        cls.dept = FundingSource.objects.get(name="Departmental Fund")
        cls.grant = FundingSource.objects.get(name="Research Grant")

        def buy(owner, inv, vendor, date, bill, items):
            p = Purchase.objects.create(owner=owner, vendor=vendor, invoice_number=inv, purchase_date=date,
                                        bill_amount=bill, created_by=owner)
            for cat, typ, name, qty, amount, fund in items:
                PurchaseItem.objects.create(purchase=p, category=cat, item_type=typ, item_name=name, quantity=qty,
                                            amount=amount, funding_source=fund, project_number="P1")
            return p
        # f1: one mixed invoice (keyboards + GPU) and one older invoice
        buy(cls.f1, "A1", cls.dell, datetime.date(2026, 5, 10), Decimal("110000"), [
            (cls.gadgets, cls.keyboard, "KB", 4, Decimal("10000"), cls.dept),
            (cls.servers, cls.gpu, "GPU", 1, Decimal("100000"), cls.grant)])
        buy(cls.f1, "A0", cls.hp, datetime.date(2025, 6, 1), Decimal("5000"), [
            (cls.gadgets, cls.keyboard, "KB old", 1, None, cls.dept)])
        # f2
        buy(cls.f2, "B1", cls.hp, datetime.date(2026, 7, 2), Decimal("20000"), [
            (cls.gadgets, cls.keyboard, "KB2", 2, Decimal("20000"), cls.dept)])

    def get(self, user, **params):
        self.client.force_login(user)
        with mock.patch("django.utils.timezone.localdate", return_value=datetime.date(2026, 11, 21)):
            return self.client.get(reverse("analytics:overview"), params)


class AnalyticsTests(AnalyticsTestBase):
    def test_default_is_this_financial_year(self):
        r = self.get(self.hod)
        self.assertEqual(r.context["period_title"], "FY 2026–27")
        self.assertEqual(r.context["invoice_count"], 2)  # A0 is in the previous FY
        self.assertEqual(r.context["spend"], Decimal("130000"))
        months = [m["month"] for m in r.context["monthly"]]
        self.assertEqual(months[0], datetime.date(2026, 4, 1))
        self.assertEqual(months[-1], datetime.date(2026, 11, 1))  # no future months
        may = next(m for m in r.context["monthly"] if m["month"].month == 5)
        self.assertEqual(may["value"], Decimal("110000"))

    def test_faculty_sees_only_own(self):
        r = self.get(self.f1, period="all")
        self.assertEqual(r.context["invoice_count"], 2)
        self.assertEqual(r.context["spend"], Decimal("115000"))
        self.assertIsNone(r.context["by_faculty"])
        self.assertNotContains(r, "Faculty Two")
        # can't widen the view with owner=
        r = self.get(self.f1, period="all", owner=self.f2.pk)
        self.assertEqual(r.context["invoice_count"], 2)

    def test_hod_breakdowns(self):
        r = self.get(self.hod, period="all")
        cats = {row["label"]: row["value"] for row in r.context["by_category"]}
        self.assertEqual(cats, {"Server/GPU Resources": Decimal("100000"), "Gadgets": Decimal("30000")})
        fac = {row["label"]: row["value"] for row in r.context["by_faculty"]}
        self.assertEqual(fac, {"Faculty One": Decimal("115000"), "Faculty Two": Decimal("20000")})
        self.assertEqual(r.context["by_category"][0]["pct"], 100.0)
        self.assertEqual(r.context["units"], 8)
        self.assertEqual((r.context["with_amount"], r.context["item_count"]), (3, 4))
        self.assertContains(r, "3 of 4 items have an item amount")

    def test_category_filter_uses_item_amounts(self):
        r = self.get(self.hod, period="all", category=self.gadgets.pk)
        self.assertTrue(r.context["item_level"])
        # Invoice A1's bill (110000) includes a GPU; only the keyboards count here.
        self.assertEqual(r.context["spend"], Decimal("30000"))
        self.assertContains(r, "Spend on matching items")

    def test_empty_period(self):
        r = self.get(self.hod, period="custom", **{"from": "2020-01-01", "to": "2020-12-31"})
        self.assertEqual(r.context["invoice_count"], 0)
        self.assertContains(r, "No data for these filters.")


class ExportTests(AnalyticsTestBase):
    def export(self, user, **params):
        self.client.force_login(user)
        r = self.client.get(reverse("purchases:export"), {"period": "all", **params})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        rows = list(wb["Items"].iter_rows(values_only=True))
        about = dict((a, b) for a, b in wb["About"].iter_rows(values_only=True))
        return rows[0], rows[1:], about

    def test_one_row_per_item_with_invoice_details(self):
        header, rows, about = self.export(self.hod)
        self.assertEqual(len(rows), 4)
        idx = {h: i for i, h in enumerate(header)}
        gpu = next(r for r in rows if r[idx["Item"]] == "GPU")
        self.assertEqual(gpu[idx["Invoice number"]], "A1")
        self.assertEqual(gpu[idx["Vendor"]], "Dell")
        self.assertEqual(gpu[idx["Faculty"]], "Faculty One")
        self.assertEqual(gpu[idx["Funding source"]], "Research Grant")
        self.assertEqual(about["Rows (items)"], 4)

    def test_faculty_export_only_own(self):
        _, rows, _ = self.export(self.f2)
        self.assertEqual(len(rows), 1)

    def test_filters_apply_and_are_described(self):
        header, rows, about = self.export(self.hod, category=self.servers.pk)
        self.assertEqual([r[header.index("Item")] for r in rows], ["GPU"])
        self.assertEqual(about["Category"], "Server/GPU Resources")

    def test_custom_field_columns(self):
        CustomField.objects.create(label="Rack Position", applies_to="ITEM", field_type="TEXT")
        PurchaseItem.objects.filter(item_name="GPU").update(extra={"rack_position": "R2-U14"})
        header, rows, _ = self.export(self.hod)
        gpu = next(r for r in rows if r[header.index("Item")] == "GPU")
        self.assertEqual(gpu[header.index("Rack Position")], "R2-U14")

    def test_list_page_has_export_link_with_filters(self):
        self.client.force_login(self.hod)
        r = self.client.get(reverse("purchases:list"), {"period": "all", "category": self.gadgets.pk})
        self.assertContains(r, f"export.xlsx?period=all&amp;category={self.gadgets.pk}")
