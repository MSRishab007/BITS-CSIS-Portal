import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.accounts.models import Role, User
from apps.accounts.validators import validate_allowed_email_domain
from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor, Venue

from .permissions import assignable_roles


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------
class PersonForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("full_name", "email", "username", "role", "employee_id", "designation", "phone")
        help_texts = {"username": "Leave blank to use the part of the email before '@'."}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["role"].choices = assignable_roles(actor)
        self.fields["username"].required = False
        if self.instance.pk and self.instance.pk == actor.pk:
            # You can't change your own role here.
            self.fields["role"].disabled = True


class BulkPeopleForm(forms.Form):
    """Paste one person per line: 'Full name, email' (optionally ', role')."""

    lines = forms.CharField(
        label="People to add",
        widget=forms.Textarea(attrs={"rows": 8, "placeholder": "Ravi Kumar, ravi.kumar@pilani.bits-pilani.ac.in\n"
                                                               "Anita Sharma, anita.sharma@pilani.bits-pilani.ac.in, HoD"}),
        help_text="One person per line: name, email. Add a third value 'HoD' to make someone HoD. "
                  "You can paste two columns straight from Excel.",
    )

    ROLE_WORDS = {"faculty": Role.FACULTY, "hod": Role.HOD, "head of department": Role.HOD, "admin": Role.ADMIN}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

    def clean_lines(self):
        people, errors, seen = [], [], set()
        allowed_roles = {v for v, _ in assignable_roles(self.actor)}
        for n, raw in enumerate(self.cleaned_data["lines"].splitlines(), start=1):
            if not raw.strip():
                continue
            parts = [p.strip() for p in re.split(r"[,\t;]", raw) if p.strip()]
            if len(parts) < 2:
                errors.append(f"Line {n}: expected 'name, email'.")
                continue
            # Accept either order: find the part that looks like an email.
            email_idx = next((i for i, p in enumerate(parts[:2]) if "@" in p), None)
            if email_idx is None:
                errors.append(f"Line {n}: no email address found.")
                continue
            email = parts[email_idx].lower()
            name = parts[1 - email_idx]
            role = Role.FACULTY
            if len(parts) > 2:
                role = self.ROLE_WORDS.get(parts[2].lower())
                if role is None or role not in allowed_roles:
                    errors.append(f"Line {n}: unknown or not allowed role '{parts[2]}'.")
                    continue
            try:
                validate_email(email)
                validate_allowed_email_domain(email)
            except ValidationError as e:
                errors.append(f"Line {n}: {email}: {' '.join(e.messages)}")
                continue
            if email in seen:
                errors.append(f"Line {n}: {email} is listed twice.")
                continue
            if User.objects.filter(email=email).exists():
                errors.append(f"Line {n}: {email} already has an account.")
                continue
            seen.add(email)
            people.append({"full_name": name, "email": email, "role": role})
        if errors:
            raise ValidationError(errors)
        if not people:
            raise ValidationError("Paste at least one person.")
        return people


# --------------------------------------------------------------------------
# Lookup lists
# --------------------------------------------------------------------------
class UniqueNameMixin:
    """Friendly 'already exists' message for case-insensitive unique names."""

    def unique_name_queryset(self):
        return type(self.instance).objects.all()

    def clean_name(self):
        name = re.sub(r"\s+", " ", self.cleaned_data["name"].strip())
        clash = self.unique_name_queryset().filter(name__iexact=name).exclude(pk=self.instance.pk).first()
        if clash:
            raise ValidationError(f"“{clash.name}” already exists."
                                  + ("" if clash.is_active else " It is hidden: show it again instead."))
        return name


class CategoryForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description", "sort_order", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class ItemTypeForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = ItemType
        fields = ("name", "sort_order", "is_active")

    def __init__(self, *args, category, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.category = category

    def unique_name_queryset(self):
        return ItemType.objects.filter(category=self.instance.category)


class FundingSourceForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = FundingSource
        fields = ("name", "requires_project_details", "sort_order", "is_active")
        labels = {"requires_project_details": "Ask for project / grant number and PI"}


class VenueForm(UniqueNameMixin, forms.ModelForm):
    class Meta:
        model = Venue
        fields = ("name", "building", "sort_order", "is_active")


class VendorForm(forms.ModelForm):
    """Duplicate check lives in Vendor.clean (ignores case/spaces/punctuation)."""

    class Meta:
        model = Vendor
        fields = ("name", "gstin", "contact_person", "phone", "email", "address", "is_active")
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class CustomFieldForm(forms.ModelForm):
    class Meta:
        model = CustomField
        fields = ("label", "applies_to", "field_type", "choices", "required", "help_text", "categories",
                  "sort_order", "is_active")
        widgets = {
            "choices": forms.Textarea(attrs={"rows": 3, "placeholder": "One option per line"}),
            "categories": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categories"].queryset = Category.objects.active()
        self.fields["categories"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("applies_to") == CustomField.AppliesTo.PURCHASE and cleaned.get("categories"):
            self.add_error("categories", "Categories only apply to item fields. Clear them for an invoice field.")
        if not self.instance.pk and cleaned.get("label"):
            from django.utils.text import slugify
            key = slugify(cleaned["label"]).replace("-", "_")[:50]
            if not key:
                self.add_error("label", "Use letters or numbers in the label.")
            elif CustomField.objects.filter(key=key).exists():
                self.add_error("label", "A field with this name already exists (it may be hidden).")
        return cleaned
