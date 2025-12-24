import frappe


def execute():
    table = "tabGarage Vehicle Inspection"
    if not frappe.db.table_exists(table):
        return

    column_info = frappe.db.sql(
        f"SHOW COLUMNS FROM `{table}` LIKE 'name'", as_dict=True
    )
    if not column_info:
        return

    column_type = (column_info[0].get("Type") or "").lower()
    if column_type.startswith("int"):
        frappe.db.sql(f"ALTER TABLE `{table}` MODIFY `name` VARCHAR(140)")
