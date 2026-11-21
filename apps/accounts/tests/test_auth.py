import re

from axes.models import AccessAttempt
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.passwords import generate_password, set_generated_password

DOMAIN = "pilani.bits-pilani.ac.in"
PASSWORD = "Correct-horse-42"


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(f"ravi.kumar@{DOMAIN}", PASSWORD, full_name="Ravi Kumar")
        self.url = reverse("accounts:login")

    def login(self, identifier, password=PASSWORD):
        return self.client.post(self.url, {"username": identifier, "password": password})

    def test_login_with_email(self):
        r = self.login(f"ravi.kumar@{DOMAIN}")
        self.assertRedirects(r, reverse("core:home"))

    def test_login_with_username_any_case(self):
        r = self.login("Ravi.Kumar")
        self.assertRedirects(r, reverse("core:home"))

    def test_wrong_password(self):
        r = self.login("ravi.kumar", "nope")
        self.assertContains(r, "Incorrect email/username or password.")

    def test_unknown_user(self):
        r = self.login("nobody")
        self.assertContains(r, "Incorrect email/username or password.")

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        r = self.login("ravi.kumar")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_home_requires_login(self):
        r = self.client.get(reverse("core:home"))
        self.assertRedirects(r, f"{self.url}?next=/")

    def test_lockout_after_five_failures_counts_email_and_username_together(self):
        for i in range(5):
            # alternate between username and email: all count against one account
            self.login("ravi.kumar" if i % 2 else f"RAVI.KUMAR@{DOMAIN}", "wrong")
        r = self.login("ravi.kumar")  # correct password, but locked
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Too many sign-in attempts", status_code=429)
        self.assertEqual(AccessAttempt.objects.get().username, f"ravi.kumar@{DOMAIN}")

    def test_success_resets_failure_count(self):
        for _ in range(4):
            self.login("ravi.kumar", "wrong")
        self.assertRedirects(self.login("ravi.kumar"), reverse("core:home"))
        self.client.logout()
        for _ in range(4):
            self.login("ravi.kumar", "wrong")
        self.assertRedirects(self.login("ravi.kumar"), reverse("core:home"))


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class ForcedPasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(f"new@{DOMAIN}", full_name="New Person")
        self.temp = set_generated_password(self.user)

    def test_generated_password_works_and_forces_change(self):
        r = self.client.post(reverse("accounts:login"), {"username": "new", "password": self.temp})
        self.assertRedirects(r, reverse("core:home"), target_status_code=302)
        # every page sends them to the change-password page
        for url in (reverse("core:home"), reverse("admin:index")):
            self.assertRedirects(self.client.get(url), reverse("accounts:password_change"))
        # healthz still works
        self.assertEqual(self.client.get(reverse("core:healthz")).status_code, 200)

    def test_changing_password_clears_flag(self):
        self.client.post(reverse("accounts:login"), {"username": "new", "password": self.temp})
        r = self.client.post(reverse("accounts:password_change"), {
            "old_password": self.temp,
            "new_password1": "My-own-pass-2026",
            "new_password2": "My-own-pass-2026",
        })
        self.assertRedirects(r, reverse("core:home"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password("My-own-pass-2026"))
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)


class PasswordGeneratorTests(TestCase):
    def test_format_and_character_mix(self):
        seen = set()
        for _ in range(200):
            p = generate_password()
            self.assertRegex(p, r"^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$")
            raw = p.replace("-", "")
            self.assertTrue(re.search(r"[A-Z]", raw) and re.search(r"[a-z]", raw) and re.search(r"\d", raw))
            self.assertFalse(set(raw) & set("0O1lI5S2Z8B"))
            seen.add(p)
        self.assertEqual(len(seen), 200)  # no repeats

    def test_passes_django_password_validators(self):
        from django.contrib.auth.password_validation import validate_password
        validate_password(generate_password())  # raises if invalid
