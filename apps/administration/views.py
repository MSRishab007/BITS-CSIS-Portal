from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.response import TemplateResponse
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.models import Role, User
from apps.accounts.passwords import generate_password, set_generated_password
from apps.catalog.models import Category, CustomField, FundingSource, ItemType, Vendor, Venue

from . import forms
from .permissions import can_manage_user, manager_required


def _credentials_page(request, creds, title):
    """Show generated passwords once. Never cached, never stored."""
    response = TemplateResponse(request, "administration/credentials.html", {"credentials": creds, "title": title})
    add_never_cache_headers(response)
    return response


# ==========================================================================
# People
# ==========================================================================
@manager_required
def people_list(request):
    status = request.GET.get("status", "active")
    role = request.GET.get("role", "")
    q = request.GET.get("q", "").strip()
    people = User.objects.annotate(invoice_count=Count("purchases"))
    if status == "active":
        people = people.filter(is_active=True)
    elif status == "inactive":
        people = people.filter(is_active=False)
    if role in Role.values:
        people = people.filter(role=role)
    if q:
        people = people.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q)
                               | Q(employee_id__icontains=q))
    rows = [(p, can_manage_user(request.user, p)) for p in people.order_by("full_name")]
    return render(request, "administration/people_list.html", {
        "rows": rows, "status": status, "role": role, "q": q, "roles": Role.choices,
        "lists": LISTS, "section": "people",
        "counts": {
            "active": User.objects.filter(is_active=True).count(),
            "inactive": User.objects.filter(is_active=False).count(),
        },
    })


@manager_required
@require_http_methods(["GET", "POST"])
def person_add(request):
    form = forms.PersonForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.created_by = request.user
        password = generate_password()
        user.set_password(password)
        user.must_change_password = True
        user.save()
        return _credentials_page(request, [(user, password)], f"{user.full_name} added")
    return render(request, "administration/person_form.html", {"form": form, "mode": "add"})


@manager_required
@require_http_methods(["GET", "POST"])
def people_bulk_add(request):
    form = forms.BulkPeopleForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        creds = []
        with transaction.atomic():
            for p in form.cleaned_data["lines"]:
                user = User(full_name=p["full_name"], email=p["email"], role=p["role"], created_by=request.user)
                user.full_clean(exclude=["password", "username"])
                password = generate_password()
                user.set_password(password)
                user.must_change_password = True
                user.save()
                creds.append((user, password))
        return _credentials_page(request, creds, f"{len(creds)} people added")
    return render(request, "administration/people_bulk_add.html", {"form": form})


def _get_manageable(request, pk):
    person = get_object_or_404(User, pk=pk)
    if not can_manage_user(request.user, person):
        raise PermissionDenied
    return person


