import datetime
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import Role, User
from apps.catalog.models import Category, CustomField, Vendor
from apps.purchases import bulk
from apps.purchases.models import Purchase, PurchaseItem

DOMAIN = "pilani.bits-pilani.ac.in"
MEDIA = tempfile.mkdtemp()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN], MEDIA_ROOT=MEDIA)
class BulkTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.f1 = User.objects.create_user(f"f1@{DOMAIN}", "x", full_name="Faculty One")
        cls.f2 = User.objects.create_user(f"f2@{DOMAIN}", "x", full_name="Faculty Two")
        cls.hod = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="The HoD", role=Role.HOD)
        Vendor.get_or_create_by_name("Dell India Pvt. Ltd.")

    def row(self, **kw):
        base = {"invoice_number": "INV-1", "vendor": "Dell India Pvt. Ltd.", "purchase_date": datetime.date(2026, 3, 1),
                "bill_amount": 5000, "category": "Gadgets", "item_type": "Keyboard", "item_name": "Logitech K120",
                "quantity": 2, "amount": 1000, "funding_source": "Departmental Fund"}
        base.update(kw)
        return base

    def workbook(self, user, rows):
        """Fill the real generated template with `rows` (dicts keyed by column key)."""
        wb = load_workbook(io.BytesIO(bulk.build_template_xlsx(user)))
        ws = wb[bulk.SHEET_NAME]
        keys = [c.key for c in bulk.build_columns(user)]
        for r, row in enumerate(rows, start=2):
            for c, key in enumerate(keys, start=1):
                if key in row:
                    ws.cell(row=r, column=c, value=row[key])
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("filled.xlsx", buf.getvalue(), content_type=XLSX)

    def upload(self, user, rows):
        self.client.force_login(user)
        return self.client.post(reverse("purchases:bulk_upload"), {"file": self.workbook(user, rows)})

    def errors(self, response):
        return [(e.row, e.column, e.message) for e in response.context["result"].errors]


class TemplateTests(BulkTestBase):
    def test_xlsx_structure(self):
        wb = load_workbook(io.BytesIO(bulk.build_template_xlsx(self.f1)))
        self.assertEqual(wb.sheetnames, ["Instructions", "Purchases", "Lists", "Example"])
        self.assertEqual(wb["Lists"].sheet_state, "hidden")
        headers = [c.value for c in wb["Purchases"][1]]
        self.assertIn("Invoice number *", headers)
        self.assertIn("Category *", headers)
        self.assertNotIn("Faculty email or username", headers)  # faculty: own purchases only
        self.assertGreaterEqual(len(wb["Purchases"].data_validations.dataValidation), 6)

    def test_hod_template_has_faculty_column(self):
        headers = [c.key for c in bulk.build_columns(self.hod)]
        self.assertEqual(headers[0], "owner")

    def test_custom_fields_become_columns(self):
        CustomField.objects.create(label="Rack Position", applies_to="ITEM", field_type="TEXT")
        CustomField.objects.create(label="GeM Order", applies_to="PURCHASE", field_type="TEXT", required=True)
        titles = [c.title for c in bulk.build_columns(self.f1)]
        self.assertIn("Rack Position", titles)
        self.assertIn("GeM Order *", titles)

    def test_downloads(self):
        self.client.force_login(self.f1)
        r = self.client.get(reverse("purchases:bulk_template", args=["xlsx"]))
        self.assertEqual(r["Content-Type"], XLSX)
        self.assertIn("attachment;", r["Content-Disposition"])
        r = self.client.get(reverse("purchases:bulk_template", args=["csv"]))
        self.assertTrue(r.content.decode("utf-8-sig").startswith("Invoice number *,Vendor *"))

    def test_example_sheet_rows_are_valid(self):
        """The sample rows we ship must pass our own checks."""
        wb = load_workbook(io.BytesIO(bulk.build_template_xlsx(self.f1)))
        ex = wb["Example"]
        rows = [list(r) for r in ex.iter_rows(values_only=True)]
        result = bulk.run_import(rows[0], [(i + 2, r) for i, r in enumerate(rows[1:])], self.f1, commit=False)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.invoices), 2)


