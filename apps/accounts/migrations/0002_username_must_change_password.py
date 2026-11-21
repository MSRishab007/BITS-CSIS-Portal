"""Add `username` and `must_change_password` to User.

Done in three steps so it works on a database that already has users:
  1. add `username` as an optional, non-unique column
  2. fill it in for existing users from their email (ravi.kumar@... -> ravi.kumar)
  3. make it unique
"""
import re

import django.core.validators
from django.db import migrations, models

import apps.accounts.models


def fill_usernames(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    used = set()
    for user in User.objects.order_by("pk"):
        base = re.sub(r"[^a-z0-9._-]", "", user.email.split("@", 1)[0].lower())[:40]
        if len(base) < 2:
            base = f"{base}user"
        candidate, n = base, 1
        while candidate in used:
            n += 1
            candidate = base[: 40 - len(str(n))] + str(n)
        used.add(candidate)
        user.username = candidate
        user.save(update_fields=["username"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Set when a password is generated; the user must choose their own at next sign-in.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(blank=True, default="", max_length=40),
            preserve_default=False,
        ),
        migrations.RunPython(fill_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=apps.accounts.models.LowercaseCharField(
                blank=True,
                help_text="Short sign-in name. Leave blank to use the part of the email before '@'.",
                max_length=40,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[a-z0-9._-]{2,40}$",
                        "Use 2–40 characters: lower-case letters, digits, '.', '_' or '-'. No '@'.",
                    )
                ],
            ),
        ),
    ]