@manager_required
@require_http_methods(["GET", "POST"])
def person_edit(request, pk):
    person = _get_manageable(request, pk)
    form = forms.PersonForm(request.POST or None, instance=person, actor=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{person.full_name}'s details saved.")
        return redirect("administration:people")
    return render(request, "administration/person_form.html", {
        "form": form, "mode": "edit", "person": person,
        "history": person.history.select_related("history_user")[:15],
    })


@manager_required
@require_POST
def person_toggle_active(request, pk):
    person = _get_manageable(request, pk)
    if person.pk == request.user.pk:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("administration:people")
    person.is_active = not person.is_active
    person.save()
    if person.is_active:
        messages.success(request, f"{person.full_name} can sign in again.")
    else:
        messages.success(request, f"{person.full_name} has been deactivated. Their purchase records are kept.")
    return redirect("administration:people")


@manager_required
@require_http_methods(["GET", "POST"])
def person_reset_password(request, pk):
    person = _get_manageable(request, pk)
    if person.pk == request.user.pk:
        messages.error(request, "To change your own password, use 'Password' at the bottom of the menu.")
        return redirect("administration:people")
    if not person.is_active:
        messages.error(request, "Reactivate this account before resetting its password.")
        return redirect("administration:people")
    if request.method == "POST":
        return _credentials_page(request, [(person, set_generated_password(person))],
                                 f"New password for {person.full_name}")
    return render(request, "administration/confirm.html", {
        "title": f"Reset {person.full_name}'s password?",
        "text": "A new temporary password will be generated and shown once. Their current password stops working "
                "immediately, and they'll choose a new one at next sign-in.",
        "button": "Generate new password",
        "cancel_url": "administration:people",
    })


# ==========================================================================
# Lookup lists
# ==========================================================================
LISTS = {
    "categories": {
        "model": Category, "form": forms.CategoryForm, "title": "Categories", "singular": "category",
        "help": "Major groups of purchases. Open a category to manage its types.",
        "usage": "items",
    },
    "funding": {
        "model": FundingSource, "form": forms.FundingSourceForm, "title": "Funding sources",
        "singular": "funding source", "help": "Where the money came from. Shown on every item.", "usage": "items",
    },
    "venues": {
        "model": Venue, "form": forms.VenueForm, "title": "Venues", "singular": "venue",
        "help": "Labs and rooms where items are placed.", "usage": "items",
    },
    "vendors": {
        "model": Vendor, "form": forms.VendorForm, "title": "Vendors", "singular": "vendor",
        "help": "Faculty can also add vendors while entering a purchase. Fix spellings or add GSTIN here.",
        "usage": "purchases",
    },
    "fields": {
        "model": CustomField, "form": forms.CustomFieldForm, "title": "Custom fields", "singular": "custom field",
        "help": "Extra fields shown on the entry form, the Excel template and exports. No code changes needed.",
        "usage": None,
    },
}


def _list_config(kind):
    if kind not in LISTS:
        raise Http404
    return LISTS[kind]


@manager_required
def lookup_list(request, kind="categories"):
    cfg = _list_config(kind)
    qs = cfg["model"].objects.all()
    if cfg["usage"]:
        qs = qs.annotate(usage=Count(cfg["usage"], distinct=True))
    if kind == "categories":
        qs = qs.annotate(type_count=Count("types", distinct=True))
    if kind == "fields":
        qs = qs.prefetch_related("categories")
    q = request.GET.get("q", "").strip()
    if q:
        field = "label" if kind == "fields" else "name"
        qs = qs.filter(**{f"{field}__icontains": q})
    show = request.GET.get("show", "all")
    if show == "active":
        qs = qs.filter(is_active=True)
    elif show == "hidden":
        qs = qs.filter(is_active=False)
    order = ("name",) if kind == "vendors" else (("applies_to", "sort_order", "label") if kind == "fields"
                                                 else ("sort_order", "name"))
    return render(request, "administration/lookup_list.html", {
        "kind": kind, "cfg": cfg, "objects": qs.order_by(*order), "lists": LISTS, "q": q, "show": show,
    })


@manager_required
@require_http_methods(["GET", "POST"])
def lookup_edit(request, kind, pk=None):
    cfg = _list_config(kind)
    obj = get_object_or_404(cfg["model"], pk=pk) if pk else cfg["model"]()
    form = cfg["form"](request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if kind == "vendors" and not saved.pk:
            saved.created_by = request.user
        saved.save()
        form.save_m2m()
        messages.success(request, f"{cfg['singular'].capitalize()} “{saved}” saved.")
        if kind == "categories" and not pk:
            return redirect("administration:lookup_edit", kind=kind, pk=saved.pk)  # go on to add its types
        return redirect("administration:lookups", kind=kind)
    context = {"kind": kind, "cfg": cfg, "form": form, "obj": obj, "lists": LISTS}
    if kind == "categories" and obj.pk:
        context["types"] = obj.types.annotate(usage=Count("items")).order_by("sort_order", "name")
        context["type_form"] = forms.ItemTypeForm(category=obj, prefix="type")
    if obj.pk and hasattr(obj, "history"):
        context["history"] = obj.history.select_related("history_user")[:10]
    return render(request, "administration/lookup_form.html", context)


@manager_required
@require_POST
def lookup_toggle(request, kind, pk):
    cfg = _list_config(kind)
    obj = get_object_or_404(cfg["model"], pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    state = "shown again in dropdowns" if obj.is_active else "hidden from dropdowns (old records keep it)"
    messages.success(request, f"“{obj}” is {state}.")
    return redirect("administration:lookups", kind=kind)


@manager_required
@require_http_methods(["POST"])
def type_add(request, category_pk):
    category = get_object_or_404(Category, pk=category_pk)
    form = forms.ItemTypeForm(request.POST, category=category, prefix="type")
    if form.is_valid():
        form.save()
        messages.success(request, f"Type “{form.instance.name}” added to {category.name}.")
    else:
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
    return redirect("administration:lookup_edit", kind="categories", pk=category.pk)


@manager_required
@require_http_methods(["GET", "POST"])
def type_edit(request, pk):
    item_type = get_object_or_404(ItemType.objects.select_related("category"), pk=pk)
    form = forms.ItemTypeForm(request.POST or None, instance=item_type, category=item_type.category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Type “{item_type.name}” saved.")
        return redirect("administration:lookup_edit", kind="categories", pk=item_type.category_id)
    return render(request, "administration/type_form.html", {"form": form, "item_type": item_type, "lists": LISTS})


@manager_required
@require_POST
def type_toggle(request, pk):
    item_type = get_object_or_404(ItemType, pk=pk)
    item_type.is_active = not item_type.is_active
    item_type.save()
    messages.success(request, f"Type “{item_type.name}” is {'shown' if item_type.is_active else 'hidden'}.")
    return redirect("administration:lookup_edit", kind="categories", pk=item_type.category_id)