class ImportTests(BulkTestBase):
    def test_preview_saves_nothing_then_confirm_saves(self):
        rows = [self.row(), self.row(item_type="Mouse", item_name="MX Master"),
                self.row(invoice_number="CR-9", vendor="Croma Retail", bill_amount="1,200", item_name="Headset",
                         item_type="Headphone", purchase_date="05/04/2026")]
        r = self.upload(self.f1, rows)
        result = r.context["result"]
        self.assertEqual(result.errors, [])
        self.assertEqual((len(result.invoices), result.item_count), (2, 3))
        self.assertEqual(result.new_vendors, ["Croma Retail"])
        self.assertContains(r, "Import 2 invoices")
        # Dry run: nothing saved, new vendor not created yet
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(Vendor.objects.filter(name="Croma Retail").exists())

        r = self.client.post(reverse("purchases:bulk_confirm"))
        self.assertRedirects(r, reverse("purchases:list"))
        self.assertEqual(Purchase.objects.count(), 2)
        inv = Purchase.objects.get(invoice_number="INV-1")
        self.assertEqual((inv.owner, inv.items.count()), (self.f1, 2))
        cr = Purchase.objects.get(invoice_number="CR-9")
        self.assertEqual(cr.purchase_date, datetime.date(2026, 4, 5))
        self.assertEqual(cr.bill_amount, 1200)
        self.assertEqual(cr.history.first().history_user, self.f1)

    def test_confirm_twice_does_not_duplicate(self):
        self.upload(self.f1, [self.row()])
        self.client.post(reverse("purchases:bulk_confirm"))
        r = self.client.post(reverse("purchases:bulk_confirm"))
        self.assertRedirects(r, reverse("purchases:bulk_upload"))
        self.assertEqual(Purchase.objects.count(), 1)

    def test_row_errors_are_reported_and_nothing_saved(self):
        rows = [
            self.row(category="Furniture"),                                   # row 2
            self.row(invoice_number="B", item_type="GPU"),                    # row 3
            self.row(invoice_number="C", purchase_date="31-31-2026"),         # row 4
            self.row(invoice_number="D", funding_source="Research Grant"),    # row 5
            self.row(invoice_number="E", quantity=""),                        # row 6
            self.row(invoice_number="F", vendor="Brand New Co"),              # row 7 (valid)
        ]
        r = self.upload(self.f1, rows)
        errs = self.errors(r)
        self.assertIn((2, "Category", "'Furniture' is not a known category."), errs)
        self.assertNotIn("Type", [e[1] for e in errs if e[0] == 2])  # no noise about Type
        self.assertIn((3, "Type", "'GPU' is not a type under Gadgets."), errs)
        self.assertIn((4, "Purchase date", "'31-31-2026' is not a date. Use DD-MM-YYYY."), errs)
        self.assertIn((5, "Project / grant no.", "Project / grant number is required for Research Grant."), errs)
        self.assertIn((6, "Quantity", "This is required."), errs)
        self.assertEqual([e for e in errs if e[0] == 7], [])
        self.assertContains(r, "Not imported")
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(Vendor.objects.filter(name="Brand New Co").exists())
        # An upload with errors can't be confirmed
        r = self.client.post(reverse("purchases:bulk_confirm"))
        self.assertRedirects(r, reverse("purchases:bulk_upload"))

    def test_conflicting_invoice_details(self):
        r = self.upload(self.f1, [self.row(), self.row(bill_amount=9999)])
        self.assertIn((3, "Bill amount", "Differs from row 2 for the same invoice ('5000' vs '9999')."), self.errors(r))

    def test_already_recorded_invoice(self):
        self.upload(self.f1, [self.row()])
        self.client.post(reverse("purchases:bulk_confirm"))
        r = self.upload(self.f2, [self.row(invoice_number="inv-1")])
        self.assertIn((2, "Invoice number", "Invoice INV-1 from Dell India Pvt. Ltd. is already recorded by Faculty One."),
                      self.errors(r))

    def test_missing_required_column(self):
        self.client.force_login(self.f1)
        f = SimpleUploadedFile("x.csv", b"Invoice number,Vendor\nA,B\n", content_type="text/csv")
        r = self.client.post(reverse("purchases:bulk_upload"), {"file": f})
        self.assertIn("Missing required column(s)", self.errors(r)[0][2])

    def test_csv_upload(self):
        header = ",".join(c.title for c in bulk.build_columns(self.f1))
        cols = [c.key for c in bulk.build_columns(self.f1)]
        values = {**self.row(purchase_date="01-03-2026"), "serial_numbers": "SN1; SN2"}
        line = ",".join(str(values.get(k, "")) for k in cols)
        self.client.force_login(self.f1)
        f = SimpleUploadedFile("p.csv", f"{header}\n{line}\n".encode(), content_type="text/csv")
        r = self.client.post(reverse("purchases:bulk_upload"), {"file": f})
        self.assertEqual(self.errors(r), [])
        self.client.post(reverse("purchases:bulk_confirm"))
        self.assertEqual(PurchaseItem.objects.get().serial_numbers, "SN1\nSN2")

    def test_hod_uploads_for_faculty(self):
        r = self.upload(self.hod, [self.row(owner="f2"), self.row(owner="nobody", invoice_number="X")])
        self.assertIn((3, "Faculty email or username", "No user 'nobody'."), self.errors(r))
        r = self.upload(self.hod, [self.row(owner="f2"), self.row(owner="", invoice_number="X")])
        self.assertEqual(self.errors(r), [])
        self.client.post(reverse("purchases:bulk_confirm"))
        self.assertEqual(Purchase.objects.get(invoice_number="INV-1").owner, self.f2)
        self.assertEqual(Purchase.objects.get(invoice_number="X").owner, self.hod)

    def test_item_custom_field_required_for_category(self):
        cf = CustomField.objects.create(label="Rack Position", applies_to="ITEM", field_type="TEXT", required=True)
        cf.categories.add(Category.objects.get(name="Server/GPU Resources"))
        rows = [self.row(),  # Gadgets: not needed
                self.row(invoice_number="S", category="Server/GPU Resources", item_type="GPU")]
        r = self.upload(self.f1, rows)
        self.assertEqual([e for e in self.errors(r)], [(3, "", "Rack Position is required.")])

    def test_stepper_states(self):
        self.client.force_login(self.f1)
        r = self.client.get(reverse("purchases:bulk_upload"))
        self.assertContains(r, 'class="stepper"')
        self.assertContains(r, "step: 1, error: false")
        r = self.upload(self.f1, [self.row(category="Furniture")])
        self.assertContains(r, "step: 3, error: true")
        self.assertContains(r, "1 problem")
        r = self.upload(self.f1, [self.row()])
        self.assertContains(r, "step: 3, error: false")
        self.assertContains(r, "1 invoice ready")

    def test_rejects_other_file_types(self):
        self.client.force_login(self.f1)
        f = SimpleUploadedFile("x.pdf", b"%PDF-1.4", content_type="application/pdf")
        r = self.client.post(reverse("purchases:bulk_upload"), {"file": f})
        self.assertContains(r, "Upload the .xlsx or .csv template.")
