import datetime

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.catalog.models import Category, FundingSource, ItemType, Vendor
from apps.purchases.models import Purchase, PurchaseItem

DOMAIN = "pilani.bits-pilani.ac.in"


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class SearchAndShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "x", full_name="Faculty One")
        cls.f2 = User.objects.create_user(f"f2@{DOMAIN}", "x", full_name="Faculty Two")
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        vendor, _ = Vendor.get_or_create_by_name("Zebronics")
        gadgets = Category.objects.get(name="Gadgets")
        for owner, inv in ((cls.f1, "ZB-1"), (cls.f2, "ZB-2")):
            p = Purchase.objects.create(owner=owner, vendor=vendor, invoice_number=inv,
                                        purchase_date=datetime.date(2026, 5, 1), bill_amount=500)
            PurchaseItem.objects.create(purchase=p, category=gadgets, item_type=ItemType.objects.get(name="Mouse"),
                                        item_name=f"Mouse {inv}", quantity=1,
                                        funding_source=FundingSource.objects.first(), serial_numbers=f"SN-{inv}")

    def search(self, user, q):
        self.client.force_login(user)
        return [(r["group"], r["label"]) for r in self.client.get(reverse("core:search"), {"q": q}).json()["results"]]

    def test_faculty_search_only_own_records(self):
        found = self.search(self.f1, "ZB")
        self.assertIn(("Invoices", "ZB-1"), found)
        self.assertNotIn(("Invoices", "ZB-2"), found)
        self.assertEqual([r for r in self.search(self.f1, "SN-ZB-2")], [])  # someone else's serial number
        self.assertNotIn("People", {g for g, _ in self.search(self.f1, "Faculty")})

    def test_hod_search_everything_and_people(self):
        found = self.search(self.hod, "ZB")
        self.assertIn(("Invoices", "ZB-2"), found)
        self.assertIn(("People", "Faculty Two"), self.search(self.hod, "faculty two"))
        self.assertIn(("Vendors", "Zebronics"), self.search(self.hod, "zebro"))

    def test_short_query_returns_nothing(self):
        self.assertEqual(self.search(self.f1, "z"), [])

    def test_shell_has_logo_and_command_menu(self):
        self.client.force_login(self.f1)
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, "bits-logo-160.png")
        self.assertContains(r, 'x-data="cmdk"')
        self.assertContains(r, 'id="cmdk-pages"')
        self.assertNotContains(r, "/manage/people/")  # faculty don't get management pages

    def test_login_page_has_logo(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "bits-logo-480.png")

    def test_login_page_google_placeholder(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "Continue with Google")
        self.assertContains(r, "Google sign-in is coming soon")
        self.assertNotContains(r, "accounts.google.com")  # no real Google flow yet
