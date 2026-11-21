"""Invoices (Purchase) and the items on them (PurchaseItem).

One invoice from one vendor can carry several items, each with its own
category, funding source, venue, warranty and remarks.
"""
import datetime
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor, Venue, clean_extra
from apps.core.models import TimeStampedModel

from .validators import validate_bill_file


def bill_upload_to(instance, filename):
    """bills/2026/3f2c…e1.pdf — a random name, so file URLs can't be guessed."""
    ext = os.path.splitext(filename)[1].lower()
    return f"bills/{timezone.now():%Y}/{uuid.uuid4().hex}{ext}"


class PurchaseQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Admin/HoD see every invoice; faculty see only their own."""
        if not user.is_authenticated:
            return self.none()
        if user.can_view_all_records:
            return self
        return self.filter(owner=user)

    def owned_by(self, user):
        """Only `user`'s own invoices, whatever their role.

        Used by the "add to one of my past invoices" picker.
        """
        return self.filter(owner=user)


class Purchase(TimeStampedModel):
    """One invoice/bill."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchases",
        help_text="Faculty member this purchase belongs to.",
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchases")
    invoice_number = models.CharField(max_length=60)
    order_number = models.CharField("order / PO number", max_length=60, blank=True)
    purchase_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    bill_amount = models.DecimalField(
        "bill amount (₹)", max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Total amount on the bill, including tax.",
    )
    bill_file = models.FileField(
        upload_to=bill_upload_to, blank=True, validators=[validate_bill_file],
        help_text="Optional. PDF, JPG, PNG or WEBP, up to 10 MB.",
    )
    remarks = models.TextField(blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="Values of admin-defined custom fields.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", editable=False,
    )

    history = HistoricalRecords()
    objects = PurchaseQuerySet.as_manager()

    class Meta:
        ordering = ["-purchase_date", "-id"]
        constraints = [
            # The same bill can't be recorded twice (case-insensitive).
            models.UniqueConstraint("vendor", Lower("invoice_number"), name="unique_invoice_per_vendor_ci"),
        ]
        indexes = [models.Index(fields=["owner", "-purchase_date"])]

    def __str__(self):
        return f"{self.invoice_number} · {self.vendor} · {self.purchase_date:%d %b %Y}"

    def clean(self):
        super().clean()
        self.invoice_number = (self.invoice_number or "").strip()
        self.order_number = (self.order_number or "").strip()
        today = timezone.localdate()
        errors = {}
        if self.purchase_date and self.purchase_date > today:
            errors["purchase_date"] = "Purchase date can't be in the future."
        if self.purchase_date and self.delivery_date and self.delivery_date < self.purchase_date:
            errors["delivery_date"] = "Delivery date can't be before the purchase date."
        if self.vendor_id and self.invoice_number:
            clash = (Purchase.objects.filter(vendor_id=self.vendor_id, invoice_number__iexact=self.invoice_number)
                     .exclude(pk=self.pk).select_related("owner").first())
            if clash:
                who = "you" if clash.owner_id == self.owner_id else clash.owner.full_name
                errors["invoice_number"] = (
                    f"Invoice {clash.invoice_number} from {self.vendor} is already recorded by {who}."
                )
        try:
            self.extra = clean_extra(CustomField.AppliesTo.PURCHASE, self.extra)
        except ValidationError as e:
            errors["extra"] = e.messages
        if errors:
            raise ValidationError(errors)

    @property
    def items_total(self) -> Decimal:
        return self.items.aggregate(t=Sum("amount"))["t"] or Decimal("0")


class PurchaseItemQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.can_view_all_records:
            return self
        return self.filter(purchase__owner=user)

    def warranty_expiring(self, within_days=30):
        today = timezone.localdate()
        return self.filter(
            warranty_end_date__gte=today,
            warranty_end_date__lte=today + datetime.timedelta(days=within_days),
        )


class PurchaseItem(TimeStampedModel):
    class Status(models.TextChoices):
        IN_USE = "IN_USE", "In use"
        IN_STORE = "IN_STORE", "In store / not deployed"
        UNDER_REPAIR = "REPAIR", "Under repair"
        TRANSFERRED = "TRANSFERRED", "Transferred"
        DISPOSED = "DISPOSED", "Disposed / written off"

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    item_type = models.ForeignKey(ItemType, on_delete=models.PROTECT, related_name="items", verbose_name="type")
    item_name = models.CharField(max_length=200, help_text="Make and model, e.g. 'Dell Precision 3660'.")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    amount = models.DecimalField(
        "amount (₹)", max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Optional: this item's total cost (all units).",
    )

    funding_source = models.ForeignKey(FundingSource, on_delete=models.PROTECT, related_name="items")
    project_number = models.CharField("project / grant no.", max_length=60, blank=True)
    principal_investigator = models.CharField("PI name", max_length=120, blank=True)

    venue = models.ForeignKey(Venue, on_delete=models.SET_NULL, null=True, blank=True, related_name="items")
    serial_numbers = models.TextField(blank=True, help_text="One per line.")
    asset_tag = models.CharField(max_length=60, blank=True)
    warranty_end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_USE)
    remarks = models.TextField(blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="Values of admin-defined custom fields.")

    history = HistoricalRecords()
    objects = PurchaseItemQuerySet.as_manager()

    class Meta:
        ordering = ["purchase", "id"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["warranty_end_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_tag"], condition=~Q(asset_tag=""), name="unique_asset_tag_when_set",
            ),
        ]

    def __str__(self):
        return f"{self.item_name} × {self.quantity}"

    def clean(self):
        super().clean()
        errors = {}
        if self.item_type_id and self.category_id and self.item_type.category_id != self.category_id:
            errors["item_type"] = f"'{self.item_type.name}' is not a type under {self.category.name}."
        if self.funding_source_id and self.funding_source.requires_project_details and not self.project_number.strip():
            errors["project_number"] = f"Project / grant number is required for {self.funding_source.name}."
        if (self.warranty_end_date and self.purchase_id and self.purchase.purchase_date
                and self.warranty_end_date < self.purchase.purchase_date):
            errors["warranty_end_date"] = "Warranty can't end before the purchase date."
        try:
            self.extra = clean_extra(
                CustomField.AppliesTo.ITEM, self.extra,
                category=self.category if self.category_id else None,
            )
        except ValidationError as e:
            errors["extra"] = e.messages
        if errors:
            raise ValidationError(errors)

    @property
    def serial_number_list(self) -> list[str]:
        return [s.strip() for s in self.serial_numbers.splitlines() if s.strip()]
