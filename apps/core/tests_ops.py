"""Tests for operations: backup/restore commands and Nginx bill hand-off."""
import datetime
import os
import shutil
import sqlite3
import tarfile
import tempfile
from io import StringIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import Category, FundingSource, Vendor
from apps.purchases.models import Purchase, PurchaseItem

DOMAIN = "pilani.bits-pilani.ac.in"


class OpsBase(TransactionTestCase):
    """Committed data (like the real command sees), seed data restored after each test."""

    serialized_rollback = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.media = self.tmp / "media"
        self.backups = self.tmp / "backups"
        self.override = override_settings(MEDIA_ROOT=str(self.media), BACKUP_DIR=self.backups,
                                          BACKUP_KEEP_DAYS=14, ALLOWED_EMAIL_DOMAINS=[DOMAIN])
        self.override.enable()
        self.owner = User.objects.create_user(f"o@{DOMAIN}", "x", full_name="Owner")
        self.other = User.objects.create_user(f"x@{DOMAIN}", "x", full_name="Other")
        vendor, _ = Vendor.get_or_create_by_name("Dell")
        self.purchase = Purchase.objects.create(owner=self.owner, vendor=vendor, invoice_number="OPS/1",
                                                purchase_date=datetime.date(2026, 3, 1), bill_amount=10,
                                                bill_file=SimpleUploadedFile("bill.pdf", b"%PDF-1.7 ops"))
        g = Category.objects.get(name="Gadgets")
        PurchaseItem.objects.create(purchase=self.purchase, category=g, item_type=g.types.first(), item_name="KB",
                                    quantity=1, funding_source=FundingSource.objects.first())

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)


class BackupRestoreTests(OpsBase):
    def test_backup_contains_db_and_bills_and_is_private(self):
        out = StringIO()
        call_command("portal_backup", stdout=out)
        archives = list(self.backups.glob("portal-backup-*.tar.gz"))
        self.assertEqual(len(archives), 1)
        if os.name != "nt":  # Windows has no Unix permission bits; the server (Linux) does
            self.assertEqual(archives[0].stat().st_mode & 0o777, 0o600)
        with tarfile.open(archives[0]) as tar:
            names = tar.getnames()
        self.assertIn("db.sqlite3", names)
        self.assertIn("manifest.json", names)
        self.assertIn(f"media/{self.purchase.bill_file.name}", names)
        self.assertIn("1 bill files", out.getvalue())

    def test_old_backups_pruned(self):
        import os
        import time
        self.backups.mkdir(parents=True)
        old = self.backups / "portal-backup-2020-01-01_000000.tar.gz"
        old.write_bytes(b"x")
        os.utime(old, (time.time() - 40 * 86400,) * 2)
        call_command("portal_backup", stdout=StringIO())
        self.assertFalse(old.exists())

    def test_restore_round_trip(self):
        call_command("portal_backup", stdout=StringIO())
        archive = next(self.backups.glob("*.tar.gz"))
        target_db = self.tmp / "restored" / "db.sqlite3"
        target_db.parent.mkdir()
        target_db.write_bytes(b"old")  # existing db must be kept aside
        target_media = self.tmp / "restored-media"
        call_command("portal_restore", str(archive), "--yes", "--database", str(target_db),
                     "--media", str(target_media), stdout=StringIO())
        con = sqlite3.connect(target_db)
        self.assertEqual(con.execute("select invoice_number from purchases_purchase").fetchall(), [("OPS/1",)])
        con.close()
        self.assertTrue((target_media / self.purchase.bill_file.name).exists())
        self.assertEqual(len(list(target_db.parent.glob("db.sqlite3.before-restore-*"))), 1)

    def test_restore_rejects_non_backup(self):
        bad = self.tmp / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            f = self.tmp / "hello.txt"
            f.write_text("hi")
            tar.add(f, arcname="hello.txt")
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, "no db.sqlite3"):
            call_command("portal_restore", str(bad), "--yes", "--database", str(self.tmp / "d.sqlite3"),
                         stdout=StringIO())


class NginxBillTests(OpsBase):
    @override_settings(SERVE_BILLS_WITH_NGINX=True)
    def test_x_accel_redirect_after_permission_check(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse("purchases:bill", args=[self.purchase.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Accel-Redirect"], f"/protected-media/{self.purchase.bill_file.name}")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn('inline; filename="bill-OPS_1.pdf"', r["Content-Disposition"])
        self.assertEqual(r.content, b"")  # Nginx sends the bytes, not Django
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("purchases:bill", args=[self.purchase.pk])).status_code, 404)
