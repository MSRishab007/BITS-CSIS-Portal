from django.urls import path

from . import views

app_name = "purchases"

urlpatterns = [
    path("", views.purchase_list, name="list"),
    path("new/", views.purchase_create, name="create"),
    path("<int:pk>/", views.purchase_detail, name="detail"),
    path("<int:pk>/edit/", views.purchase_edit, name="edit"),
    path("<int:pk>/add-items/", views.purchase_add_items, name="add_items"),
    path("<int:pk>/delete/", views.purchase_delete, name="delete"),
    path("<int:pk>/bill/", views.bill_file, name="bill"),
    path("api/vendors/", views.api_vendors, name="api_vendors"),
    path("api/my-invoices/", views.api_my_invoices, name="api_my_invoices"),
]
