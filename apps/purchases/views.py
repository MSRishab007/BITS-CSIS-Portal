import os
from itertools import chain

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from apps.catalog.models import Category, CustomField, FundingSource, Vendor, normalize_vendor_name
from apps.core.templatetags.portal_tags import inr

from .forms import ItemFormSet, PurchaseForm
from .models import Purchase, PurchaseItem, can_edit_purchase


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _form_context():
    """Lookup data the entry form's JavaScript needs (embedded as JSON)."""
    categories = Category.objects.active().prefetch_related("types")
    return {
        "categories": [
            {"id": c.id, "name": c.name,
             "types": [{"id": t.id, "name": t.name} for t in c.types.all() if t.is_active]}
            for c in categories
        ],
        "project_funding_ids": list(
            FundingSource.objects.filter(requires_project_details=True).values_list("id", flat=True)
        ),
        "item_field_categories": {
            cf.key: [c.id for c in cf.categories.all()]
            for cf in CustomField.objects.active().filter(applies_to=CustomField.AppliesTo.ITEM)
            .prefetch_related("categories")
        },
    }


def _save_purchase(request, form, formset):
    """Validate and save inside one transaction.

    If anything is invalid the transaction is rolled back, which also undoes
    a vendor that was auto-created from a typed name.
    """
    with transaction.atomic():
        if form.is_valid() and formset.is_valid():
            purchase = form.save(commit=False)
            if not purchase.pk:
                purchase.created_by = request.user
            purchase.save()
            formset.instance = purchase
            formset.save()
            return purchase
        transaction.set_rollback(True)
    return None


