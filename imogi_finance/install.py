import frappe


def before_install():
    """Clean up legacy custom fields that conflict with standard DocType fields."""
    ensure_role_exists("Budget Controller")
    duplicates = frappe.get_all(
        "Custom Field",
        filters={"dt": "Expense Request", "fieldname": "workflow_state"},
        pluck="name",
    )
    for name in duplicates:
        frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)


def ensure_role_exists(role_name: str) -> None:
    """Ensure the specified role exists to satisfy link validations during install."""
    if frappe.db.exists("Role", {"role_name": role_name}):
        return

    role = frappe.new_doc("Role")
    role.role_name = role_name
    role.desk_access = 1
    role.insert(ignore_permissions=True)
