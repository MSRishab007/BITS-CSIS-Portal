import re

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from .managers import UserManager
from .validators import validate_allowed_email_domain


USERNAME_RE = r"^[a-z0-9._-]{2,40}$"
username_validator = RegexValidator(
    USERNAME_RE,
    "Use 2–40 characters: lower-case letters, digits, '.', '_' or '-'. No '@'.",
)


def username_from_email(email: str) -> str:
    """'Ravi.Kumar+x@pilani.bits-pilani.ac.in' -> 'ravi.kumarx'."""
    local = (email or "").split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9._-]", "", local)[:40]


class LowercaseCharField(models.CharField):
    """CharField that trims and lower-cases its value before validation,
    so 'RKumar ' is accepted and stored as 'rkumar'."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.strip().lower() if isinstance(value, str) else value


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    HOD = "HOD", "Head of Department"
    FACULTY = "FACULTY", "Faculty"


class User(AbstractBaseUser, PermissionsMixin):
    """A portal user, identified by their institute email address.

    Login methods:
      * email + password (now)
      * Google sign-in (later). Google accounts will be linked by email in a
        separate table, so this table will not need to change. A user created
        without a password can only sign in once Google login is enabled or an
        admin sets a password.

    Users are never deleted: removing someone from the department sets
    is_active=False so their purchase records keep a valid owner.
    """

    email = models.EmailField(
        "email address",
        unique=True,
        validators=[validate_allowed_email_domain],
        help_text="Institute email address; used to sign in.",
    )
    username = LowercaseCharField(
        max_length=40,
        unique=True,
        blank=True,
        validators=[username_validator],
        help_text="Short sign-in name. Leave blank to use the part of the email before '@'.",
    )
    full_name = models.CharField(max_length=150)
    employee_id = models.CharField(
        "employee ID / PSRN",
        max_length=30,
        blank=True,
        help_text="Optional staff number.",
    )
    designation = models.CharField(max_length=100, blank=True)
    phone = models.CharField(
        max_length=15,
        blank=True,
        validators=[RegexValidator(r"^\+?[0-9 \-]{7,15}$", "Enter a valid phone number.")],
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.FACULTY)

    is_active = models.BooleanField(
        "active",
        default=True,
        help_text="Unticking this removes the person from the portal without deleting their records.",
    )
    is_staff = models.BooleanField(
        "Django admin access",
        default=False,
        help_text="Allows signing in to the technical /admin/ site.",
    )

    must_change_password = models.BooleanField(
        default=False,
        help_text="Set when a password is generated; the user must choose their own at next sign-in.",
    )

    date_joined = models.DateTimeField(default=timezone.now)
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]
        constraints = [
            # A staff number, when given, must be unique.
            models.UniqueConstraint(
                fields=["employee_id"],
                condition=~models.Q(employee_id=""),
                name="unique_employee_id_when_set",
            ),
        ]
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.username = (self.username or "").strip().lower()
        if not self.username:
            self.username = self._unique_username(username_from_email(self.email))
        # Record when an account is deactivated / reactivated.
        if not self.is_active and self.deactivated_at is None:
            self.deactivated_at = timezone.now()
        elif self.is_active and self.deactivated_at is not None:
            self.deactivated_at = None
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.email = (self.email or "").strip().lower()
        self.username = (self.username or "").strip().lower()

    def _unique_username(self, base: str) -> str:
        """Return `base`, or `base2`, `base3`… if it is already taken."""
        if len(base) < 2:
            base = f"{base}user"
        candidate, n = base, 1
        taken = User.objects.exclude(pk=self.pk)
        while taken.filter(username=candidate).exists():
            n += 1
            suffix = str(n)
            candidate = base[: 40 - len(suffix)] + suffix
        return candidate

    # Names used by Django's auth helpers
    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email

    # ---- Role helpers: the single place permissions are decided ----------
    @property
    def is_portal_admin(self) -> bool:
        return self.is_superuser or self.role == Role.ADMIN

    @property
    def is_hod(self) -> bool:
        return self.role == Role.HOD

    @property
    def can_view_all_records(self) -> bool:
        """Admin and HoD see every faculty member's purchases."""
        return self.is_portal_admin or self.is_hod

    @property
    def can_manage_faculty(self) -> bool:
        """Admin and HoD can add, deactivate and reactivate faculty."""
        return self.is_portal_admin or self.is_hod

    @property
    def can_manage_settings(self) -> bool:
        """Categories, funding sources, custom fields, etc."""
        return self.is_portal_admin or self.is_hod
