from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import User


class PortalUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name", "role")


class PortalUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = PortalUserChangeForm
    add_form = PortalUserCreationForm

    list_display = ("full_name", "email", "role", "designation", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("full_name", "email", "employee_id")
    ordering = ("full_name",)
    readonly_fields = ("date_joined", "deactivated_at", "updated_at", "last_login")
    actions = ["deactivate", "reactivate"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "employee_id", "designation", "phone")}),
        ("Role & status", {"fields": ("role", "is_active", "deactivated_at")}),
        ("Django admin permissions", {
            "classes": ("collapse",),
            "fields": ("is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        ("Dates", {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "usable_password", "password1", "password2"),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        # Users are deactivated, never deleted, so their records stay intact.
        return False

    @admin.action(description="Deactivate selected users")
    def deactivate(self, request, queryset):
        count = 0
        for user in queryset.filter(is_active=True).exclude(pk=request.user.pk):
            user.is_active = False
            user.save()
            count += 1
        self.message_user(request, f"{count} user(s) deactivated.")

    @admin.action(description="Reactivate selected users")
    def reactivate(self, request, queryset):
        count = 0
        for user in queryset.filter(is_active=False):
            user.is_active = True
            user.save()
            count += 1
        self.message_user(request, f"{count} user(s) reactivated.")
