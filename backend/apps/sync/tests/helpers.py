"""A tiny stand-in for a device's offline queue, so tests read like the scenarios they model."""

import uuid
from typing import Any

from django.urls import reverse

from apps.storage.testing import CUSTOMERS, SALES


class Device:
    """One phone: it queues changes while offline and uploads them when it reconnects."""

    def __init__(self, client, workspace, schema_version: int = 1):
        self.client = client
        self.workspace = workspace
        self.schema_version = schema_version
        self.queue: list[dict[str, Any]] = []

    def create(self, table_id: str, values: dict[str, Any], record_id=None) -> str:
        record_id = str(record_id or uuid.uuid4())
        self.queue.append(self._op("create", table_id, record_id, values))
        return record_id

    def edit(self, table_id: str, record_id, base_version: int, values: dict[str, Any]) -> None:
        op = self._op("update", table_id, str(record_id), values)
        op["base_version"] = base_version
        self.queue.append(op)

    def _op(self, kind, table_id, record_id, values):
        return {
            "idempotency_key": str(uuid.uuid4()),
            "op": kind,
            "table_id": table_id,
            "record_id": record_id,
            "schema_version": self.schema_version,
            "values": values,
        }

    def upload(self, operations=None):
        body = {"operations": operations if operations is not None else self.queue}
        url = reverse("workspace-sync", kwargs={"workspace_id": self.workspace.id})
        return self.client.post(url, body, format="json")

    def sync(self) -> list[dict[str, Any]]:
        """Upload the queue and drop applied operations, as the app does."""
        response = self.upload()
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        applied = {r["idempotency_key"] for r in results if r["status"] == "applied"}
        self.queue = [op for op in self.queue if op["idempotency_key"] not in applied]
        return results


def sale(product_id, customer_id=None, **extra) -> dict[str, Any]:
    return {
        "fld_sale_date": "2026-11-26",
        "fld_sale_product": str(product_id),
        "fld_sale_customer": str(customer_id) if customer_id else None,
        "fld_sale_quantity": 1,
        "fld_sale_unit_price": "500.00",
        "fld_sale_total_amount": "500.00",
        "fld_sale_amount_paid": "0.00",
        "fld_sale_payment_status": "unpaid",
        **extra,
    }


__all__ = ["CUSTOMERS", "SALES", "Device", "sale"]
