from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("people/", views.people_list, name="people"),
    path("people/add/", views.person_add, name="person_add"),
    path("people/add-many/", views.people_bulk_add, name="people_bulk_add"),
    path("people/<int:pk>/", views.person_edit, name="person_edit"),
    path("people/<int:pk>/toggle-active/", views.person_toggle_active, name="person_toggle"),
    path("people/<int:pk>/reset-password/", views.person_reset_password, name="person_reset"),

    path("lists/", views.lookup_list, name="lookups_home"),
    path("lists/<str:kind>/", views.lookup_list, name="lookups"),
    path("lists/<str:kind>/add/", views.lookup_edit, name="lookup_add"),
    path("lists/<str:kind>/<int:pk>/", views.lookup_edit, name="lookup_edit"),
    path("lists/<str:kind>/<int:pk>/toggle/", views.lookup_toggle, name="lookup_toggle"),
    path("types/add/<int:category_pk>/", views.type_add, name="type_add"),
    path("types/<int:pk>/", views.type_edit, name="type_edit"),
    path("types/<int:pk>/toggle/", views.type_toggle, name="type_toggle"),
]
