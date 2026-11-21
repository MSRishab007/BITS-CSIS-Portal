from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Purchase, PurchaseItem


class PurchaseItemInline(admin.StackedInline):
    model = PurchaseItem
    extra = 0
    autocomplete_fields = ("category", "item_type", "funding_source", "venue")
    fieldsets = (
        (None, {"fields": (("category", "item_type"), "item_name", ("quantity", "amount"), "status")}),
        ("Funding", {"fields": ("funding_source", ("project_number", "principal_investigator"))}),
        ("Asset details", {"fields": ("venue", "asset_tag", "serial_numbers", "warranty_end_date")}),
        (None, {"fields": ("remarks", "extra")}),
    )


@admin.register(Purchase)
class PurchaseAdmin(SimpleHistoryAdmin):
    """Technical admin view. Faculty and HoD use the portal screens instead."""

    list_display = ("invoice_number", "vendor", "owner", "purchase_date", "bill_amount", "item_count")
    list_filter = ("purchase_date", "items__category", "items__funding_source")
    search_fields = ("invoice_number", "order_number", "vendor__name", "owner__full_name", "items__item_name")
    date_hierarchy = "purchase_date"
    autocomplete_fields = ("owner", "vendor")
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = [PurchaseItemInline]
    fieldsets = (
        (None, {"fields": ("owner", "vendor", ("invoice_number", "order_number"))}),
        ("Dates & amount", {"fields": (("purchase_date", "delivery_date"), "bill_amount", "bill_file")}),
        (None, {"fields": ("remarks", "extra")}),
        ("Record", {"classes": ("collapse",), "fields": ("created_by", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("vendor", "owner").prefetch_related("items")

    @admin.display(description="Items")
    def item_count(self, obj):
        return len(obj.items.all())

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PurchaseItem)
class PurchaseItemAdmin(SimpleHistoryAdmin):
    list_display = ("item_name", "category", "item_type", "quantity", "funding_source", "venue",
                    "warranty_end_date", "status", "purchase")
    list_filter = ("category", "funding_source", "status", "venue")
    search_fields = ("item_name", "serial_numbers", "asset_tag", "project_number", "purchase__invoice_number")
    autocomplete_fields = ("purchase", "category", "item_type", "funding_source", "venue")
    list_select_related = ("category", "item_type", "funding_source", "venue", "purchase__vendor")
