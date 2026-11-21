"""Restore a backup made by portal_backup.

    sudo systemctl stop asset-portal          # stop the site first
    python manage.py portal_restore backups/portal-backup-2026-11-21_020000.tar.gz
    sudo systemctl start asset-portal

The current database is kept next to it as db.sqlite3.before-restore-<time>,
and the restored database is integrity-checked before it replaces anything.
"""
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Restore the database and uploaded bills from a portal_backup archive."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--yes", action="store_true", help="Don't ask for confirmation.")
        parser.add_argument("--database", help="Database file to restore into (default: the configured one).")
        parser.add_argument("--media", help="Media folder to restore into (default: MEDIA_ROOT).")

    def handle(self, *args, **opts):
        archive = Path(opts["archive"])
        if not archive.exists():
            raise CommandError(f"No such file: {archive}")
        db_path = Path(opts["database"] or settings.DATABASES["default"]["NAME"])
        media_root = Path(opts["media"] or settings.MEDIA_ROOT)

        if not opts["yes"]:
            self.stdout.write(f"This replaces {db_path} and restores bills into {media_root}.")
            self.stdout.write("Stop the portal first (sudo systemctl stop asset-portal).")
            if input("Type RESTORE to continue: ").strip() != "RESTORE":
                raise CommandError("Cancelled.")

        with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "r:gz") as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and not m.name.startswith("/") and ".." not in Path(m.name).parts]
            try:
                tar.extractall(tmp, members=members, filter="data")
            except TypeError:  # older Python without extraction filters (members already checked)
                tar.extractall(tmp, members=members)
            new_db = Path(tmp) / "db.sqlite3"
            if not new_db.exists():
                raise CommandError("This archive has no db.sqlite3; is it a portal backup?")
            con = sqlite3.connect(new_db)
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
            if ok != "ok":
                raise CommandError(f"The backup's database failed its integrity check: {ok}")

            if db_path.exists():
                keep = db_path.with_name(f"{db_path.name}.before-restore-{timezone.localtime():%Y%m%d-%H%M%S}")
                shutil.copy2(db_path, keep)
                self.stdout.write(f"Current database saved as {keep}")
            for suffix in ("-wal", "-shm"):  # stale WAL files would corrupt the restored copy
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_db, db_path)

            restored = 0
            src_media = Path(tmp) / "media"
            if src_media.exists():
                for f in src_media.rglob("*"):
                    if f.is_file():
                        target = media_root / f.relative_to(src_media)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, target)
                        restored += 1
        self.stdout.write(self.style.SUCCESS(f"Restored database and {restored} bill file(s). Start the portal again."))