def _get_editable(request, pk):
    purchase = get_object_or_404(Purchase.objects.visible_to(request.user).select_related("vendor", "owner"), pk=pk)
    if not can_edit_purchase(request.user, purchase):
        raise PermissionDenied
    return purchase


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@login_required
@require_GET
def purchase_list(request):
    user = request.user
    qs = (Purchase.objects.visible_to(user)
          .select_related("vendor", "owner")
          .annotate(item_count=Count("items"))
          .order_by("-purchase_date", "-id"))

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(invoice_number__icontains=q) | Q(order_number__icontains=q)
                       | Q(vendor__name__icontains=q) | Q(items__item_name__icontains=q)
                       | Q(items__serial_numbers__icontains=q) | Q(owner__full_name__icontains=q)).distinct()
    filters = {
        "category": ("items__category_id", Category.objects.active()),
        "funding": ("items__funding_source_id", FundingSource.objects.active()),
    }
    selected = {}
    for param, (lookup, _) in filters.items():
        value = request.GET.get(param, "")
        if value.isdigit():
            qs = qs.filter(**{lookup: int(value)}).distinct()
            selected[param] = int(value)
    owner = request.GET.get("owner", "")
    if user.can_view_all_records and owner.isdigit():
        qs = qs.filter(owner_id=int(owner))
        selected["owner"] = int(owner)
    date_from, date_to = request.GET.get("from", ""), request.GET.get("to", "")
    if date_from:
        qs = qs.filter(purchase_date__gte=date_from)
    if date_to:
        qs = qs.filter(purchase_date__lte=date_to)

    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "purchases/list.html", {
        "page": page,
        "q": q,
        "selected": selected,
        "date_from": date_from,
        "date_to": date_to,
        "categories": filters["category"][1],
        "funding_sources": filters["funding"][1],
        "owners": get_user_model().objects.filter(purchases__isnull=False).distinct()
        if user.can_view_all_records else None,
        "querystring": params.urlencode(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def purchase_create(request):
    purchase = Purchase()
    form = PurchaseForm(request.POST or None, request.FILES or None, instance=purchase, user=request.user)
    formset = ItemFormSet(request.POST or None, instance=purchase, prefix="items")
    if request.method == "POST":
        saved = _save_purchase(request, form, formset)
        if saved:
            n = saved.items.count()
            note = " New vendor added." if getattr(form, "vendor_created", False) else ""
            messages.success(request, f"Invoice {saved.invoice_number} saved with {n} item{'s' * (n != 1)}.{note}")
            return redirect("purchases:detail", pk=saved.pk)
    return render(request, "purchases/form.html", {
        "form": form, "formset": formset, "mode": "create", "form_data": _form_context(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def purchase_add_items(request, pk):
    """Add more items to an invoice that's already recorded."""
    purchase = _get_editable(request, pk)
    formset = ItemFormSet(request.POST or None, instance=purchase, prefix="items",
                          queryset=PurchaseItem.objects.none())
    if request.method == "POST":
        with transaction.atomic():
            if formset.is_valid():
                created = formset.save()
                n = len(created)
                messages.success(request, f"Added {n} item{'s' * (n != 1)} to invoice {purchase.invoice_number}.")
                return redirect("purchases:detail", pk=purchase.pk)
    return render(request, "purchases/form.html", {
        "purchase": purchase, "formset": formset, "mode": "add_items", "form_data": _form_context(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def purchase_edit(request, pk):
    purchase = _get_editable(request, pk)
    form = PurchaseForm(request.POST or None, request.FILES or None, instance=purchase, user=request.user)
    formset = ItemFormSet(request.POST or None, instance=purchase, prefix="items")
    if request.method == "POST":
        if _save_purchase(request, form, formset):
            messages.success(request, f"Invoice {purchase.invoice_number} updated.")
            return redirect("purchases:detail", pk=purchase.pk)
    return render(request, "purchases/form.html", {
        "form": form, "formset": formset, "mode": "edit", "purchase": purchase, "form_data": _form_context(),
    })


@login_required
@require_GET
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.visible_to(request.user).select_related("vendor", "owner", "created_by"), pk=pk)
    items = purchase.items.select_related("category", "item_type", "funding_source", "venue")
    custom = {cf.key: cf for cf in CustomField.objects.all()}

    # Change history of the invoice and its items, newest first.
    records = sorted(
        chain(purchase.history.select_related("history_user"),
              PurchaseItem.history.filter(purchase_id=purchase.pk).select_related("history_user")),
        key=lambda h: h.history_date, reverse=True,
    )[:50]
    history = []
    for h in records:
        changes = []
        if h.history_type == "~" and h.prev_record:
            for c in h.diff_against(h.prev_record).changes:
                if c.field in ("updated_at",):
                    continue
                changes.append(c.field.replace("_", " "))
        history.append({
            "when": h.history_date,
            "who": h.history_user,
            "what": {"+": "Added", "~": "Edited", "-": "Removed"}[h.history_type],
            "subject": f"item “{h.item_name}”" if isinstance(h, PurchaseItem.history.model) else "invoice",
            "changes": changes,
        })

    return render(request, "purchases/detail.html", {
        "purchase": purchase,
        "items": items,
        "custom": custom,
        "history": history,
        "can_edit": can_edit_purchase(request.user, purchase),
    })


@login_required
@require_http_methods(["GET", "POST"])
def purchase_delete(request, pk):
    purchase = _get_editable(request, pk)
    if request.method == "POST":
        number = purchase.invoice_number
        purchase.delete()  # the change history keeps a copy
        messages.success(request, f"Invoice {number} deleted.")
        return redirect("purchases:list")
    return render(request, "purchases/confirm_delete.html", {"purchase": purchase})


@login_required
@require_GET
def bill_file(request, pk):
    """Stream a bill only to people allowed to see the invoice."""
    purchase = get_object_or_404(Purchase.objects.visible_to(request.user), pk=pk)
    if not purchase.bill_file:
        raise Http404
    ext = os.path.splitext(purchase.bill_file.name)[1].lower()
    safe_invoice = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in purchase.invoice_number)
    try:
        f = purchase.bill_file.open("rb")
    except FileNotFoundError:
        raise Http404
    response = FileResponse(f, filename=f"bill-{safe_invoice}{ext}",
                            as_attachment=request.GET.get("download") == "1")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


# --------------------------------------------------------------------------
# JSON endpoints used by the vendor and invoice boxes
# --------------------------------------------------------------------------
@login_required
@require_GET
def api_vendors(request):
    """Vendors matching ?q=, plus `exact` if the text equals an existing one."""
    q = request.GET.get("q", "").strip()
    key = normalize_vendor_name(q)
    qs = Vendor.objects.active()
    if key:
        qs = qs.filter(Q(name__icontains=q) | Q(name_key__contains=key))
    results = [{"id": v.id, "name": v.name} for v in qs.order_by("name")[:15]]
    exact = Vendor.objects.filter(name_key=key).values("id", "name").first() if key else None
    return JsonResponse({"results": results, "exact": exact})


@login_required
@require_GET
def api_my_invoices(request):
    """The signed-in user's own invoices matching ?q= (most recent first).

    Admin/HoD entering on behalf of someone may pass ?owner=<id> to see that
    person's invoices; for everyone else `owner` is ignored.
    """
    owner_id = request.user.pk
    requested = request.GET.get("owner", "")
    if requested.isdigit() and request.user.can_view_all_records:
        owner_id = int(requested)
    qs = Purchase.objects.filter(owner_id=owner_id).select_related("vendor").annotate(item_count=Count("items"))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(invoice_number__icontains=q) | Q(vendor__name__icontains=q))
    results = [{
        "id": p.id,
        "invoice_number": p.invoice_number,
        "vendor": p.vendor.name,
        "date": p.purchase_date.strftime("%d %b %Y"),
        "amount": f"₹{inr(p.bill_amount)}",
        "items": p.item_count,
        "add_items_url": reverse("purchases:add_items", args=[p.id]),
    } for p in qs[:10]]
    return JsonResponse({"results": results})
