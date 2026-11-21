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

    def test_smooth_navigation_shell(self):
        self.client.force_login(self.hod)
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, 'hx-boost="true" hx-target="#content" hx-select="#content"')
        self.assertContains(r, 'id="content"')
        self.assertContains(r, 'id="nav-links"')
        self.assertContains(r, "htmx-2.0.11.min.js")
        # sign-out and technical admin are normal page loads
        self.assertContains(r, 'class="inline" hx-boost="false"')

    def test_downloads_are_not_swapped_into_the_page(self):
        self.client.force_login(self.hod)
        for url in (reverse("purchases:list"), reverse("analytics:overview"), reverse("purchases:bulk_upload")):
            self.assertContains(self.client.get(url), 'hx-boost="false"', msg_prefix=url)

    def test_bits_colour_order_and_tagline(self):
        from pathlib import Path
        from django.conf import settings
        css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text()
        self.assertIn("--tri: linear-gradient(90deg, var(--bits-yellow) 0 33.33%, var(--bits-blue) 33.33% 66.66%, "
                      "var(--bits-red) 66.66% 100%)", css)
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "<span>innovate</span><i>·</i><span>achieve</span><i>·</i><span>lead</span>", html=False)

    def test_login_page_has_logo(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "bits-logo-480.png")

    def test_login_page_google_placeholder(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "Continue with Google")
        self.assertContains(r, "Google sign-in is coming soon")
        self.assertNotContains(r, "accounts.google.com")  # no real Google flow yet


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class ExpiredTokenTests(TestCase):
    """A sign-in form loaded before a sign-in/out elsewhere has a stale token."""

    def setUp(self):
        from django.test import Client
        self.user = User.objects.create_user(f"tara@{DOMAIN}", "Pass-word-123", full_name="Tara Iyer")
        self.client = Client(enforce_csrf_checks=True)

    def stale_login(self):
        self.client.get(reverse("accounts:login"))  # sets the CSRF cookie
        return self.client.post(reverse("accounts:login"),
                                {"username": "tara", "password": "Pass-word-123", "csrfmiddlewaretoken": "x" * 64})

    def test_stale_login_form_redirects_back_with_explanation(self):
        r = self.stale_login()
        self.assertRedirects(r, reverse("accounts:login"), fetch_redirect_response=False)
        page = self.client.get(reverse("accounts:login"))
        self.assertContains(page, "That sign-in page had expired")
        self.assertNotContains(page, "CSRF verification failed")

    def test_stale_login_when_already_signed_in_says_who(self):
        self.client.force_login(self.user)
        r = self.stale_login()
        self.assertRedirects(r, reverse("core:home"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("core:home")), "already signed in as Tara Iyer")

    def test_other_forms_get_friendly_page(self):
        self.client.force_login(self.user)
        self.client.get(reverse("core:home"))
        r = self.client.post(reverse("accounts:logout"), {"csrfmiddlewaretoken": "x" * 64})
        self.assertContains(r, "This page expired", status_code=403)

    def test_valid_login_still_works(self):
        page = self.client.get(reverse("accounts:login"))
        token = page.cookies["csrftoken"].value
        r = self.client.post(reverse("accounts:login"),
                             {"username": "tara", "password": "Pass-word-123", "csrfmiddlewaretoken": token})
        self.assertRedirects(r, reverse("core:home"))

    def test_sign_in_button_disables_on_submit(self):
        self.assertContains(self.client.get(reverse("accounts:login")), "Signing in…")
