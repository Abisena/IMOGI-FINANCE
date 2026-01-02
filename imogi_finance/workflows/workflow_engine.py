from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import frappe
from frappe import _

from .guards import AuthorizationGuard


class WorkflowEngine:
    """Config-driven workflow engine for IMOGI Finance doctypes."""

    def __init__(self, config_path: str | Path | None = None, *, config: dict[str, Any] | None = None):
        self.config_path = Path(config_path) if config_path else None
        self.config = config if config is not None else self._load_config()

    def _load_config(self) -> dict:
        if not self.config_path:
            frappe.throw(_("Workflow configuration path is required when config is not provided."))

        if not self.config_path.exists():
            frappe.throw(_("Workflow configuration file not found: {0}").format(self.config_path))

        return self._load_structured_file(self.config_path)

    def get_states(self) -> set[str]:
        states = self.config.get("states", [])
        return {state.get("state") for state in states if state.get("state")}

    def get_actions(self) -> Iterable[dict[str, Any]]:
        return self.config.get("actions", [])

    def get_transitions(self) -> Iterable[dict[str, Any]]:
        return self.config.get("transitions", [])

    def guard_action(self, *, doc: Any, action: str, current_state: str | None, next_state: str | None = None):
        """Validate that a workflow action is allowed for the routed user."""
        if not action or current_state is None:
            return
        transitions = [t for t in self.get_transitions() if t.get("action") == action and t.get("state") == current_state]
        if not transitions:
            frappe.throw(_("Action {0} is not allowed from state {1}.").format(action, current_state))

        # Derive required roles/users from doc-level route fields
        level = self._current_level_from_state(current_state)
        role_field = f"level_{level}_role" if level else None
        user_field = f"level_{level}_user" if level else None
        expected_roles = {getattr(doc, role_field)} if role_field and getattr(doc, role_field, None) else set()
        expected_users = {getattr(doc, user_field)} if user_field and getattr(doc, user_field, None) else set()

        if expected_roles or expected_users:
            guard = AuthorizationGuard(roles=expected_roles, users=expected_users)
            guard.require(action=action, level=level)

        if action == "Approve" and next_state == "Approved":
            self._validate_not_skipping(doc, level)

    @staticmethod
    def _current_level_from_state(state: str | None) -> str | None:
        mapping = {
            "Pending Level 1": "1",
            "Pending Level 2": "2",
            "Pending Level 3": "3",
        }
        return mapping.get(state)

    @staticmethod
    def _validate_not_skipping(doc: Any, level: str | None):
        if level == "1" and (getattr(doc, "level_2_role", None) or getattr(doc, "level_2_user", None) or getattr(doc, "level_3_role", None) or getattr(doc, "level_3_user", None)):
            frappe.throw(_("Cannot approve directly when further levels are configured."))
        if level == "2" and (getattr(doc, "level_3_role", None) or getattr(doc, "level_3_user", None)):
            frappe.throw(_("Cannot approve directly when further levels are configured."))

    @staticmethod
    def _load_structured_file(path: Path) -> dict:
        try:
            with path.open() as handle:
                return json.load(handle)
        except Exception:
            pass

        try:
            import yaml  # type: ignore
        except Exception:
            yaml = None

        if yaml is None:
            frappe.throw(
                _("Failed to load workflow configuration {0}. Ensure it is valid JSON or install PyYAML for YAML support.").format(
                    path
                )
            )

        try:
            with path.open() as handle:
                loaded = yaml.safe_load(handle)
                if isinstance(loaded, dict):
                    return loaded
        except Exception as exc:
            frappe.throw(_("Failed to load workflow configuration: {0}").format(exc))

        frappe.throw(_("Workflow configuration must resolve to a mapping: {0}").format(path))


class WorkflowConfigRegistry:
    """Registry for resolving workflow engines from a central config map."""

    def __init__(self, *, config_map_path: str | Path | None = None):
        default_map = Path(__file__).resolve().parent / "workflow_config.yaml"
        self.config_map_path = Path(config_map_path) if config_map_path else default_map
        self.config_map = self._load_config_map()

    def get_engine(self, key: str) -> WorkflowEngine:
        config_path = self.get_config_path(key)
        return WorkflowEngine(config_path=config_path)

    def get_config_path(self, key: str) -> Path:
        entry = self.config_map.get(key)
        if not entry:
            frappe.throw(_("Workflow configuration not found for {0}.").format(key))

        if isinstance(entry, dict):
            path = entry.get("config")
        else:
            path = entry

        if not path:
            frappe.throw(_("Workflow configuration path is missing for {0}.").format(key))

        path_obj = Path(path)
        if not path_obj.is_absolute():
            fallback_base = Path(__file__).resolve().parents[2]
            candidate = (self.config_map_path.parent / path_obj).resolve()
            path_obj = candidate if candidate.exists() else (fallback_base / path_obj).resolve()
        return path_obj

    def _load_config_map(self) -> dict:
        if not self.config_map_path.exists():
            frappe.throw(_("Workflow configuration map file not found: {0}").format(self.config_map_path))
        raw = WorkflowEngine._load_structured_file(self.config_map_path)
        if not isinstance(raw, dict):
            frappe.throw(_("Workflow configuration map must be a mapping: {0}").format(self.config_map_path))
        return raw
