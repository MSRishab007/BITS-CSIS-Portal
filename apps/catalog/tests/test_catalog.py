from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.models import (
    Category, CustomField, FundingSource, ItemType, Vendor, clean_extra, normalize_vendor_name,
)


class SeedDataTests(TestCase):
    def test_defaults_present(self):
        self.assertEqual(Category.objects.count(), 5)
        self.assertTrue(ItemType.objects.filter(category__name="Gadgets", name="Keyboard").exists())
        self.assertTrue(FundingSource.objects.get(name="Research Grant").requires_project_details)
        self.assertFalse(FundingSource.objects.get(name="Departmental Fund").requires_project_details)


class VendorTests(TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_vendor_name("  Dell India Pvt. Ltd. "), "dell india pvt ltd")
        self.assertEqual(normalize_vendor_name("A&B  Traders"), normalize_vendor_name("a and b traders"))

    def test_get_or_create_reuses_existing(self):
        v1, created1 = Vendor.get_or_create_by_name("Dell India Pvt. Ltd.")
        v2, created2 = Vendor.get_or_create_by_name("DELL india pvt ltd")
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(v1.pk, v2.pk)
        self.assertEqual(v2.name, "Dell India Pvt. Ltd.")  # original spelling kept

    def test_clean_reports_duplicate_by_name(self):
        Vendor.get_or_create_by_name("Amazon Business")
        v = Vendor(name="amazon   business.")
        with self.assertRaisesMessage(ValidationError, 'already exists as "Amazon Business"'):
            v.full_clean()

    def test_blank_name_rejected(self):
        with self.assertRaises(ValidationError):
            Vendor.get_or_create_by_name("  ...  ")


class CustomFieldTests(TestCase):
    def setUp(self):
        self.gadgets = Category.objects.get(name="Gadgets")
        self.servers = Category.objects.get(name="Server/GPU Resources")

    def make(self, label, field_type, applies_to=CustomField.AppliesTo.ITEM, **kw):
        f = CustomField(label=label, field_type=field_type, applies_to=applies_to, **kw)
        f.full_clean()
        f.save()
        return f

    def test_key_from_label(self):
        f = self.make("Rack Position", CustomField.FieldType.TEXT)
        self.assertEqual(f.key, "rack_position")

    def test_dropdown_needs_options(self):
        f = CustomField(label="Colour", field_type=CustomField.FieldType.CHOICE)
        with self.assertRaises(ValidationError):
            f.full_clean()

    def test_value_conversion(self):
        num = self.make("Cores", CustomField.FieldType.NUMBER)
        date = self.make("Installed On", CustomField.FieldType.DATE)
        yes = self.make("AMC", CustomField.FieldType.BOOLEAN)
        pick = self.make("OS", CustomField.FieldType.CHOICE, choices="Linux\nWindows")
        self.assertEqual(num.to_value("1,024"), "1024")
        self.assertEqual(date.to_value("05/03/2026"), "2026-03-05")
        self.assertEqual(yes.to_value("Yes"), True)
        self.assertEqual(pick.to_value("linux"), "Linux")
        for field, bad in ((num, "abc"), (date, "31-31-2026"), (yes, "maybe"), (pick, "Mac")):
            with self.subTest(field=field.label), self.assertRaises(ValidationError):
                field.to_value(bad)

    def test_clean_extra_required_unknown_and_category_scope(self):
        rack = self.make("Rack Position", CustomField.FieldType.TEXT, required=True)
        rack.categories.add(self.servers)
        # Required only applies to Server/GPU items
        self.assertEqual(clean_extra("ITEM", {"junk": 1}, category=self.gadgets), {})
        with self.assertRaisesMessage(ValidationError, "Rack Position is required"):
            clean_extra("ITEM", {}, category=self.servers)
        self.assertEqual(clean_extra("ITEM", {"rack_position": " R2-U14 "}, category=self.servers),
                         {"rack_position": "R2-U14"})

    def test_inactive_fields_ignored(self):
        self.make("Old Field", CustomField.FieldType.TEXT, required=True, is_active=False)
        self.assertEqual(clean_extra("ITEM", {}), {})


class VenueTests(TestCase):
    def test_get_or_create_matches_case_and_reactivates(self):
        from apps.catalog.models import Venue
        v, created = Venue.get_or_create_by_name("Lab  6105")
        self.assertTrue(created)
        self.assertEqual(v.name, "Lab 6105")
        v.is_active = False
        v.save()
        again, created = Venue.get_or_create_by_name("LAB 6105")
        self.assertFalse(created)
        self.assertEqual(again.pk, v.pk)
        self.assertTrue(again.is_active)
