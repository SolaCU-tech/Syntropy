"""Create a demo user with the example retail workspace and a few records.

For local development and the end-to-end tests only: it refuses to run unless DEBUG is on.

    python manage.py seed_demo                 # user "demo", password "demo-pass-1"
    python manage.py seed_demo --username ada --password "something long"
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.schema_registry.management.commands.seed_retail_example import WORKSPACE_NAME
from apps.storage.store import get_record_store
from apps.storage.testing import CUSTOMERS, PRODUCTS, SALES
from apps.tenancy.models import Workspace

CUSTOMER_ROWS = [
    ("Adaeze Okafor", "08031234501", "Yaba", "50000.00"),
    ("Bayo Adewale", "08031234502", "Ikeja", None),
    ("Chioma Eze", "08031234503", "Surulere", "20000.00"),
]
PRODUCT_ROWS = [
    ("Rice 50kg", "SKU-RICE50", "provisions", "45000.00", 12),
    ("Indomie carton", "SKU-INDO40", "provisions", "9500.00", 30),
    ("Peak milk tin", "SKU-PEAK", "beverages", "650.00", 4),
]


class Command(BaseCommand):
    help = "Create a demo user and example workspace with sample records (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="demo-pass-1")

    @transaction.atomic
    def handle(self, *args, username: str, password: str, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=true.")
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": "Ade"}
        )
        if created:
            user.set_password(password)
            user.save()
        call_command("seed_retail_example", username, stdout=self.stdout)
        workspace = Workspace.objects.get(memberships__user=user, name=WORKSPACE_NAME)
        store = get_record_store(workspace)
        if store.queryset(CUSTOMERS).exists():
            self.stdout.write("Sample records already exist.")
            return
        customers = [
            store.create(
                CUSTOMERS,
                {
                    "fld_customer_name": name,
                    "fld_customer_phone": phone,
                    "fld_customer_area": area,
                    "fld_customer_credit_limit": limit,
                },
                actor=user,
            )
            for name, phone, area, limit in CUSTOMER_ROWS
        ]
        products = [
            store.create(
                PRODUCTS,
                {
                    "fld_product_name": name,
                    "fld_product_sku": sku,
                    "fld_product_category": category,
                    "fld_product_unit_price": price,
                    "fld_product_stock_quantity": stock,
                    "fld_product_reorder_level": 5,
                },
                actor=user,
            )
            for name, sku, category, price, stock in PRODUCT_ROWS
        ]
        for i, (customer, product) in enumerate(zip(customers, products, strict=True)):
            price = product.values["fld_product_unit_price"]
            store.create(
                SALES,
                {
                    "fld_sale_date": f"2026-11-{20 + i:02d}",
                    "fld_sale_customer": str(customer.id),
                    "fld_sale_product": str(product.id),
                    "fld_sale_quantity": 1,
                    "fld_sale_unit_price": price,
                    "fld_sale_total_amount": price,
                    "fld_sale_amount_paid": "0.00" if i == 0 else price,
                    "fld_sale_payment_status": "unpaid" if i == 0 else "paid",
                    "fld_sale_payment_method": "cash",
                },
                actor=user,
            )
        self.stdout.write(self.style.SUCCESS(f"Demo ready: sign in as '{username}'."))
