"""Forms for entering invoices and items.

* Vendor: pick an existing one (hidden `vendor` id) or type a new name
  (`vendor_name`). A typed name that matches an existing vendor (ignoring
  case, spaces and punctuation) uses that vendor instead of a duplicate.
* Custom fields: one form field per active CustomField, named
  `extra__<key>`. Values are validated and stored in the `extra` column.
"""
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from apps.catalog.models import (
    Category, CustomField, FundingSource, ItemType, Vendor, Venue, clean_extra, normalize_vendor_name,
)

from .models import Purchase, PurchaseItem

EXTRA_PREFIX = "extra__"
DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def active_or_current(queryset, current_id):
    """Active entries, plus the one already chosen (even if now inactive)."""
    qs = queryset.filter(is_active=True)
    if current_id:
        qs = queryset.filter(pk=current_id) | qs
    return qs.distinct()


def custom_form_field(cf: CustomField) -> forms.Field:
    """Build a form field for a CustomField.

    Always optional here: whether it's required can depend on the item's
    category, so `clean_extra` enforces that.
    """
    common = {"label": cf.label, "required": False, "help_text": cf.help_text}
    t = CustomField.FieldType
    if cf.field_type == t.NUMBER:
        return forms.DecimalField(**common)
    if cf.field_type == t.DATE:
        return forms.DateField(widget=DATE_WIDGET, **common)
    if cf.field_type == t.CHOICE:
        return forms.ChoiceField(choices=[("", "—")] + [(c, c) for c in cf.choice_list], **common)
    if cf.field_type == t.BOOLEAN:
        return forms.ChoiceField(choices=[("", "—"), ("yes", "Yes"), ("no", "No")], **common)
    return forms.CharField(max_length=500, **common)


class CustomFieldsMixin:
    """Adds `extra__<key>` fields and copies their values into `extra`."""

    applies_to: str = ""

    def add_custom_fields(self):
        self.custom_fields = list(
            CustomField.objects.active().filter(applies_to=self.applies_to).prefetch_related("categories")
        )
        stored = self.instance.extra or {}
        for cf in self.custom_fields:
            name = EXTRA_PREFIX + cf.key
            self.fields[name] = custom_form_field(cf)
            value = stored.get(cf.key)
            if cf.field_type == CustomField.FieldType.BOOLEAN and value is not None:
                value = "yes" if value else "no"
            self.initial.setdefault(name, value)

    def extra_bound_fields(self):
        """[(bound field, CustomField)] for templates."""
        return [(self[EXTRA_PREFIX + cf.key], cf) for cf in self.custom_fields]

    def clean_custom_fields(self, category=None):
        raw = {cf.key: self.cleaned_data.get(EXTRA_PREFIX + cf.key) for cf in self.custom_fields}
        # Errors are attached to each extra__<key> field here, so the model
        # doesn't need to check (and report) the same values again.
        self.instance._extra_checked_by_form = True
        try:
            self.instance.extra = clean_extra(self.applies_to, raw, category=category)
        except ValidationError as e:
            for key, messages in e.message_dict.items():
                self.add_error(EXTRA_PREFIX + key, messages)


