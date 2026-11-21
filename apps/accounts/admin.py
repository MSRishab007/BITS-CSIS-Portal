from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.template.response import TemplateResponse
from django.utils.cache import add_never_cache_headers

from .models import User
from .passwords import generate_password, set_generated_password


class PortalUserAddForm(forms.ModelForm):
    """Add-user form with no password fields: the password is generated."""

    class Meta:
        model = User
        fields = ("email", "full_name", "username", "role", "employee_id", "designation", "phone")


class PortalUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = PortalUserChangeForm
    add_form = PortalUserAddForm

    list_display = ("full_name", "email", "username", "role", "is_active", "must_change_password", "last_login")
    list_filter = ("role", "is_active", "must_change_password", "is_staff")
    search_fields = ("full_name", "email", "username", "employee_id")
    ordering = ("full_name",)
    readonly_fields = ("date_joined", "deactivated_at", "updated_at", "last_login")
    actions = ["reset_passwords", "deactivate", "reactivate"]

    fieldsets = (
        (None, {"fields": ("email", "username", "password", "must_change_password")}),
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
            "description": "A password is generated automatically and shown once after saving. "
                           "The user must change it at first sign-in.",
            "fields": ("email", "full_name", "username", "role", "employee_id", "designation", "phone"),
        }),
    )

    # ---- Adding a user: generate the password and show it once ---------
    def save_model(self, request, obj, form, change):
        if not change:
            if obj.created_by_id is None:
                obj.created_by = request.user
            password = generate_password()
            obj.set_password(password)
            obj.must_change_password = True
            # Kept only on this request object, never stored, so it can be
            # shown on the very next page and then it's gone.
            request._generated_credentials = [(obj, password)]
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        creds = getattr(request, "_generated_credentials", None)
        if creds:
            return self._credentials_response(request, creds, title="User added")
        return super().response_add(request, obj, post_url_continue)

    # ---- Setting a password by hand from the admin ----------------------
    def user_change_password(self, request, id, form_url=""):
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            # The admin knows this password, so the user must replace it.
            User.objects.filter(pk=id).update(must_change_password=True)
        return response

    # ---- Actions ---------------------------------------------------------
    @admin.action(description="Generate new password for selected users")
    def reset_passwords(self, request, queryset):
        queryset = queryset.filter(is_active=True).exclude(pk=request.user.pk)
        if request.POST.get("confirm") == "yes":
            creds = [(user, set_generated_password(user)) for user in queryset]
            if not creds:
                self.message_user(request, "No eligible users selected (inactive users and yourself are skipped).")
                return None
            return self._credentials_response(request, creds, title="New passwords generated")

        context = {
            **self.admin_site.each_context(request),
            "title": "Generate new passwords?",
            "opts": self.model._meta,
            "users": queryset,
            "action_name": "reset_passwords",
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/accounts/user/reset_passwords_confirm.html", context)

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

    def has_delete_permission(self, request, obj=None):
        # Users are deactivated, never deleted, so their records stay intact.
        return False

    # ---- Helpers -----------------------------------------------------------
    def _credentials_response(self, request, creds, title):
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.model._meta,
            "credentials": creds,
        }
        response = TemplateResponse(request, "admin/accounts/user/credentials.html", context)
        # Stop the browser from caching a page that contains passwords.
        add_never_cache_headers(response)
        return response
