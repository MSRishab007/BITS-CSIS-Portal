import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.catalog.models import Category, FundingSource, ItemType, Vendor
from apps.purchases.models import Purchase, PurchaseItem
from apps.purchases.validators import validate_bill_file

DOMAIN = "pilani.bits-pilani.ac.in"


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class PurchaseTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "x", full_name="Faculty One")
        cls.f2 = User.objects.create_user(f"f2@{DOMAIN}", "x", full_name="Faculty Two")
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        cls.vendor, _ = Vendor.get_or_create_by_name("Dell India Pvt Ltd")
        cls.gadgets = Category.objects.get(name="Gadgets")
        cls.keyboard = ItemType.objects.get(category=cls.gadgets, name="Keyboard")
        cls.gpu = ItemType.objects.get(name="GPU")
        cls.dept_fund = FundingSource.objects.get(name="Departmental Fund")
        cls.grant = FundingSource.objects.get(name="Research Grant")

    def purchase(self, owner, invoice="INV-1", **kw):
        data = dict(owner=owner, vendor=self.vendor, invoice_number=invoice,
                    purchase_date=datetime.date(2026, 1, 10), bill_amount=Decimal("1500.00"))
        data.update(kw)
        p = Purchase(**data)
        p.full_clean()
        p.save()
        return p

    def item(self, purchase, **kw):
        data = dict(purchase=purchase, category=self.gadgets, item_type=self.keyboard,
                    item_name="Logitech K120", quantity=2, funding_source=self.dept_fund)
        data.update(kw)
        i = PurchaseItem(**data)
        i.full_clean()
        i.save()
        return i


class VisibilityTests(PurchaseTestBase):
    def test_faculty_sees_only_own_hod_sees_all(self):
        p1 = self.purchase(self.f1, "A-1")
        p2 = self.purchase(self.f2, "A-2")
        self.assertEqual(list(Purchase.objects.visible_to(self.f1)), [p1])
        self.assertEqual(set(Purchase.objects.visible_to(self.hod)), {p1, p2})
        self.item(p1)
        self.item(p2)
        self.assertEqual(PurchaseItem.objects.visible_to(self.f2).count(), 1)
        self.assertEqual(PurchaseItem.objects.visible_to(self.hod).count(), 2)

    def test_owned_by_is_own_only_even_for_hod(self):
        self.purchase(self.f1, "A-1")
        self.assertEqual(Purchase.objects.owned_by(self.hod).count(), 0)


class PurchaseValidationTests(PurchaseTestBase):
    def test_duplicate_invoice_same_vendor_case_insensitive(self):
        self.purchase(self.f1, "inv-001")
        with self.assertRaisesMessage(ValidationError, "already recorded by Faculty One"):
            self.purchase(self.f2, "INV-001 ")
        with self.assertRaisesMessage(ValidationError, "already recorded by you"):
            self.purchase(self.f1, "INV-001")

    def test_same_invoice_number_other_vendor_ok(self):
        self.purchase(self.f1, "INV-9")
        other, _ = Vendor.get_or_create_by_name("Amazon")
        self.purchase(self.f1, "INV-9", vendor=other)

    def test_dates(self):
        future = timezone.localdate() + datetime.timedelta(days=2)
        with self.assertRaisesMessage(ValidationError, "can't be in the future"):
            self.purchase(self.f1, purchase_date=future)
        with self.assertRaisesMessage(ValidationError, "before the purchase date"):
            self.purchase(self.f1, delivery_date=datetime.date(2026, 1, 1))

    def test_negative_amount(self):
        with self.assertRaises(ValidationError):
            self.purchase(self.f1, bill_amount=Decimal("-1"))


class ItemValidationTests(PurchaseTestBase):
    def test_type_must_belong_to_category(self):
        p = self.purchase(self.f1)
        with self.assertRaisesMessage(ValidationError, "'GPU' is not a type under Gadgets"):
            self.item(p, item_type=self.gpu)

    def test_research_grant_needs_project_number(self):
        p = self.purchase(self.f1)
        with self.assertRaisesMessage(ValidationError, "Project / grant number is required"):
            self.item(p, funding_source=self.grant)
        self.item(p, funding_source=self.grant, project_number="DST/2026/42", principal_investigator="Dr X")

    def test_warranty_before_purchase(self):
        p = self.purchase(self.f1)
        with self.assertRaises(ValidationError):
            self.item(p, warranty_end_date=datetime.date(2025, 1, 1))

    def test_warranty_expiring(self):
        p = self.purchase(self.f1)
        soon = timezone.localdate() + datetime.timedelta(days=10)
        later = timezone.localdate() + datetime.timedelta(days=100)
        a = self.item(p, warranty_end_date=soon)
        self.item(p, warranty_end_date=later)
        self.assertEqual(list(PurchaseItem.objects.warranty_expiring(30)), [a])

    def test_items_total(self):
        p = self.purchase(self.f1)
        self.item(p, amount=Decimal("500"))
        self.item(p, amount=Decimal("250.50"))
        self.item(p)  # no amount
        self.assertEqual(p.items_total, Decimal("750.50"))


class HistoryTests(PurchaseTestBase):
    def test_changes_are_recorded(self):
        p = self.purchase(self.f1)
        p.bill_amount = Decimal("2000")
        p.save()
        history = list(p.history.all())
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].bill_amount, Decimal("2000"))
        self.assertEqual(history[1].bill_amount, Decimal("1500"))
        delta = history[0].diff_against(history[1])
        self.assertEqual([c.field for c in delta.changes], ["bill_amount"])


class BillFileTests(TestCase):
    def test_accepts_real_pdf_and_png(self):
        validate_bill_file(SimpleUploadedFile("bill.pdf", b"%PDF-1.7 rest"))
        validate_bill_file(SimpleUploadedFile("bill.PNG", b"\x89PNG\r\n\x1a\n" + b"0" * 20))

    def test_rejects_wrong_extension_and_fake_content(self):
        with self.assertRaisesMessage(ValidationError, "Upload a PDF"):
            validate_bill_file(SimpleUploadedFile("bill.exe", b"MZ..."))
        with self.assertRaisesMessage(ValidationError, "don't match"):
            validate_bill_file(SimpleUploadedFile("bill.pdf", b"MZ this is an exe"))
