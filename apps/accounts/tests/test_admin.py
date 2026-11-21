import re

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User

DOMAIN = "pilani.bits-pilani.ac.in"
PASSWORD_RE = re.compile(r'class="cred-pass">([A-Za-z0-9-]+)<')


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class AdminUserTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(f"admin@{DOMAIN}", "Admin-pass-123", full_name="Admin")
        self.client.force_login(self.admin)
        self.changelist = reverse("admin:accounts_user_changelist")

    def add_user(self, **extra):
        data = {"email": f"new.faculty@{DOMAIN}", "full_name": "New Faculty", "username": "",
                "role": Role.FACULTY, "employee_id": "", "designation": "", "phone": "", **extra}
        return self.client.post(reverse("admin:accounts_user_add"), data)

    def test_add_user_shows_generated_password_once(self):
        r = self.add_user()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "shown only once")
        self.assertIn("no-cache", r["Cache-Control"])
        password = PASSWORD_RE.search(r.content.decode()).group(1)

        user = User.objects.get(email=f"new.faculty@{DOMAIN}")
        self.assertEqual(user.username, "new.faculty")
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(password))
        self.assertEqual(user.created_by, self.admin)
        # The plain password is not stored anywhere on the user.
        self.assertNotIn(password, user.password)

        # Shown once: the user's change page never shows it.
        page = self.client.get(reverse("admin:accounts_user_change", args=[user.pk]))
        self.assertNotContains(page, password)

    def test_add_user_rejects_other_domain(self):
        r = self.add_user(email="someone@gmail.com")
        self.assertContains(r, "Only email addresses on")
        self.assertFalse(User.objects.filter(email="someone@gmail.com").exists())

    def test_reset_password_action_asks_for_confirmation_then_resets(self):
        target = User.objects.create_user(f"t@{DOMAIN}", "Old-pass-12345", full_name="Target")
        base = {"action": "reset_passwords", ACTION_CHECKBOX_NAME: [target.pk]}

        r = self.client.post(self.changelist, base)
        self.assertContains(r, "Yes, generate passwords")
        target.refresh_from_db()
        self.assertTrue(target.check_password("Old-pass-12345"))  # nothing changed yet

        r = self.client.post(self.changelist, {**base, "confirm": "yes"})
        password = PASSWORD_RE.search(r.content.decode()).group(1)
        target.refresh_from_db()
        self.assertTrue(target.check_password(password))
        self.assertTrue(target.must_change_password)

    def test_reset_skips_self_and_inactive(self):
        inactive = User.objects.create_user(f"gone@{DOMAIN}", "Old-pass-12345", full_name="Gone", is_active=False)
        r = self.client.post(self.changelist, {
            "action": "reset_passwords", ACTION_CHECKBOX_NAME: [self.admin.pk, inactive.pk], "confirm": "yes"})
        self.assertRedirects(r, self.changelist)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Admin-pass-123"))

    def test_admin_setting_password_by_hand_forces_change(self):
        target = User.objects.create_user(f"h@{DOMAIN}", "Old-pass-12345", full_name="Hand")
        url = reverse("admin:auth_user_password_change", args=[target.pk])
        r = self.client.post(url, {"password1": "Set-by-admin-99", "password2": "Set-by-admin-99"})
        self.assertEqual(r.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.must_change_password)

    def test_no_delete(self):
        target = User.objects.create_user(f"d@{DOMAIN}", "x", full_name="D")
        r = self.client.get(reverse("admin:accounts_user_delete", args=[target.pk]))
        self.assertEqual(r.status_code, 403)
