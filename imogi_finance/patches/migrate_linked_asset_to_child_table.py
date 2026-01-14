"""
Migrate single linked_asset field to asset_links child table.

This patch migrates existing Expense Requests that have linked_asset populated
to use the new asset_links child table instead.
"""

import frappe


def execute():
    """Migrate linked_asset to asset_links child table."""
    
    # Get all Expense Requests with linked_asset
    expense_requests = frappe.get_all(
        "Expense Request",
        filters={
            "linked_asset": ["!=", ""]
        },
        fields=["name", "linked_asset"]
    )
    
    if not expense_requests:
        print("No Expense Requests with linked_asset found. Migration skipped.")
        return
    
    print(f"Found {len(expense_requests)} Expense Requests to migrate...")
    
    migrated_count = 0
    error_count = 0
    
    for er in expense_requests:
        try:
            # Get the Expense Request document
            doc = frappe.get_doc("Expense Request", er.name)
            
            # Skip if already migrated (asset_links has data)
            if doc.get("asset_links"):
                continue
            
            # Get asset details
            asset_name = er.linked_asset
            asset_doc = frappe.get_doc("Asset", asset_name)
            
            # Add to asset_links child table
            doc.append("asset_links", {
                "asset": asset_name,
                "asset_name": asset_doc.asset_name,
                "asset_category": asset_doc.asset_category,
                "asset_location": asset_doc.location,
                "status": asset_doc.status
            })
            
            # Save without triggering workflows
            doc.flags.ignore_validate = True
            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)
            
            migrated_count += 1
            
            if migrated_count % 10 == 0:
                print(f"Migrated {migrated_count} records...")
                frappe.db.commit()
            
        except Exception as e:
            error_count += 1
            print(f"Error migrating {er.name}: {str(e)}")
            frappe.log_error(
                title=f"Asset Link Migration Error - {er.name}",
                message=f"Error: {str(e)}"
            )
            continue
    
    frappe.db.commit()
    
    print(f"\nMigration complete!")
    print(f"Successfully migrated: {migrated_count}")
    print(f"Errors: {error_count}")
    print(f"Total processed: {len(expense_requests)}")
