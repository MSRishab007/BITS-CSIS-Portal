"""Back up the database and uploaded bills into one .tar.gz file.

    python manage.py portal_backup                 # into BACKUP_DIR, prune old ones
    python manage.py portal_backup --output D:/x   # somewhere else
    python manage.py portal_backup --keep-days 30

The database copy uses SQLite's online backup API, so it is consistent even
while people are using the portal (a plain file copy can be corrupt).
"""
import json
import os
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

PREFIX = "portal-backup-"


class Command(BaseCommand):
    help = "Back up the database and uploaded bills into a single .tar.gz archive."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Folder for the archive (default: BACKUP_DIR).")
        parser.add_argument("--keep-days", type=int, help="Delete archives older than this (default: BACKUP_KEEP_DAYS). 0 = keep all.")

    def handle(self, *args, **opts):
        out_dir = Path(opts["output"] or settings.BACKUP_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M%S")
        archive = out_dir / f"{PREFIX}{stamp}.tar.gz"

        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "db.sqlite3"
            # Own connection to the database file (not Django's), so the copy
            # never waits on a transaction held by this process.
            name = str(connection.settings_dict["NAME"])
            src = sqlite3.connect(name, uri=name.startswith("file:"), timeout=30)
            dest = sqlite3.connect(db_copy)
            with dest:
                src.backup(dest)  # consistent online copy
            src.close()
            ok = dest.execute("PRAGMA integrity_check").fetchone()[0]
            dest.close()
            if ok != "ok":
                raise SystemExit(f"Database integrity check failed: {ok}")

            media = Path(settings.MEDIA_ROOT)
            files = [p for p in media.rglob("*") if p.is_file() and "bulk_tmp" not in p.parts] if media.exists() else []
            manifest = {
                "created": timezone.localtime().isoformat(),
                "database_bytes": db_copy.stat().st_size,
                "media_files": len(files),
                "media_bytes": sum(p.stat().st_size for p in files),
            }
            (Path(tmp) / "manifest.json").write_text(json.dumps(manifest, indent=2))

            partial = archive.with_suffix(".partial")
            with tarfile.open(partial, "w:gz") as tar:
                tar.add(db_copy, arcname="db.sqlite3")
                tar.add(Path(tmp) / "manifest.json", arcname="manifest.json")
                for p in files:
                    tar.add(p, arcname=str(Path("media") / p.relative_to(media)))
            os.replace(partial, archive)  # never leave a half-written archive with the real name
        os.chmod(archive, 0o600)  # contains the whole database: owner-only

        size_mb = archive.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(
            f"Backup written: {archive} ({size_mb:.1f} MB, {manifest['media_files']} bill files)"))

        keep = settings.BACKUP_KEEP_DAYS if opts["keep_days"] is None else opts["keep_days"]
        if keep and keep > 0:
            cutoff = time.time() - keep * 86400
            removed = 0
            for old in out_dir.glob(f"{PREFIX}*.tar.gz"):
                if old != archive and old.stat().st_mtime < cutoff:
                    old.unlink()
                    removed += 1
            if removed:
                self.stdout.write(f"Removed {removed} backup(s) older than {keep} days.")
