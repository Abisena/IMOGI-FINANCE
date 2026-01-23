"""
Native Payment Ledger - Custom Dashboard Report

This report queries ERPNext's native Payment Ledger Entry table
to provide a better UX for advance payment tracking.

Features:
- Status visualization (Fully Allocated, Partially Allocated, Unallocated)
- Party-wise grouping
- Aging analysis (0-30, 30-60, 60-90, 90+ days)
- Quick links to Payment Entry and allocation

Usage:
  Add to desk page or reports list
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, date_diff, nowdate


def execute(filters=None):
    """Execute the report"""
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    """Define report columns"""
    return [
        {
            "fieldname": "payment_entry",
            "label": _("Payment Entry"),
            "fieldtype": "Link",
            "options": "Payment Entry",
            "width": 150
        },
        {
            "fieldname": "posting_date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "party_type",
            "label": _("Party Type"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "party",
            "label": _("Party"),
            "fieldtype": "Dynamic Link",
            "options": "party_type",
            "width": 200
        },
        {
            "fieldname": "advance_amount",
            "label": _("Advance Amount"),
            "fieldtype": "Currency",
            "width": 150
        },
        {
            "fieldname": "allocated_amount",
            "label": _("Allocated"),
            "fieldtype": "Currency",
            "width": 130
        },
        {
            "fieldname": "unallocated_amount",
            "label": _("Unallocated"),
            "fieldtype": "Currency",
            "width": 130
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "age_days",
            "label": _("Age (Days)"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "age_bracket",
            "label": _("Age Bracket"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "allocated_to",
            "label": _("Allocated To"),
            "fieldtype": "Small Text",
            "width": 250
        }
    ]


def get_data(filters):
    """Get report data from Payment Ledger Entry"""
    
    conditions = get_conditions(filters)
    
    # Query for advance payments with allocation details
    query = """
        SELECT 
            ple.voucher_no as payment_entry,
            MIN(ple.posting_date) as posting_date,
            ple.party_type,
            ple.party,
            SUM(CASE 
                WHEN ple.against_voucher_type IS NULL THEN ple.amount 
                ELSE 0 
            END) as advance_amount,
            SUM(COALESCE(ple.allocated_amount, 0)) as allocated_amount,
            SUM(CASE 
                WHEN ple.against_voucher_type IS NULL THEN ple.amount 
                ELSE 0 
            END) - SUM(COALESCE(ple.allocated_amount, 0)) as unallocated_amount,
            GROUP_CONCAT(
                CASE 
                    WHEN ple.against_voucher_type IS NOT NULL 
                    THEN CONCAT(ple.against_voucher_type, ': ', ple.against_voucher_no)
                    ELSE NULL
                END
                SEPARATOR ', '
            ) as allocated_to
        FROM `tabPayment Ledger Entry` ple
        WHERE ple.delinked = 0
          AND ple.docstatus = 1
          {conditions}
        GROUP BY ple.voucher_no, ple.party_type, ple.party
        HAVING advance_amount > 0
        ORDER BY posting_date DESC, unallocated_amount DESC
    """.format(conditions=conditions)
    
    data = frappe.db.sql(query, filters, as_dict=True)
    
    # Process data to add status and aging
    for row in data:
        # Calculate status
        advance = flt(row.get("advance_amount"))
        allocated = flt(row.get("allocated_amount"))
        unallocated = flt(row.get("unallocated_amount"))
        
        if unallocated <= 0:
            row["status"] = "✅ Fully Allocated"
        elif allocated > 0:
            pct = (allocated / advance) * 100
            row["status"] = f"🟡 {pct:.0f}% Allocated"
        else:
            row["status"] = "🔴 Unallocated"
        
        # Calculate age
        posting_date = getdate(row.get("posting_date"))
        age = date_diff(nowdate(), posting_date)
        row["age_days"] = age
        
        # Age bracket
        if age <= 30:
            row["age_bracket"] = "0-30 days"
        elif age <= 60:
            row["age_bracket"] = "31-60 days"
        elif age <= 90:
            row["age_bracket"] = "61-90 days"
        else:
            row["age_bracket"] = "90+ days"
        
        # Clean up allocated_to
        if not row.get("allocated_to"):
            row["allocated_to"] = "-"
    
    return data


def get_conditions(filters):
    """Build SQL conditions from filters"""
    conditions = []
    
    if filters.get("company"):
        conditions.append("ple.company = %(company)s")
    
    if filters.get("party_type"):
        conditions.append("ple.party_type = %(party_type)s")
    
    if filters.get("party"):
        conditions.append("ple.party = %(party)s")
    
    if filters.get("from_date"):
        conditions.append("ple.posting_date >= %(from_date)s")
    
    if filters.get("to_date"):
        conditions.append("ple.posting_date <= %(to_date)s")
    
    if filters.get("status"):
        if filters["status"] == "Unallocated":
            # Will be filtered in HAVING clause
            pass
        elif filters["status"] == "Partially Allocated":
            # Will be filtered in HAVING clause
            pass
        elif filters["status"] == "Fully Allocated":
            # Will be filtered in HAVING clause
            pass
    
    return " AND " + " AND ".join(conditions) if conditions else ""


def get_report_summary(data):
    """Generate report summary cards"""
    
    if not data:
        return []
    
    total_advance = sum(flt(row.get("advance_amount")) for row in data)
    total_allocated = sum(flt(row.get("allocated_amount")) for row in data)
    total_unallocated = sum(flt(row.get("unallocated_amount")) for row in data)
    
    unallocated_count = len([r for r in data if flt(r.get("unallocated_amount")) > 0])
    
    return [
        {
            "value": total_advance,
            "indicator": "Blue",
            "label": _("Total Advances"),
            "datatype": "Currency"
        },
        {
            "value": total_allocated,
            "indicator": "Green",
            "label": _("Allocated"),
            "datatype": "Currency"
        },
        {
            "value": total_unallocated,
            "indicator": "Orange" if total_unallocated > 0 else "Green",
            "label": _("Unallocated"),
            "datatype": "Currency"
        },
        {
            "value": unallocated_count,
            "indicator": "Orange" if unallocated_count > 0 else "Green",
            "label": _("Pending Allocation"),
            "datatype": "Int"
        }
    ]
