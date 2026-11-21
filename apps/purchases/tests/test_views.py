import datetime
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor
from apps.purchases.models import Purchase, PurchaseItem

DOMAIN = "pilani.bits-pilani.ac.in"
MEDIA = tempfile.mkdtemp()


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN], MEDIA_ROOT=MEDIA)
class ViewTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "x", full_name="Faculty One")
        cls.f2 = User.objects.create_user(f"f2@{DOMAIN}", "x", full_name="Faculty Two")
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        cls.dell, _ = Vendor.get_or_create_by_name("Dell India Pvt. Ltd.")
        cls.gadgets = Category.objects.get(name="Gadgets")
        cls.keyboard = ItemType.objects.get(category=cls.gadgets, name="Keyboard")
        cls.fund = FundingSource.objects.get(name="Departmental Fund")

    def make_purchase(self, owner, invoice, vendor=None):
        p = Purchase.objects.create(owner=owner, vendor=vendor or self.dell, invoice_number=invoice,
                                    purchase_date=datetime.date(2026, 2, 1), bill_amount=1000)
        PurchaseItem.objects.create(purchase=p, category=self.gadgets, item_type=self.keyboard,
                                    item_name="Keyboard", quantity=1, funding_source=self.fund)
        return p

    def item_data(self, i=0, **kw):
        d = {"category": self.gadgets.pk, "item_type": self.keyboard.pk, "item_name": f"Logitech K{i}",
             "quantity": 2, "amount": "1200.00", "funding_source": self.fund.pk, "project_number": "",
             "principal_investigator": "", "venue": "", "serial_numbers": "", "asset_tag": "",
             "warranty_end_date": "", "status": "IN_USE", "remarks": ""}
        d.update(kw)
        return {f"items-{i}-{k}": v for k, v in d.items()}

    def post_data(self, items=1, initial=0, **invoice):
        data = {"invoice_number": "INV-100", "vendor": "", "vendor_name": "", "order_number": "",
                "purchase_date": "2026-03-01", "delivery_date": "", "bill_amount": "2400", "remarks": "",
                "items-TOTAL_FORMS": str(items), "items-INITIAL_FORMS": str(initial),
                "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "1000"}
        data.update(invoice)
        for i in range(items):
            data.update(self.item_data(i))
        return data


class VendorApiTests(ViewTestBase):
    def test_search_and_exact(self):
        self.client.force_login(self.f1)
        url = reverse("purchases:api_vendors")
        r = self.client.get(url, {"q": "dell"}).json()
        self.assertEqual(r["results"], [{"id": self.dell.pk, "name": "Dell India Pvt. Ltd."}])
        self.assertIsNone(r["exact"])
        r = self.client.get(url, {"q": "DELL india pvt ltd"}).json()
        self.assertEqual(r["exact"]["id"], self.dell.pk)

    def test_requires_login(self):
        r = self.client.get(reverse("purchases:api_vendors"))
        self.assertEqual(r.status_code, 302)


class MyInvoicesApiTests(ViewTestBase):
    def test_only_own_invoices(self):
        mine = self.make_purchase(self.f1, "MINE-1")
        self.make_purchase(self.f2, "THEIRS-1")
        self.client.force_login(self.f1)
        url = reverse("purchases:api_my_invoices")
        r = self.client.get(url).json()["results"]
        self.assertEqual([x["id"] for x in r], [mine.pk])
        # Faculty can't peek at someone else's by passing owner=
        r = self.client.get(url, {"owner": self.f2.pk}).json()["results"]
        self.assertEqual([x["id"] for x in r], [mine.pk])

    def test_hod_sees_own_by_default_and_others_on_request(self):
        theirs = self.make_purchase(self.f2, "THEIRS-1")
        self.client.force_login(self.hod)
        url = reverse("purchases:api_my_invoices")
        self.assertEqual(self.client.get(url).json()["results"], [])
        r = self.client.get(url, {"owner": self.f2.pk}).json()["results"]
        self.assertEqual([x["id"] for x in r], [theirs.pk])

    def test_search_by_number(self):
        self.make_purchase(self.f1, "ABC-1")
        self.make_purchase(self.f1, "XYZ-9")
        self.client.force_login(self.f1)
        r = self.client.get(reverse("purchases:api_my_invoices"), {"q": "xyz"}).json()["results"]
        self.assertEqual([x["invoice_number"] for x in r], ["XYZ-9"])
        self.assertTrue(r[0]["add_items_url"].endswith("/add-items/"))


class CreatePurchaseTests(ViewTestBase):
    url = reverse("purchases:create")

    def test_form_renders(self):
        self.client.force_login(self.f1)
        r = self.client.get(self.url)
        self.assertContains(r, 'x-data="vendorPicker"')
        self.assertContains(r, 'x-data="invoicePicker"')
        self.assertNotContains(r, 'name="owner"')  # faculty can't choose owner

    def test_create_with_existing_vendor(self):
        self.client.force_login(self.f1)
        r = self.client.post(self.url, self.post_data(items=2, vendor=self.dell.pk, vendor_name=self.dell.name))
        p = Purchase.objects.get(invoice_number="INV-100")
        self.assertRedirects(r, reverse("purchases:detail", args=[p.pk]))
        self.assertEqual(p.owner, self.f1)
        self.assertEqual(p.created_by, self.f1)
        self.assertEqual(p.items.count(), 2)

    def test_create_with_new_vendor_name(self):
        self.client.force_login(self.f1)
        self.client.post(self.url, self.post_data(vendor_name="Croma Retail"))
        v = Vendor.objects.get(name="Croma Retail")
        self.assertEqual(v.created_by, self.f1)
        self.assertEqual(Purchase.objects.get().vendor, v)

    def test_typed_name_matching_existing_vendor_reuses_it(self):
        self.client.force_login(self.f1)
        self.client.post(self.url, self.post_data(vendor_name="dell INDIA pvt ltd"))
        self.assertEqual(Vendor.objects.count(), 1)
        self.assertEqual(Purchase.objects.get().vendor, self.dell)

    def test_new_vendor_rolled_back_when_form_invalid(self):
        self.client.force_login(self.f1)
        r = self.client.post(self.url, self.post_data(vendor_name="Brand New Traders", purchase_date=""))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Vendor.objects.filter(name="Brand New Traders").exists())
        self.assertFalse(Purchase.objects.exists())
        # The typed name is kept in the form so nothing is lost
        self.assertContains(r, 'data-initial-name="Brand New Traders"')

    def test_vendor_required(self):
        self.client.force_login(self.f1)
        r = self.client.post(self.url, self.post_data())
        self.assertContains(r, "Choose a vendor or type a new vendor name.")

    def test_faculty_cannot_set_owner(self):
        self.client.force_login(self.f1)
        self.client.post(self.url, self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name, owner=self.f2.pk))
        self.assertEqual(Purchase.objects.get().owner, self.f1)

    def test_hod_can_record_for_faculty(self):
        self.client.force_login(self.hod)
        self.client.post(self.url, self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name, owner=self.f2.pk))
        p = Purchase.objects.get()
        self.assertEqual((p.owner, p.created_by), (self.f2, self.hod))

    def test_needs_at_least_one_item(self):
        self.client.force_login(self.f1)
        data = self.post_data(vendor_name="X")
        data["items-0-DELETE"] = "on"
        r = self.client.post(self.url, data)
        self.assertContains(r, "Please submit at least 1 form")
        self.assertFalse(Purchase.objects.exists())

    def test_duplicate_invoice_message(self):
        self.make_purchase(self.f2, "INV-100")
        self.client.force_login(self.f1)
        r = self.client.post(self.url, self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name))
        self.assertContains(r, "already recorded by Faculty Two")

    def test_bill_upload(self):
        self.client.force_login(self.f1)
        data = self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name)
        data["bill_file"] = SimpleUploadedFile("my bill.pdf", b"%PDF-1.7 test", content_type="application/pdf")
        self.client.post(self.url, data)
        p = Purchase.objects.get()
        self.assertTrue(p.bill_file.name.startswith("bills/"))
        self.assertNotIn("my bill", p.bill_file.name)  # random file name

    def test_required_item_custom_field_for_category(self):
        cf = CustomField.objects.create(label="Connection", field_type="CHOICE", choices="USB\nWireless",
                                        required=True)
        cf.categories.add(self.gadgets)
        self.client.force_login(self.f1)
        r = self.client.post(self.url, self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name))
        self.assertContains(r, "Connection is required.")
        data = self.post_data(vendor=self.dell.pk, vendor_name=self.dell.name)
        data["items-0-extra__connection"] = "Wireless"
        self.client.post(self.url, data)
        self.assertEqual(PurchaseItem.objects.get().extra, {"connection": "Wireless"})


