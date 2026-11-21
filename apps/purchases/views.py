import os
import time
import uuid
from itertools import chain

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.catalog.models import Category, CustomField, FundingSource, Vendor, normalize_vendor_name
from apps.core.templatetags.portal_tags import inr

from . import bulk, exports
from .filters import PurchaseFilter
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
    f = PurchaseFilter.from_request(request)
    qs = (f.purchases(request.user)
          .select_related("vendor", "owner")
          .annotate(item_count=Count("items", distinct=True))
          .order_by("-purchase_date", "-id"))
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "purchases/list.html", {
        "page": page, "querystring": f.querystring(), **f.form_context(request.user),
    })


@login_required
@require_GET
def purchase_export(request):
    """Excel file of the items on the invoices currently filtered."""
    f = PurchaseFilter.from_request(request)
    data = exports.build_items_xlsx(f, request.user)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="purchases-{stamp}.xlsx"'
    return response


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
        "last_change": history[0] if history else None,
        "can_edit": can_edit_purchase(request.user, purchase),
    })


@login_required
@require_GET
def purchase_peek(request, pk):
    """Invoice summary for the slide-over panel on the list page (HTML fragment)."""
    purchase = get_object_or_404(
        Purchase.objects.visible_to(request.user).select_related("vendor", "owner", "created_by"), pk=pk)
    items = purchase.items.select_related("category", "item_type", "funding_source", "venue")
    return render(request, "purchases/_peek.html", {
        "purchase": purchase, "items": items, "can_edit": can_edit_purchase(request.user, purchase),
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


# --------------------------------------------------------------------------
# Bulk upload
# --------------------------------------------------------------------------
BULK_SESSION_KEY = "bulk_upload"
BULK_MAX_SIZE = 5 * 1024 * 1024


def _bulk_dir():
    path = os.path.join(settings.MEDIA_ROOT, "bulk_tmp")
    os.makedirs(path, exist_ok=True)
    return path


def _sweep_bulk_dir(max_age_hours=24):
    """Delete abandoned uploads (never confirmed) older than a day."""
    cutoff = time.time() - max_age_hours * 3600
    for name in os.listdir(_bulk_dir()):
        full = os.path.join(_bulk_dir(), name)
        try:
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
        except OSError:
            pass


def _pending_upload(request):
    info = request.session.get(BULK_SESSION_KEY)
    if not info:
        return None
    path = os.path.join(_bulk_dir(), info["file"])
    return (path, info["name"]) if os.path.exists(path) else None


@login_required
@require_GET
def bulk_template(request, fmt):
    stamp = timezone.localdate().strftime("%Y%m%d")
    if fmt == "xlsx":
        response = HttpResponse(
            bulk.build_template_xlsx(request.user),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        response = HttpResponse(bulk.build_template_csv(request.user), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="purchase-upload-template-{stamp}.{fmt}"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def bulk_upload(request):
    context = {"max_rows": bulk.MAX_ROWS}
    if request.method == "POST":
        upload = request.FILES.get("file")
        error = None
        if upload is None:
            error = "Choose a file to upload."
        elif not upload.name.lower().endswith((".xlsx", ".csv")):
            error = "Upload the .xlsx or .csv template."
        elif upload.size > BULK_MAX_SIZE:
            error = "The file is larger than 5 MB."
        if error:
            context["file_error"] = error
            return render(request, "purchases/bulk_upload.html", context)

        _sweep_bulk_dir()
        ext = os.path.splitext(upload.name)[1].lower()
        stored = f"{uuid.uuid4().hex}{ext}"
        path = os.path.join(_bulk_dir(), stored)
        with open(path, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        try:
            headers, data = bulk.read_file(path, upload.name)
        except bulk.FileError as e:
            os.remove(path)
            context["file_error"] = str(e)
            return render(request, "purchases/bulk_upload.html", context)

        result = bulk.run_import(headers, data, request.user, commit=False)  # dry run
        if result.ok:
            request.session[BULK_SESSION_KEY] = {"file": stored, "name": upload.name}
        else:
            os.remove(path)
            request.session.pop(BULK_SESSION_KEY, None)
        context.update({"result": result, "filename": upload.name})
    return render(request, "purchases/bulk_upload.html", context)


@login_required
@require_http_methods(["POST"])
def bulk_confirm(request):
    pending = _pending_upload(request)
    if pending is None:
        messages.error(request, "That upload has expired. Please upload the file again.")
        return redirect("purchases:bulk_upload")
    path, name = pending
    headers, data = bulk.read_file(path, name)
    # Checked again: lookup lists or invoices may have changed since the preview.
    result = bulk.run_import(headers, data, request.user, commit=True)
    request.session.pop(BULK_SESSION_KEY, None)
    os.remove(path)
    if not result.committed:
        return render(request, "purchases/bulk_upload.html",
                      {"result": result, "filename": name, "max_rows": bulk.MAX_ROWS})
    n, m = len(result.invoices), result.item_count
    extra = f" {len(result.new_vendors)} new vendor(s) added." if result.new_vendors else ""
    messages.success(request, f"Imported {n} invoice{'s' * (n != 1)} with {m} item{'s' * (m != 1)}.{extra}")
    return redirect("purchases:list")
