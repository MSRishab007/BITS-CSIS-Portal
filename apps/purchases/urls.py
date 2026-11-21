from django.urls import path, re_path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.purchase_list, name="list"),
    path("new/", views.purchase_create, name="create"),
    path("export.xlsx", views.purchase_export, name="export"),
    path("<int:pk>/", views.purchase_detail, name="detail"),
    path("<int:pk>/edit/", views.purchase_edit, name="edit"),
    path("<int:pk>/add-items/", views.purchase_add_items, name="add_items"),
    path("<int:pk>/delete/", views.purchase_delete, name="delete"),
    path("<int:pk>/bill/", views.bill_file, name="bill"),
    path("bulk/", views.bulk_upload, name="bulk_upload"),
    path("bulk/confirm/", views.bulk_confirm, name="bulk_confirm"),
    re_path(r"^bulk/template\.(?P<fmt>xlsx|csv)$", views.bulk_template, name="bulk_template"),
    path("api/vendors/", views.api_vendors, name="api_vendors"),
    path("api/my-invoices/", views.api_my_invoices, name="api_my_invoices"),
]
