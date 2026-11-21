import re

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor

DOMAIN = "pilani.bits-pilani.ac.in"
PASSWORD_RE = re.compile(r'class="mono" style="font-size:1rem;letter-spacing:.5px">([A-Za-z0-9-]+)<')


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class AdminTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(f"admin@{DOMAIN}", "x", full_name="Office Admin", role=Role.ADMIN)
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "Old-pass-12345", full_name="Faculty One")


class AccessTests(AdminTestBase):
    def test_faculty_cannot_open_management(self):
        self.client.force_login(self.f1)
        for url in (reverse("administration:people"), reverse("administration:person_add"),
                    reverse("administration:lookups", args=["categories"])):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_hod_and_admin_can(self):
        for u in (self.hod, self.admin):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("administration:people")).status_code, 200)
            for kind in ("categories", "funding", "venues", "vendors", "fields"):
                self.assertEqual(self.client.get(reverse("administration:lookups", args=[kind])).status_code, 200)

    def test_sidebar_link_only_for_managers(self):
        self.client.force_login(self.f1)
        self.assertNotContains(self.client.get(reverse("core:home")), "Lists &amp; fields")
        self.client.force_login(self.hod)
        self.assertContains(self.client.get(reverse("core:home")), "Lists &amp; fields")


class PeopleTests(AdminTestBase):
    def test_hod_adds_faculty_with_generated_password(self):
        self.client.force_login(self.hod)
        r = self.client.post(reverse("administration:person_add"), {
            "full_name": "New Prof", "email": f"New.Prof@{DOMAIN}", "username": "", "role": Role.FACULTY,
            "employee_id": "", "designation": "Assistant Professor", "phone": ""})
        self.assertContains(r, "shown only once")
        self.assertIn("no-cache", r["Cache-Control"])
        password = PASSWORD_RE.search(r.content.decode()).group(1)
        u = User.objects.get(email=f"new.prof@{DOMAIN}")
        self.assertEqual((u.username, u.created_by, u.must_change_password), ("new.prof", self.hod, True))
        self.assertTrue(u.check_password(password))

    def test_hod_cannot_create_or_edit_admins(self):
        self.client.force_login(self.hod)
        r = self.client.get(reverse("administration:person_add"))
        self.assertNotContains(r, 'value="ADMIN"')
        r = self.client.post(reverse("administration:person_add"), {
            "full_name": "Sneaky", "email": f"sneaky@{DOMAIN}", "role": Role.ADMIN})
        self.assertFalse(User.objects.filter(email=f"sneaky@{DOMAIN}").exists())
        self.assertEqual(self.client.get(reverse("administration:person_edit", args=[self.admin.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("administration:person_toggle", args=[self.admin.pk])).status_code, 403)

    def test_admin_can_create_admin(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("administration:person_add"), {
            "full_name": "Second Admin", "email": f"admin2@{DOMAIN}", "role": Role.ADMIN})
        self.assertEqual(User.objects.get(email=f"admin2@{DOMAIN}").role, Role.ADMIN)

    def test_cannot_change_own_role_or_deactivate_self(self):
        self.client.force_login(self.hod)
        self.client.post(reverse("administration:person_edit", args=[self.hod.pk]), {
            "full_name": "The HoD", "email": self.hod.email, "username": "hod", "role": Role.FACULTY})
        self.hod.refresh_from_db()
        self.assertEqual(self.hod.role, Role.HOD)
        self.client.post(reverse("administration:person_toggle", args=[self.hod.pk]))
        self.hod.refresh_from_db()
        self.assertTrue(self.hod.is_active)

    def test_deactivate_and_reactivate(self):
        self.client.force_login(self.hod)
        self.client.post(reverse("administration:person_toggle", args=[self.f1.pk]))
        self.f1.refresh_from_db()
        self.assertFalse(self.f1.is_active)
        self.assertIsNotNone(self.f1.deactivated_at)
        self.client.post(reverse("administration:person_toggle", args=[self.f1.pk]))
        self.f1.refresh_from_db()
        self.assertTrue(self.f1.is_active)

    def test_reset_password_confirm_then_show_once(self):
        self.client.force_login(self.hod)
        url = reverse("administration:person_reset", args=[self.f1.pk])
        self.assertContains(self.client.get(url), "Generate new password")
        self.f1.refresh_from_db()
        self.assertTrue(self.f1.check_password("Old-pass-12345"))
        r = self.client.post(url)
        password = PASSWORD_RE.search(r.content.decode()).group(1)
        self.f1.refresh_from_db()
        self.assertTrue(self.f1.check_password(password))
        self.assertTrue(self.f1.must_change_password)

    def test_bulk_add(self):
        self.client.force_login(self.hod)
        lines = (f"Anita Sharma, anita@{DOMAIN}\n"
                 f"vikram@{DOMAIN}\tVikram Rao\n"          # email first, tab-separated (pasted from Excel)
                 f"Meera Iyer, meera@{DOMAIN}, HoD\n\n")
        r = self.client.post(reverse("administration:people_bulk_add"), {"lines": lines})
        self.assertContains(r, "3 people added")
        self.assertEqual(len(PASSWORD_RE.findall(r.content.decode())), 3)
        self.assertEqual(User.objects.get(email=f"vikram@{DOMAIN}").full_name, "Vikram Rao")
        self.assertEqual(User.objects.get(email=f"meera@{DOMAIN}").role, Role.HOD)

    def test_bulk_add_is_all_or_nothing(self):
        self.client.force_login(self.hod)
        lines = f"Good Person, good@{DOMAIN}\nBad Person, bad@gmail.com\nDup, f1@{DOMAIN}\nAdminTry, at@{DOMAIN}, Admin"
        r = self.client.post(reverse("administration:people_bulk_add"), {"lines": lines})
        self.assertContains(r, "Nobody was added")
        self.assertContains(r, "Line 2: bad@gmail.com")
        self.assertContains(r, "already has an account")
        self.assertContains(r, "not allowed role")
        self.assertFalse(User.objects.filter(email=f"good@{DOMAIN}").exists())


class LookupTests(AdminTestBase):
    def setUp(self):
        self.client.force_login(self.hod)

    def test_add_category_then_types(self):
        r = self.client.post(reverse("administration:lookup_add", args=["categories"]),
                             {"name": "Lab Furniture", "description": "", "sort_order": 60, "is_active": "on"})
        cat = Category.objects.get(name="Lab Furniture")
        self.assertRedirects(r, reverse("administration:lookup_edit", args=["categories", cat.pk]))
        self.client.post(reverse("administration:type_add", args=[cat.pk]),
                         {"type-name": "Chair", "type-sort_order": 10, "type-is_active": "on"})
        self.assertTrue(ItemType.objects.filter(category=cat, name="Chair").exists())
        # duplicate type (different case) is refused
        self.client.post(reverse("administration:type_add", args=[cat.pk]),
                         {"type-name": "chair", "type-sort_order": 10, "type-is_active": "on"})
        self.assertEqual(ItemType.objects.filter(category=cat).count(), 1)

    def test_duplicate_name_message(self):
        r = self.client.post(reverse("administration:lookup_add", args=["funding"]),
                             {"name": "research grant", "sort_order": 1, "is_active": "on"})
        self.assertContains(r, "“Research Grant” already exists.")

    def test_hide_and_show(self):
        fund = FundingSource.objects.get(name="Institute Fund")
        self.client.post(reverse("administration:lookup_toggle", args=["funding", fund.pk]))
        fund.refresh_from_db()
        self.assertFalse(fund.is_active)

    def test_vendor_duplicate_detection(self):
        Vendor.get_or_create_by_name("Dell India Pvt. Ltd.")
        r = self.client.post(reverse("administration:lookup_add", args=["vendors"]),
                             {"name": "DELL india pvt ltd", "is_active": "on"})
        self.assertContains(r, "already exists as")
        r = self.client.post(reverse("administration:lookup_add", args=["vendors"]),
                             {"name": "Croma", "gstin": "27aaacb1234c1z5", "is_active": "on"})
        v = Vendor.objects.get(name="Croma")
        self.assertEqual((v.gstin, v.created_by), ("27AAACB1234C1Z5", self.hod))

    def test_custom_field(self):
        gadgets = Category.objects.get(name="Gadgets")
        self.client.post(reverse("administration:lookup_add", args=["fields"]), {
            "label": "Connection", "applies_to": "ITEM", "field_type": "CHOICE", "choices": "USB\nWireless",
            "required": "on", "help_text": "", "categories": [gadgets.pk], "sort_order": 0, "is_active": "on"})
        cf = CustomField.objects.get(key="connection")
        self.assertEqual(list(cf.categories.all()), [gadgets])
        # same label again is refused
        r = self.client.post(reverse("administration:lookup_add", args=["fields"]), {
            "label": "connection", "applies_to": "ITEM", "field_type": "TEXT", "sort_order": 0, "is_active": "on"})
        self.assertContains(r, "already exists")
        # invoice fields can't be limited to categories
        r = self.client.post(reverse("administration:lookup_add", args=["fields"]), {
            "label": "GeM no", "applies_to": "PURCHASE", "field_type": "TEXT", "categories": [gadgets.pk],
            "sort_order": 0, "is_active": "on"})
        self.assertContains(r, "Categories only apply to item fields")

    def test_edit_page_shows_history(self):
        venue_add = reverse("administration:lookup_add", args=["venues"])
        self.client.post(venue_add, {"name": "Lab 6105", "building": "", "sort_order": 0, "is_active": "on"})
        from apps.catalog.models import Venue
        v = Venue.objects.get(name="Lab 6105")
        self.client.post(reverse("administration:lookup_edit", args=["venues", v.pk]),
                         {"name": "Lab 6105", "building": "New Block", "sort_order": 0, "is_active": "on"})
        r = self.client.get(reverse("administration:lookup_edit", args=["venues", v.pk]))
        self.assertContains(r, "Change history")
        self.assertContains(r, "building")
        self.assertContains(r, "The HoD")
