import json
import sys
import types

import pytest

from imogi_finance.workflows.workflow_engine import WorkflowConfigRegistry

frappe = sys.modules.setdefault("frappe", types.ModuleType("frappe"))
frappe._ = lambda msg, *args, **kwargs: msg
frappe.session = types.SimpleNamespace(user="approver@example.com")
frappe.get_roles = lambda: []


class WorkflowNotAllowed(Exception):
    pass


def _throw(message=None, *args, **kwargs):
    raise WorkflowNotAllowed(message)


frappe.throw = _throw


@pytest.fixture(autouse=True)
def _reset_frappe(monkeypatch):
    monkeypatch.setattr(frappe, "throw", _throw, raising=False)
    monkeypatch.setattr(frappe, "session", types.SimpleNamespace(user="approver@example.com"), raising=False)
    monkeypatch.setattr(frappe, "get_roles", lambda: [], raising=False)
    logger_calls = []

    class _Logger:
        def warning(self, *args, **kwargs):
            logger_calls.append((args, kwargs))

    monkeypatch.setattr(frappe, "logger", lambda *_args, **_kwargs: _Logger(), raising=False)
    return logger_calls


def test_registry_loads_engine_with_relative_path(tmp_path, monkeypatch):
    workflow_config = {
        "actions": [{"action": "Approve"}],
        "states": [{"state": "Pending Level 1"}],
        "transitions": [
            {"action": "Approve", "state": "Pending Level 1", "next_state": "Approved"},
        ],
    }
    workflow_path = tmp_path / "test_workflow.json"
    workflow_path.write_text(json.dumps(workflow_config))

    map_path = tmp_path / "workflow_config.yaml"
    map_path.write_text(json.dumps({"test": {"config": workflow_path.name}}))

    registry = WorkflowConfigRegistry(config_map_path=map_path)
    engine = registry.get_engine("test")

    doc = types.SimpleNamespace(level_1_role="Approver", level_1_user=None)
    monkeypatch.setattr(frappe, "get_roles", lambda: ["Approver"], raising=False)
    engine.guard_action(doc=doc, action="Approve", current_state="Pending Level 1", next_state="Approved")


def test_guard_action_raises_when_not_allowed(tmp_path, monkeypatch):
    workflow_config = {
        "actions": [{"action": "Approve"}],
        "states": [{"state": "Pending Level 1"}],
        "transitions": [
            {"action": "Approve", "state": "Pending Level 1", "next_state": "Approved"},
        ],
    }
    workflow_path = tmp_path / "restricted_workflow.json"
    workflow_path.write_text(json.dumps(workflow_config))

    map_path = tmp_path / "workflow_config.yaml"
    map_path.write_text(json.dumps({"restricted": {"config": workflow_path.name}}))

    registry = WorkflowConfigRegistry(config_map_path=map_path)
    engine = registry.get_engine("restricted")

    doc = types.SimpleNamespace(level_1_role="Approver", level_1_user=None)
    monkeypatch.setattr(frappe, "get_roles", lambda: [], raising=False)

    with pytest.raises(WorkflowNotAllowed):
        engine.guard_action(doc=doc, action="Approve", current_state="Pending Level 1", next_state="Approved")


def test_registry_missing_key_raises(tmp_path):
    map_path = tmp_path / "workflow_config.yaml"
    map_path.write_text(json.dumps({"known": {"config": "demo.json"}}))

    registry = WorkflowConfigRegistry(config_map_path=map_path)

    with pytest.raises(WorkflowNotAllowed):
        registry.get_engine("missing")
