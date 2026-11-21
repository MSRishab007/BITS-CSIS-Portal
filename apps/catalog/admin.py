from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Category, CustomField, FundingSource, ItemType, Vendor, Venue


class NoDeleteMixin:
    """Lookup entries are deactivated rather than deleted, so old records
    keep their values. (Deleting one that's in use is blocked anyway.)"""

    actions = ["make_inactive", "make_active"]

    @admin.action(description="Mark selected as inactive (hide from dropdowns)")
    def make_inactive(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} hidden.")

    @admin.action(description="Mark selected as active")
    def make_active(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} shown again.")


class ItemTypeInline(admin.TabularInline):
    model = ItemType
    extra = 1
    fields = ("name", "sort_order", "is_active")


@admin.register(Category)
class CategoryAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("name", "sort_order", "is_active", "type_count")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name",)
    inlines = [ItemTypeInline]

    @admin.display(description="Types")
    def type_count(self, obj):
        return obj.types.count()


@admin.register(ItemType)
class ItemTypeAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("name", "category", "sort_order", "is_active")
    list_filter = ("category", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "category__name")


@admin.register(Vendor)
class VendorAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("name", "gstin", "contact_person", "phone", "is_active", "created_by", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "gstin", "contact_person")
    readonly_fields = ("created_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(FundingSource)
class FundingSourceAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("name", "requires_project_details", "sort_order", "is_active")
    list_editable = ("requires_project_details", "sort_order", "is_active")
    search_fields = ("name",)


@admin.register(Venue)
class VenueAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("name", "building", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "building")


@admin.register(CustomField)
class CustomFieldAdmin(NoDeleteMixin, SimpleHistoryAdmin):
    list_display = ("label", "key", "applies_to", "field_type", "required", "sort_order", "is_active")
    list_filter = ("applies_to", "field_type", "is_active")
    list_editable = ("sort_order", "is_active")
    filter_horizontal = ("categories",)
    fields = ("label", "key", "applies_to", "field_type", "choices", "required", "help_text",
              "categories", "sort_order", "is_active")

    def get_readonly_fields(self, request, obj=None):
        # The key links stored values to the field, so it's fixed once created.
        return ("key",) if obj else ()
