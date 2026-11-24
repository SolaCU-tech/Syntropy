"""What each workspace role may do.

This is the permission matrix from spec section 5. Its status there is Recommended until
Sola confirms it (Open decision "Workspace permissions", needed by Phase 5), so it lives in
one table that is easy to change.
"""

from enum import StrEnum

from .models import Role


class Action(StrEnum):
    VIEW_WORKSPACE = "view_workspace"
    VIEW_SCHEMA = "view_schema"
    MANAGE_BILLING = "manage_billing"
    DELETE_WORKSPACE = "delete_workspace"
    APPROVE_SCHEMA_CHANGES = "approve_schema_changes"
    ACTIVATE_WORKSPACE = "activate_workspace"
    MANAGE_MEMBERS = "manage_members"
    IMPORT_DATA = "import_data"
    EDIT_STRUCTURE_LABELS = "edit_structure_labels"
    EDIT_RECORDS = "edit_records"
    DELETE_ANY_RECORD = "delete_any_record"
    DELETE_OWN_RECORDS = "delete_own_records"
    ASK_AND_RUN_REPORTS = "ask_and_run_reports"
    SAVE_REPORTS = "save_reports"
    EXPORT = "export"


_ALL = frozenset(Action)

ROLE_PERMISSIONS: dict[str, frozenset[Action]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ALL
    - {Action.MANAGE_BILLING, Action.DELETE_WORKSPACE, Action.APPROVE_SCHEMA_CHANGES},
    Role.EDITOR: frozenset(
        {
            Action.VIEW_WORKSPACE,
            Action.VIEW_SCHEMA,
            Action.EDIT_RECORDS,
            Action.DELETE_OWN_RECORDS,
            Action.ASK_AND_RUN_REPORTS,
            Action.SAVE_REPORTS,
        }
    ),
    Role.VIEWER: frozenset({Action.VIEW_WORKSPACE, Action.VIEW_SCHEMA, Action.ASK_AND_RUN_REPORTS}),
}


def role_allows(role: str, action: Action) -> bool:
    return action in ROLE_PERMISSIONS.get(role, frozenset())
