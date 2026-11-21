"""Starting categories, types and funding sources.

Admin/HoD can rename, add or deactivate any of these later. Re-running is
safe: existing entries are left as they are.
"""
from django.db import migrations

CATEGORIES = {
    "Computing Resources": ["Workstation", "Desktop", "Laptop", "Monitor", "Printer / Scanner",
                            "Software License", "Other"],
    "Server/GPU Resources": ["Server", "GPU", "Storage Server / NAS", "Memory / RAM", "Rack / UPS", "Other"],
    "Networking Resources": ["Switch", "Router", "Wireless Access Point", "Firewall", "Cables / Accessories",
                             "Other"],
    "Gadgets": ["Keyboard", "Mouse", "Headphone", "Webcam", "Tablet", "Storage Device", "Other"],
    "Research Project Items": ["Equipment", "Components", "Consumables", "Software License", "Other"],
}

FUNDING = [
    ("Departmental Fund", False),
    ("Research Grant", True),   # asks for project/grant number and PI
    ("Institute Fund", False),
]


def seed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    ItemType = apps.get_model("catalog", "ItemType")
    FundingSource = apps.get_model("catalog", "FundingSource")

    for c_order, (cat_name, types) in enumerate(CATEGORIES.items(), start=1):
        cat = Category.objects.filter(name__iexact=cat_name).first()
        if cat is None:
            cat = Category.objects.create(name=cat_name, sort_order=c_order * 10)
        for t_order, type_name in enumerate(types, start=1):
            if not ItemType.objects.filter(category=cat, name__iexact=type_name).exists():
                # "Other" always sorts last.
                order = 999 if type_name == "Other" else t_order * 10
                ItemType.objects.create(category=cat, name=type_name, sort_order=order)

    for f_order, (name, needs_project) in enumerate(FUNDING, start=1):
        if not FundingSource.objects.filter(name__iexact=name).exists():
            FundingSource.objects.create(name=name, requires_project_details=needs_project, sort_order=f_order * 10)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
