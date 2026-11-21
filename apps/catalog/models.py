"""Lookup lists managed by Admin/HoD, plus admin-defined custom fields.

Lists are never hard-deleted once used: they are marked inactive so they
disappear from dropdowns but old purchases still show the right name.
"""
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify
from simple_history.models import HistoricalRecords

from apps.core.models import TimeStampedModel


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class LookupBase(TimeStampedModel):
    """Common shape for simple lookup lists."""

    name = models.CharField(max_length=120)
    is_active = models.BooleanField(
        "active", default=True, help_text="Inactive entries are hidden from dropdowns but kept on old records."
    )
    sort_order = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers are listed first.")

    objects = ActiveQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# Categories & types
# --------------------------------------------------------------------------
class Category(LookupBase):
    description = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta(LookupBase.Meta):
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(Lower("name"), name="unique_category_name_ci")]


class ItemType(LookupBase):
    """A type within a category, e.g. Gadgets → Keyboard."""

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="types")
    history = HistoricalRecords()

    class Meta(LookupBase.Meta):
        ordering = ["category__sort_order", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint("category", Lower("name"), name="unique_type_name_per_category_ci"),
        ]

    def __str__(self):
        return f"{self.category.name} › {self.name}"


# --------------------------------------------------------------------------
# Vendors
# --------------------------------------------------------------------------
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")


def normalize_vendor_name(name: str) -> str:
    """Key used to spot duplicates, so these all count as one vendor:
    'Dell India Pvt. Ltd.', 'DELL  India Pvt Ltd', 'dell india pvt ltd'
    """
    s = (name or "").lower().replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


class Vendor(TimeStampedModel):
    """Any signed-in user can add a vendor while entering a purchase.

    `name_key` (a normalised copy of the name) is unique, so the same vendor
    can't be added twice with different spacing, capitals or punctuation.
    """

    name = models.CharField(max_length=200)
    name_key = models.CharField(max_length=200, unique=True, editable=False)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField("active", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", editable=False,
    )
    history = HistoricalRecords()

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = _SPACES.sub(" ", (self.name or "").strip())
        self.name_key = normalize_vendor_name(self.name)
        if not self.name_key:
            raise ValidationError({"name": "Enter a vendor name."})
        clash = Vendor.objects.filter(name_key=self.name_key).exclude(pk=self.pk).first()
        if clash:
            raise ValidationError({"name": f'This vendor already exists as "{clash.name}".'})
        self.gstin = (self.gstin or "").strip().upper()

    def save(self, *args, **kwargs):
        self.name = _SPACES.sub(" ", (self.name or "").strip())
        self.name_key = normalize_vendor_name(self.name)
        self.gstin = (self.gstin or "").strip().upper()
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_by_name(cls, name: str, user=None):
        """Return the existing vendor matching `name`, or create it.

        Used by the "type a new vendor" box: typing 'dell india pvt ltd'
        picks the existing 'Dell India Pvt. Ltd.' instead of making a copy.
        """
        key = normalize_vendor_name(name)
        if not key:
            raise ValidationError("Enter a vendor name.")
        vendor, created = cls.objects.get_or_create(
            name_key=key,
            defaults={"name": _SPACES.sub(" ", name.strip()), "created_by": user},
        )
        return vendor, created


# --------------------------------------------------------------------------
# Funding & venues
# --------------------------------------------------------------------------
class FundingSource(LookupBase):
    requires_project_details = models.BooleanField(
        default=False,
        help_text="Ask for project/grant number and PI name (e.g. for Research Grant).",
    )
    history = HistoricalRecords()

    class Meta(LookupBase.Meta):
        constraints = [models.UniqueConstraint(Lower("name"), name="unique_funding_name_ci")]


class Venue(LookupBase):
    """Where an item is placed, e.g. 'Lab 6105' or 'Server Room'."""

    building = models.CharField(max_length=120, blank=True)
    history = HistoricalRecords()

    class Meta(LookupBase.Meta):
        constraints = [models.UniqueConstraint(Lower("name"), name="unique_venue_name_ci")]