class AddItemsTests(ViewTestBase):
    def test_add_items_to_own_invoice(self):
        p = self.make_purchase(self.f1, "A-1")
        self.client.force_login(self.f1)
        data = {"items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "1000", **self.item_data(0, item_name="Extra mouse")}
        r = self.client.post(reverse("purchases:add_items", args=[p.pk]), data)
        self.assertRedirects(r, reverse("purchases:detail", args=[p.pk]))
        self.assertEqual(p.items.count(), 2)

    def test_cannot_add_to_someone_elses(self):
        p = self.make_purchase(self.f2, "B-1")
        self.client.force_login(self.f1)
        self.assertEqual(self.client.get(reverse("purchases:add_items", args=[p.pk])).status_code, 404)


class AccessTests(ViewTestBase):
    def test_list_shows_only_own_for_faculty(self):
        self.make_purchase(self.f1, "MINE-1")
        self.make_purchase(self.f2, "THEIRS-1")
        self.client.force_login(self.f1)
        r = self.client.get(reverse("purchases:list"))
        self.assertContains(r, "MINE-1")
        self.assertNotContains(r, "THEIRS-1")
        self.client.force_login(self.hod)
        r = self.client.get(reverse("purchases:list"))
        self.assertContains(r, "MINE-1")
        self.assertContains(r, "THEIRS-1")

    def test_detail_edit_delete_permissions(self):
        p = self.make_purchase(self.f2, "T-1")
        self.client.force_login(self.f1)
        for name in ("detail", "edit", "delete", "bill"):
            self.assertEqual(self.client.get(reverse(f"purchases:{name}", args=[p.pk])).status_code, 404, name)
        self.client.force_login(self.hod)
        self.assertEqual(self.client.get(reverse("purchases:edit", args=[p.pk])).status_code, 200)

    def test_edit_keeps_items_and_records_history(self):
        p = self.make_purchase(self.f1, "E-1")
        item = p.items.get()
        self.client.force_login(self.f1)
        data = self.post_data(items=1, initial=1, invoice_number="E-1", vendor=self.dell.pk,
                              vendor_name=self.dell.name, bill_amount="1500")
        data["items-0-id"] = item.pk
        data["items-0-purchase"] = p.pk
        r = self.client.post(reverse("purchases:edit", args=[p.pk]), data)
        self.assertRedirects(r, reverse("purchases:detail", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.bill_amount, 1500)
        page = self.client.get(reverse("purchases:detail", args=[p.pk]))
        self.assertContains(page, "Change history")
        self.assertContains(page, "bill amount")

    def test_delete(self):
        p = self.make_purchase(self.f1, "D-1")
        self.client.force_login(self.f1)
        self.client.post(reverse("purchases:delete", args=[p.pk]))
        self.assertFalse(Purchase.objects.filter(pk=p.pk).exists())
        self.assertTrue(Purchase.history.filter(id=p.pk, history_type="-").exists())

    def test_bill_served_only_to_allowed_users(self):
        p = self.make_purchase(self.f1, "F-1")
        p.bill_file = SimpleUploadedFile("b.pdf", b"%PDF-1.7 secret")
        p.save()
        self.client.force_login(self.f1)
        r = self.client.get(reverse("purchases:bill", args=[p.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.7 secret")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.client.force_login(self.f2)
        self.assertEqual(self.client.get(reverse("purchases:bill", args=[p.pk])).status_code, 404)

    def test_dashboard(self):
        self.make_purchase(self.f1, "H-1")
        self.client.force_login(self.f1)
        r = self.client.get(reverse("core:home"))
        self.assertContains(r, "H-1")
        self.assertContains(r, "₹1,000.00")
