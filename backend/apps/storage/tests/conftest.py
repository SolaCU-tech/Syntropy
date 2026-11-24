import pytest

from apps.schema_registry import registry
from apps.storage.store import get_record_store
from apps.storage.testing import (
    CUSTOMERS,
    PRODUCTS,
    SALES,
    customer_values,
    product_values,
    retail_with_policies,
)


@pytest.fixture
def published_ssd():
    """The SSD the storage tests publish: retail plus Payments, covering every delete policy."""
    return retail_with_policies()


@pytest.fixture
def store(workspace, owner, published_ssd):
    registry.publish(registry.create_draft(workspace, published_ssd), published_by=owner)
    return get_record_store(workspace)


@pytest.fixture
def make_customer(store, owner):
    counter = iter(range(1, 10_000))

    def make(**values):
        return store.create(CUSTOMERS, {**customer_values(next(counter)), **values}, actor=owner)

    return make


@pytest.fixture
def make_product(store, owner):
    counter = iter(range(1, 10_000))

    def make(**values):
        return store.create(PRODUCTS, {**product_values(next(counter)), **values}, actor=owner)

    return make


@pytest.fixture
def make_sale(store, owner, make_product):
    def make(product=None, customer=None, **values):
        product = product or make_product()
        base = {
            "fld_sale_date": "2026-11-24",
            "fld_sale_product": str(product.id),
            "fld_sale_customer": str(customer.id) if customer else None,
            "fld_sale_quantity": 2,
            "fld_sale_unit_price": "500.00",
            "fld_sale_total_amount": "1000.00",
        }
        return store.create(SALES, {**base, **values}, actor=owner)

    return make
