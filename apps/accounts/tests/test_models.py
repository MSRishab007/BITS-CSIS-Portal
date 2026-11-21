from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User

DOMAIN = "pilani.bits-pilani.ac.in"


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class UserModelTests(TestCase):
    def test_create_faculty_defaults(self):
        u = User.objects.create_user(f"Ravi.Kumar@{DOMAIN.upper()}", "a-Strong-pass-123", full_name="Ravi Kumar")
        self.assertEqual(u.email, f"ravi.kumar@{DOMAIN}")  # normalised to lower case
        self.assertEqual(u.role, Role.FACULTY)
        self.assertFalse(u.is_staff)
        self.assertFalse(u.can_view_all_records)
        self.assertTrue(u.check_password("a-Strong-pass-123"))

    def test_user_without_password_cannot_log_in_with_password(self):
        u = User.objects.create_user(f"g@{DOMAIN}", full_name="Google Only")
        self.assertFalse(u.has_usable_password())

    def test_superuser_is_admin(self):
        u = User.objects.create_superuser(f"admin@{DOMAIN}", "a-Strong-pass-123", full_name="Admin")
        self.assertEqual(u.role, Role.ADMIN)
        self.assertTrue(u.is_portal_admin and u.can_manage_faculty and u.can_view_all_records)

    def test_hod_permissions(self):
        u = User.objects.create_user(f"hod@{DOMAIN}", "x", full_name="HoD", role=Role.HOD)
        self.assertTrue(u.can_view_all_records)
        self.assertTrue(u.can_manage_faculty)
        self.assertFalse(u.is_portal_admin)

    def test_other_domains_rejected(self):
        for bad in ("someone@gmail.com", "x@goa.bits-pilani.ac.in", "x@pilani.bits-pilani.ac.in.evil.com"):
            with self.subTest(email=bad), self.assertRaises(ValidationError):
                User.objects.create_user(bad, "x", full_name="X")

    def test_email_unique_case_insensitive(self):
        User.objects.create_user(f"dup@{DOMAIN}", "x", full_name="A")
        with self.assertRaises(ValidationError):
            User.objects.create_user(f"DUP@{DOMAIN}", "x", full_name="B")

    def test_employee_id_unique_only_when_set(self):
        User.objects.create_user(f"a@{DOMAIN}", "x", full_name="A")
        User.objects.create_user(f"b@{DOMAIN}", "x", full_name="B")  # both blank: allowed
        User.objects.create_user(f"c@{DOMAIN}", "x", full_name="C", employee_id="P123")
        with self.assertRaises(ValidationError):
            User.objects.create_user(f"d@{DOMAIN}", "x", full_name="D", employee_id="P123")

    def test_deactivation_timestamp(self):
        u = User.objects.create_user(f"t@{DOMAIN}", "x", full_name="T")
        u.is_active = False
        u.save()
        self.assertIsNotNone(u.deactivated_at)
        u.is_active = True
        u.save()
        self.assertIsNone(u.deactivated_at)


@override_settings(ALLOWED_EMAIL_DOMAINS=[DOMAIN])
class UsernameTests(TestCase):
    def test_username_defaults_to_email_local_part(self):
        u = User.objects.create_user(f"Ravi.Kumar@{DOMAIN}", "x", full_name="Ravi")
        self.assertEqual(u.username, "ravi.kumar")

    def test_username_collision_gets_number(self):
        User.objects.create_user(f"a@{DOMAIN}", "x", full_name="A", username="ravi")
        u = User.objects.create_user(f"ravi@{DOMAIN}", "x", full_name="Ravi")
        self.assertEqual(u.username, "ravi2")

    def test_username_lowercased_and_unique(self):
        User.objects.create_user(f"a@{DOMAIN}", "x", full_name="A", username="RKumar")
        self.assertTrue(User.objects.filter(username="rkumar").exists())
        with self.assertRaises(ValidationError):
            User.objects.create_user(f"b@{DOMAIN}", "x", full_name="B", username="rkumar")

    def test_username_rejects_at_sign_and_spaces(self):
        for i, bad in enumerate(("ravi@kumar", "ravi kumar", "r")):
            with self.subTest(username=bad), self.assertRaises(ValidationError):
                User.objects.create_user(f"u{i}@{DOMAIN}", "x", full_name="X", username=bad)

    def test_short_local_part_padded(self):
        u = User.objects.create_user(f"r@{DOMAIN}", "x", full_name="R")
        self.assertEqual(u.username, "ruser")


@override_settings(ALLOWED_EMAIL_DOMAINS=[])
class EmptyDomainListTests(TestCase):
    def test_any_domain_allowed_when_list_empty(self):
        User.objects.create_user("someone@gmail.com", "x", full_name="X")


class HealthCheckTests(TestCase):
    def test_healthz(self):
        r = self.client.get(reverse("core:healthz"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})
