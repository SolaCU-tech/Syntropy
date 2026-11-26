"""Apply a batch of offline operations (spec section 13, ADR-27).

Each operation runs in its own transaction, in the order the device queued it, so a sale can
link to a customer created earlier in the same batch. One operation failing never blocks the
others; the device gets one result per operation:

* ``applied``: written; the device drops it from its queue.
* ``conflict``: an edit was based on a version the server has moved past. The result holds the
  current record so the user can see both versions and choose (Agreed 26 Nov 2026).
* ``rejected``: the server refused it for a reason the user must fix (a duplicate unique
  value, a deleted linked record, a record that no longer exists).
* ``schema_changed``: the structure changed since the change was made and the change doesn't
  fit the new version; the device re-validates its form against the new schema.

Deletes are never queued offline (Agreed 26 Nov 2026), so the batch accepts only creates and
edits. Validation and integrity come from the record store, exactly as for online writes.
"""

import hashlib
import json
from typing import Any

from django.db import IntegrityError, transaction

from apps.storage import errors
from apps.storage.serializers import RecordSerializer
from apps.storage.store import JsonbRecordStore

from .models import SyncOperation

Status = SyncOperation.Status


def request_hash(op: dict[str, Any]) -> str:
    body = {k: v for k, v in op.items() if k != "idempotency_key"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _error(exc: errors.StorageError) -> dict[str, Any]:
    body: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        body["details"] = exc.details
    return body


def apply_batch(store: JsonbRecordStore, user, operations: list[dict[str, Any]]) -> dict:
    """Apply ``operations`` (already shape-checked by the serializer) and return the results."""
    results = [apply_operation(store, user, op) for op in operations]
    return {"schema_version": store.schema.version.number, "results": results}


def apply_operation(store: JsonbRecordStore, user, op: dict[str, Any]) -> dict[str, Any]:
    key = op["idempotency_key"]
    digest = request_hash(op)
    with transaction.atomic():
        try:
            with transaction.atomic():
                entry = SyncOperation.objects.create(
                    workspace=store.workspace,
                    user=user,
                    idempotency_key=key,
                    request_hash=digest,
                    kind=op["op"],
                    table_id=op["table_id"],
                    record_id=op["record_id"],
                    status=Status.REJECTED,
                )
        except IntegrityError:
            return _replay(store, user, key, digest)
        result = _execute(store, user, op)
        result = {"idempotency_key": str(key), "replayed": False, **result}
        entry.status = result["status"]
        entry.result = result
        entry.save(update_fields=["status", "result"])
    return result


def _replay(store: JsonbRecordStore, user, key, digest: str) -> dict[str, Any]:
    entry = SyncOperation.objects.get(workspace=store.workspace, user=user, idempotency_key=key)
    if entry.request_hash != digest:
        return {
            "idempotency_key": str(key),
            "replayed": False,
            "status": Status.REJECTED,
            "error": {
                "code": "idempotency_key_reused",
                "message": "This change reused the key of a different change. Nothing was saved.",
            },
        }
    return {**entry.result, "replayed": True}


def _execute(store: JsonbRecordStore, user, op: dict[str, Any]) -> dict[str, Any]:
    table_id, record_id = op["table_id"], op["record_id"]
    stale_schema = op["schema_version"] != store.schema.version.number
    try:
        # A savepoint, so a refused write leaves the ledger entry intact.
        with transaction.atomic():
            if op["op"] == SyncOperation.Kind.CREATE:
                record = store.create(table_id, op["values"], record_id=record_id, actor=user)
            else:
                record = store.update(
                    table_id,
                    record_id,
                    op["values"],
                    expected_version=op["base_version"],
                    actor=user,
                )
    except errors.VersionConflict as exc:
        return {
            "status": Status.CONFLICT,
            "error": _error(exc),
            "current": RecordSerializer(exc.current).data,
        }
    except (errors.RecordValidationError, errors.UnknownTable) as exc:
        status = Status.SCHEMA_CHANGED if stale_schema else Status.REJECTED
        return {"status": status, "error": _error(exc)}
    except errors.StorageError as exc:
        return {"status": Status.REJECTED, "error": _error(exc)}
    return {"status": Status.APPLIED, "record": RecordSerializer(record).data}
