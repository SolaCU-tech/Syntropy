"""Shared helpers for the storage tests and the storage benchmark.

``retail_with_policies`` extends the hand-written retail SSD so every delete policy is
exercised: a sale's customer becomes set_null, and a new Payments table cascades from Sales.
"""

import copy
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.schema_registry.examples import load_retail_ssd

CUSTOMERS = "tbl_customers"
PRODUCTS = "tbl_products"
SALES = "tbl_sales"
PAYMENTS = "tbl_payments"

PAYMENTS_TABLE = {
    "id": PAYMENTS,
    "key": "payments",
    "label": "Payments",
    "icon": "banknote",
    "fields": [
        {
            "id": "fld_payment_date",
            "key": "date",
            "label": "Date",
            "type": "date",
            "required": True,
            "display_role": "date",
        },
        {
            "id": "fld_payment_amount",
            "key": "amount",
            "label": "Amount",
            "type": "decimal",
            "required": True,
            "precision": 14,
            "scale": 2,
            "currency": "NGN",
            "min_value": "0",
            "display_role": "money",
        },
        {
            "id": "fld_payment_sale",
            "key": "sale",
            "label": "Sale",
            "type": "reference",
            "required": True,
        },
    ],
}

PAYMENT_SALE_RELATIONSHIP = {
    "id": "rel_payment_sale",
    "from_table": PAYMENTS,
    "from_field": "fld_payment_sale",
    "to_table": SALES,
    "cardinality": "many_to_one",
    "optional": False,
    "on_delete": "cascade",
    "description": "Each payment is for one sale",
}


_rng = random.Random(1)  # noqa: S311  (deterministic fixtures, not security)


def retail_with_policies() -> dict[str, Any]:
    doc = copy.deepcopy(load_retail_ssd())
    for rel in doc["relationships"]:
        if rel["id"] == "rel_sale_customer":
            rel["on_delete"] = "set_null"
    doc["tables"].append(copy.deepcopy(PAYMENTS_TABLE))
    doc["relationships"].append(copy.deepcopy(PAYMENT_SALE_RELATIONSHIP))
    return doc


def customer_values(i: int) -> dict[str, Any]:
    return {
        "fld_customer_name": f"Customer {i}",
        "fld_customer_phone": f"0803{i:07d}",
        "fld_customer_area": _rng.choice(["Ikeja", "Yaba", "Surulere", "Lekki"]),
    }


def product_values(i: int) -> dict[str, Any]:
    return {
        "fld_product_name": f"Product {i}",
        "fld_product_sku": f"SKU-{i:05d}",
        "fld_product_category": _rng.choice(["provisions", "beverages", "household"]),
        "fld_product_unit_price": f"{_rng.randint(100, 5000)}.00",
        "fld_product_stock_quantity": 1000,
    }


def sale_values(customer_id, product_id, *, day: date, rng: random.Random) -> dict[str, Any]:
    quantity = rng.randint(1, 10)
    price = Decimal(rng.randint(100, 5000))
    total = price * quantity
    paid = total if rng.random() < 0.6 else (total / 2).quantize(Decimal("0.01"))
    return {
        "fld_sale_date": day.isoformat(),
        "fld_sale_customer": str(customer_id) if customer_id else None,
        "fld_sale_product": str(product_id),
        "fld_sale_quantity": quantity,
        "fld_sale_unit_price": f"{price:.2f}",
        "fld_sale_total_amount": f"{total:.2f}",
        "fld_sale_amount_paid": f"{paid:.2f}",
        "fld_sale_payment_status": "paid" if paid == total else "part_paid",
        "fld_sale_payment_method": rng.choice(["cash", "transfer", "pos"]),
    }


def sale_days(n: int, *, start: date = date(2025, 1, 1), months: int = 12) -> list[date]:
    rng = random.Random(7)  # noqa: S311
    span = months * 30
    return [start + timedelta(days=rng.randrange(span)) for _ in range(n)]