class PurchaseForm(CustomFieldsMixin, forms.ModelForm):
    applies_to = CustomField.AppliesTo.PURCHASE

    vendor = forms.ModelChoiceField(queryset=Vendor.objects.all(), required=False, widget=forms.HiddenInput)
    vendor_name = forms.CharField(label="Vendor", max_length=200, required=False)

    class Meta:
        model = Purchase
        fields = ("owner", "vendor", "invoice_number", "order_number", "purchase_date", "delivery_date",
                  "bill_amount", "bill_file", "remarks")
        widgets = {
            "purchase_date": DATE_WIDGET,
            "delivery_date": DATE_WIDGET,
            "remarks": forms.Textarea(attrs={"rows": 2}),
            "invoice_number": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.can_view_all_records:
            # Admin/HoD can record a purchase on behalf of a faculty member.
            User = get_user_model()
            self.fields["owner"].queryset = active_or_current(User.objects.all(), self.instance.owner_id)
            self.fields["owner"].label = "Purchased by"
            self.fields["owner"].label_from_instance = lambda u: f"{u.full_name} ({u.username})"
            if not self.instance.pk:
                self.initial.setdefault("owner", user.pk)
        else:
            del self.fields["owner"]
            if not self.instance.pk:
                self.instance.owner = user
        self.fields["vendor"].queryset = active_or_current(Vendor.objects.all(), self.instance.vendor_id)
        if self.instance.vendor_id:
            self.initial.setdefault("vendor_name", self.instance.vendor.name)
        self.fields["bill_amount"].widget.attrs.update({"step": "0.01", "min": "0", "inputmode": "decimal"})
        self.add_custom_fields()

    def clean(self):
        cleaned = super().clean()
        vendor = cleaned.get("vendor")
        name = (cleaned.get("vendor_name") or "").strip()

        if vendor is not None and normalize_vendor_name(name) not in ("", vendor.name_key):
            # The user picked a vendor, then edited the text: treat as typed name.
            vendor = None
        if vendor is None:
            if not normalize_vendor_name(name):
                self.add_error("vendor_name", "Choose a vendor or type a new vendor name.")
            else:
                # Uses the existing vendor if the name matches one; otherwise
                # creates it. The view runs inside a transaction, so if the
                # form has other errors this new vendor is rolled back.
                vendor, created = Vendor.get_or_create_by_name(name, user=self.user)
                self.vendor_created = created
        cleaned["vendor"] = vendor
        if vendor is not None:
            self.instance.vendor = vendor
        self.clean_custom_fields()
        return cleaned


class PurchaseItemForm(CustomFieldsMixin, forms.ModelForm):
    applies_to = CustomField.AppliesTo.ITEM

    class Meta:
        model = PurchaseItem
        fields = ("category", "item_type", "item_name", "quantity", "amount", "funding_source", "project_number",
                  "principal_investigator", "venue", "serial_numbers", "asset_tag", "warranty_end_date", "status",
                  "remarks")
        widgets = {
            "warranty_end_date": DATE_WIDGET,
            "serial_numbers": forms.Textarea(attrs={"rows": 2, "placeholder": "One per line"}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        self.fields["category"].queryset = active_or_current(Category.objects.all(), inst.category_id)
        self.fields["item_type"].queryset = active_or_current(
            ItemType.objects.select_related("category"), inst.item_type_id)
        self.fields["funding_source"].queryset = active_or_current(FundingSource.objects.all(),
                                                                   inst.funding_source_id)
        self.fields["venue"].queryset = active_or_current(Venue.objects.all(), inst.venue_id)
        self.fields["venue"].required = False
        self.fields["venue"].empty_label = "Not specified"
        self.fields["amount"].widget.attrs.update({"step": "0.01", "min": "0", "inputmode": "decimal"})
        self.fields["quantity"].widget.attrs.update({"min": "1"})
        # Bind to the row's Alpine.js state (see static/js/purchase-form.js).
        self.fields["category"].widget.attrs["x-model"] = "category"
        self.fields["funding_source"].widget.attrs["x-model"] = "funding"
        self.fields["item_name"].widget.attrs["x-model"] = "name"
        self.add_custom_fields()

    def clean(self):
        cleaned = super().clean()
        self.clean_custom_fields(category=cleaned.get("category"))
        return cleaned


class BaseItemFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        tags = [f.cleaned_data.get("asset_tag") for f in self.forms
                if f.cleaned_data and not self._should_delete_form(f) and f.cleaned_data.get("asset_tag")]
        if len(tags) != len(set(tags)):
            raise ValidationError("Two items have the same asset tag.")


ItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm, formset=BaseItemFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True,
)