# --------------------------------------------------------------------------
# Admin-defined custom fields
# --------------------------------------------------------------------------
class CustomField(TimeStampedModel):
    """An extra field the admin adds without code changes.

    Values are stored in the `extra` JSON column of the invoice or item,
    keyed by `key`. Forms, the Excel template and exports read this table.
    """

    class AppliesTo(models.TextChoices):
        PURCHASE = "PURCHASE", "Invoice (once per invoice)"
        ITEM = "ITEM", "Item (once per item)"

    class FieldType(models.TextChoices):
        TEXT = "TEXT", "Text"
        NUMBER = "NUMBER", "Number"
        DATE = "DATE", "Date"
        CHOICE = "CHOICE", "Dropdown"
        BOOLEAN = "BOOLEAN", "Yes / No"

    label = models.CharField(max_length=80)
    key = models.SlugField(
        max_length=50, unique=True, blank=True,
        help_text="Internal name; filled in from the label. Don't change it once data has been entered.",
    )
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.ITEM)
    field_type = models.CharField(max_length=10, choices=FieldType.choices, default=FieldType.TEXT)
    choices = models.TextField(blank=True, help_text="For dropdowns: one option per line.")
    required = models.BooleanField(default=False)
    help_text = models.CharField(max_length=200, blank=True)
    categories = models.ManyToManyField(
        Category, blank=True,
        help_text="Item fields only: show just for these categories. Leave empty for all.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField("active", default=True)
    history = HistoricalRecords(m2m_fields=[categories])

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["applies_to", "sort_order", "label"]

    def __str__(self):
        return f"{self.label} ({self.get_applies_to_display()})"

    @property
    def choice_list(self) -> list[str]:
        return [c.strip() for c in self.choices.splitlines() if c.strip()]

    def clean(self):
        super().clean()
        if not self.key:
            self.key = slugify(self.label).replace("-", "_")[:50]
        if self.field_type == self.FieldType.CHOICE and not self.choice_list:
            raise ValidationError({"choices": "Add at least one option for a dropdown."})

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = slugify(self.label).replace("-", "_")[:50]
        super().save(*args, **kwargs)

    # ---- Validation of submitted values --------------------------------
    def to_value(self, raw):
        """Convert raw input (form or Excel) to the stored JSON value.

        Returns None for empty input. Raises ValidationError if invalid.
        """
        import datetime
        from decimal import Decimal, InvalidOperation

        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        if self.field_type == self.FieldType.TEXT:
            return str(raw).strip()
        if self.field_type == self.FieldType.NUMBER:
            try:
                return str(Decimal(str(raw).replace(",", "").strip()))
            except InvalidOperation:
                raise ValidationError(f"{self.label}: enter a number.")
        if self.field_type == self.FieldType.DATE:
            if isinstance(raw, datetime.datetime):
                return raw.date().isoformat()
            if isinstance(raw, datetime.date):
                return raw.isoformat()
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    return datetime.datetime.strptime(str(raw).strip(), fmt).date().isoformat()
                except ValueError:
                    pass
            raise ValidationError(f"{self.label}: enter a date as DD-MM-YYYY.")
        if self.field_type == self.FieldType.CHOICE:
            match = {c.lower(): c for c in self.choice_list}.get(str(raw).strip().lower())
            if match is None:
                raise ValidationError(f"{self.label}: choose one of {', '.join(self.choice_list)}.")
            return match
        if self.field_type == self.FieldType.BOOLEAN:
            s = str(raw).strip().lower()
            if s in ("1", "true", "yes", "y", "on"):
                return True
            if s in ("0", "false", "no", "n", "off"):
                return False
            raise ValidationError(f"{self.label}: answer Yes or No.")
        return raw  # pragma: no cover


def custom_fields_for(applies_to: str, category=None):
    """Active custom fields for an invoice, or for an item of `category`."""
    qs = CustomField.objects.active().filter(applies_to=applies_to).prefetch_related("categories")
    if applies_to == CustomField.AppliesTo.ITEM and category is not None:
        qs = qs.filter(models.Q(categories__isnull=True) | models.Q(categories=category)).distinct()
    return qs


def clean_extra(applies_to: str, data: dict, category=None) -> dict:
    """Validate a dict of custom-field values; return what should be stored.

    Unknown keys are dropped. Raises ValidationError listing every problem.
    """
    data = data or {}
    cleaned, errors = {}, {}
    for field in custom_fields_for(applies_to, category):
        try:
            value = field.to_value(data.get(field.key))
        except ValidationError as e:
            errors[field.key] = e.messages
            continue
        if value is None:
            if field.required:
                errors[field.key] = [f"{field.label} is required."]
            continue
        cleaned[field.key] = value
    if errors:
        raise ValidationError(errors)
    return cleaned
