from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = f"{settings.PORTAL_NAME} — Administration"
admin.site.site_title = settings.PORTAL_NAME
admin.site.index_title = settings.DEPARTMENT_NAME

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("purchases/", include("apps.purchases.urls")),
    path("manage/", include("apps.administration.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.core.urls")),
]
