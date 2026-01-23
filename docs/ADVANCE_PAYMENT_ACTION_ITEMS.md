# Action Items: Menutup Gap dengan ERPNext v15 Standard

## Overview

Dokumen ini berisi **action items konkret** untuk menutup gap antara implementasi IMOGI Finance dengan ERPNext v15 standard advance payment, sambil mempertahankan keunggulan arsitektur IMOGI.

**Priority Legend**:
- 🔴 **P0 - Critical**: Untuk feature parity dengan ERPNext v15
- 🟡 **P1 - High**: Untuk enhanced functionality
- 🟢 **P2 - Medium**: Nice to have improvements
- 🔵 **P3 - Low**: Future enhancements

---

## Phase 1: Critical Feature Parity (P0)

### 🔴 Task 1.1: Enable Customer Advance Support

**Current State**: Hanya support Supplier dan Employee
**Target State**: Support Customer, Supplier, Employee

**Files to Modify**:

1. **`imogi_finance/advance_payment/workflow.py`**
```python
# Line 11 - UPDATE
ALLOWED_PARTIES = {"Supplier", "Employee", "Customer"}  # Add Customer

# Line 20-24 - UPDATE validation message
def on_payment_entry_validate(doc, method=None):
    if not is_advance_payment(doc):
        return

    if not doc.party:
        frappe.throw(_("Party is required for advance payments."))

    if doc.party_type not in ALLOWED_PARTIES:
        frappe.throw(_("Advance Payment is only supported for Supplier, Employee, or Customer."))

    # Add customer-specific validation
    if doc.party_type == "Customer":
        if doc.payment_type != "Receive":
            frappe.throw(_("Customer advances must use 'Receive' payment type."))
    elif doc.party_type == "Supplier":
        if doc.payment_type != "Pay":
            frappe.throw(_("Supplier advances must use 'Pay' payment type."))
    elif doc.party_type == "Employee":
        if doc.payment_type != "Pay":
            frappe.throw(_("Employee advances must use 'Pay' payment type."))

    amount = get_payment_amount(doc)
    if flt(amount) <= 0:
        frappe.throw(_("Advance Payment amount must be greater than zero."))
```

2. **`imogi_finance/advance_payment/api.py`**
```python
# Line 13 - UPDATE to include Sales Order
SUPPORTED_REFERENCE_DOCTYPES = {
    "Purchase Invoice",
    "Sales Invoice",       # Customer invoices
    "Expense Claim",
    "Payroll Entry",
    "Purchase Order",      # Supplier PO
    "Sales Order",         # NEW: Customer SO advance
    "Journal Entry",
    "Expense Request",
    "Branch Expense Request",
}
```

3. **`imogi_finance/public/js/advance_payment_allocation.js`**
```javascript
// Add Sales Invoice to doctype list
frappe.ui.form.on('Sales Invoice', {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Get Advances'), () => {
                show_advance_allocation_dialog(frm);
            }, __('Get Items From'));
        }
    }
});

frappe.ui.form.on('Sales Order', {
    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            // Show advance payment button
            frm.add_custom_button(__('Make Advance Payment'), () => {
                frappe.model.open_mapped_doc({
                    method: "erpnext.selling.doctype.sales_order.sales_order.make_payment_entry",
                    frm: frm
                });
            }, __('Create'));
        }
    }
});
```

4. **Update hooks in `imogi_finance/hooks.py`**
```python
doctype_js = {
    # ... existing ...
    "Sales Invoice": "public/js/advance_payment_allocation.js",
    "Sales Order": "public/js/advance_payment_allocation.js",
}

doc_events = {
    # ... existing ...
    "Sales Invoice": {
        "on_submit": "imogi_finance.advance_payment.api.on_reference_update",
        "on_update_after_submit": "imogi_finance.advance_payment.api.on_reference_update",
        "before_cancel": "imogi_finance.advance_payment.api.on_reference_before_cancel",
        "on_cancel": "imogi_finance.advance_payment.api.on_reference_cancel",
    },
    "Sales Order": {
        "on_submit": "imogi_finance.advance_payment.api.on_reference_update",
        "on_update_after_submit": "imogi_finance.advance_payment.api.on_reference_update",
    },
}
```

**Testing Checklist**:
- [ ] Create advance PE for Customer (payment_type = Receive)
- [ ] Verify APE created with Customer party
- [ ] Create Sales Invoice for same Customer
- [ ] Allocate advance to Sales Invoice
- [ ] Verify native_bridge syncs to SI.advances[]
- [ ] Check GL entries correct
- [ ] Cancel SI, verify APE allocation cleared
- [ ] Create advance PE for Sales Order
- [ ] Allocate to Sales Invoice created from SO

**Estimated Effort**: 4-6 hours
**Dependencies**: None
**Risk**: Low (straightforward extension)

---

### 🔴 Task 1.2: Implement Separate Advance Account Mode

**Current State**: Semua advance langsung ke Payable/Receivable
**Target State**: Optional separate advance accounts (Customer Advances, Supplier Advances)

#### Step 2.1: Add Company Custom Fields

**File**: `imogi_finance/fixtures/custom_field_company.json` (CREATE NEW)

```json
[
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "advance_payment_settings_section",
    "fieldtype": "Section Break",
    "label": "Advance Payment Settings",
    "insert_after": "book_deferred_entries_based_on",
    "collapsible": 1
  },
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "use_separate_advance_accounts",
    "fieldtype": "Check",
    "label": "Use Separate Advance Accounts",
    "insert_after": "advance_payment_settings_section",
    "description": "Enable to book advance payments in separate liability/asset accounts instead of party accounts"
  },
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "advance_accounts_column_break",
    "fieldtype": "Column Break",
    "insert_after": "use_separate_advance_accounts"
  },
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "default_customer_advance_account",
    "fieldtype": "Link",
    "options": "Account",
    "label": "Default Customer Advance Account",
    "insert_after": "advance_accounts_column_break",
    "depends_on": "use_separate_advance_accounts",
    "description": "Liability account for customer advances (e.g., 'Customer Advances - Company')"
  },
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "default_supplier_advance_account",
    "fieldtype": "Link",
    "options": "Account",
    "label": "Default Supplier Advance Account",
    "insert_after": "default_customer_advance_account",
    "depends_on": "use_separate_advance_accounts",
    "description": "Asset account for supplier advances (e.g., 'Supplier Advances - Company')"
  },
  {
    "doctype": "Custom Field",
    "dt": "Company",
    "fieldname": "default_employee_advance_account",
    "fieldtype": "Link",
    "options": "Account",
    "label": "Default Employee Advance Account",
    "insert_after": "default_supplier_advance_account",
    "depends_on": "use_separate_advance_accounts",
    "description": "Asset account for employee advances (e.g., 'Employee Advances - Company')"
  }
]
```

**Load Fixture**:
```python
# In imogi_finance/fixtures/__init__.py
fixtures = [
    # ... existing ...
    {"dt": "Custom Field", "filters": [["dt", "=", "Company"], ["fieldname", "like", "%advance%"]]},
]
```

#### Step 2.2: Auto-set Advance Account in Payment Entry

**File**: `imogi_finance/advance_payment/workflow.py`

```python
# Add after line 11
def get_advance_account(doc, company_doc=None):
    """
    Get the advance account for this payment based on company settings.
    Returns None if not using separate advance accounts.
    """
    if not company_doc:
        company_doc = frappe.get_cached_doc("Company", doc.company)
    
    if not company_doc.use_separate_advance_accounts:
        return None
    
    # Determine account based on party type
    if doc.party_type == "Customer":
        return company_doc.default_customer_advance_account
    elif doc.party_type == "Supplier":
        return company_doc.default_supplier_advance_account
    elif doc.party_type == "Employee":
        return company_doc.default_employee_advance_account
    
    return None


# Modify on_payment_entry_validate
def on_payment_entry_validate(doc, method=None):
    if not is_advance_payment(doc):
        return

    if not doc.party:
        frappe.throw(_("Party is required for advance payments."))

    if doc.party_type not in ALLOWED_PARTIES:
        frappe.throw(_("Advance Payment is only supported for Supplier, Employee, or Customer."))

    amount = get_payment_amount(doc)
    if flt(amount) <= 0:
        frappe.throw(_("Advance Payment amount must be greater than zero."))
    
    # NEW: Auto-set advance account if enabled
    company_doc = frappe.get_cached_doc("Company", doc.company)
    advance_account = get_advance_account(doc, company_doc)
    
    if advance_account:
        # Set appropriate account based on payment type
        if doc.payment_type == "Receive":
            doc.paid_from = advance_account
        elif doc.payment_type == "Pay":
            doc.paid_to = advance_account
        
        frappe.msgprint(
            _("Advance account {0} has been set based on company settings.").format(
                frappe.bold(advance_account)
            ),
            indicator="blue",
            alert=True
        )
```

#### Step 2.3: GL Entry untuk Advance Clearing (Optional)

**File**: `imogi_finance/advance_payment/gl_entries.py` (CREATE NEW)

```python
"""
GL Entries for Advance Payment Clearing
Only used when separate advance account mode is enabled.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate
from erpnext.accounts.general_ledger import make_gl_entries


def create_advance_clearing_entries(
    ape_name: str,
    invoice_doctype: str,
    invoice_name: str,
    allocated_amount: float,
    cancel: int = 0
) -> None:
    """
    Create GL entries to clear advance account and reduce invoice outstanding.
    
    This is called only when:
    1. Company.use_separate_advance_accounts = True
    2. Allocation is being made between APE and Invoice
    
    Args:
        ape_name: Advance Payment Entry name
        invoice_doctype: Purchase Invoice, Sales Invoice, etc.
        invoice_name: Invoice name
        allocated_amount: Amount being allocated
        cancel: 1 if cancelling, 0 if posting
    """
    # Get APE and Company settings
    ape = frappe.get_doc("Advance Payment Entry", ape_name)
    company = frappe.get_cached_doc("Company", ape.company)
    
    # Skip if not using separate advance accounts
    if not company.use_separate_advance_accounts:
        return
    
    # Get accounts
    advance_account = get_advance_account_from_ape(ape, company)
    party_account = get_party_account_from_invoice(invoice_doctype, invoice_name)
    
    if not advance_account or not party_account:
        frappe.throw(_("Could not determine advance or party account for GL entry."))
    
    # Get invoice for posting date
    invoice = frappe.get_doc(invoice_doctype, invoice_name)
    posting_date = getdate(invoice.posting_date)
    
    # Build GL entries
    gl_entries = []
    
    # Determine Dr/Cr based on party type
    if ape.party_type == "Supplier":
        # Supplier advance: Clear asset, reduce liability
        # Dr: Accounts Payable (reduce liability)
        # Cr: Supplier Advances (clear asset)
        gl_entries.append({
            "account": party_account,
            "debit": flt(allocated_amount),
            "credit": 0,
            "party_type": ape.party_type,
            "party": ape.party,
            "against": advance_account,
            "against_voucher_type": invoice_doctype,
            "against_voucher": invoice_name,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
        
        gl_entries.append({
            "account": advance_account,
            "debit": 0,
            "credit": flt(allocated_amount),
            "party_type": ape.party_type,
            "party": ape.party,
            "against": party_account,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
    
    elif ape.party_type == "Customer":
        # Customer advance: Clear liability, reduce asset
        # Dr: Customer Advances (clear liability)
        # Cr: Accounts Receivable (reduce asset)
        gl_entries.append({
            "account": advance_account,
            "debit": flt(allocated_amount),
            "credit": 0,
            "party_type": ape.party_type,
            "party": ape.party,
            "against": party_account,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
        
        gl_entries.append({
            "account": party_account,
            "debit": 0,
            "credit": flt(allocated_amount),
            "party_type": ape.party_type,
            "party": ape.party,
            "against": advance_account,
            "against_voucher_type": invoice_doctype,
            "against_voucher": invoice_name,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
    
    elif ape.party_type == "Employee":
        # Employee advance: Clear asset, reduce liability (expense claim)
        gl_entries.append({
            "account": party_account,
            "debit": flt(allocated_amount),
            "credit": 0,
            "party_type": ape.party_type,
            "party": ape.party,
            "against": advance_account,
            "against_voucher_type": invoice_doctype,
            "against_voucher": invoice_name,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
        
        gl_entries.append({
            "account": advance_account,
            "debit": 0,
            "credit": flt(allocated_amount),
            "party_type": ape.party_type,
            "party": ape.party,
            "against": party_account,
            "voucher_type": "Advance Payment Entry",
            "voucher_no": ape_name,
            "posting_date": posting_date,
            "company": ape.company,
            "remarks": f"Advance cleared for {invoice_doctype} {invoice_name}",
        })
    
    # Post GL entries
    if gl_entries:
        make_gl_entries(gl_entries, cancel=cancel, adv_adj=True)
        
        frappe.logger().info(
            f"{'Cancelled' if cancel else 'Posted'} advance clearing GL entries: "
            f"APE {ape_name} → {invoice_doctype} {invoice_name} = {allocated_amount}"
        )


def get_advance_account_from_ape(ape, company):
    """Get advance account from APE party type"""
    if ape.party_type == "Customer":
        return company.default_customer_advance_account
    elif ape.party_type == "Supplier":
        return company.default_supplier_advance_account
    elif ape.party_type == "Employee":
        return company.default_employee_advance_account
    return None


def get_party_account_from_invoice(invoice_doctype, invoice_name):
    """Get party account from invoice"""
    if invoice_doctype == "Purchase Invoice":
        return frappe.db.get_value("Purchase Invoice", invoice_name, "credit_to")
    elif invoice_doctype == "Sales Invoice":
        return frappe.db.get_value("Sales Invoice", invoice_name, "debit_to")
    elif invoice_doctype == "Expense Claim":
        return frappe.db.get_value("Expense Claim", invoice_name, "payable_account")
    return None
```

#### Step 2.4: Integrate GL Entries with APE

**File**: `imogi_finance/imogi_finance/doctype/advance_payment_entry/advance_payment_entry.py`

```python
# Add after line 93 (in allocate_reference method)
        # NATIVE BRIDGE: Sync to ERPNext native advances table
        if self.payment_entry and invoice_doctype in ["Purchase Invoice", "Sales Invoice"]:
            from imogi_finance.advance_payment.native_bridge import sync_allocation_to_native_advances
            
            result = sync_allocation_to_native_advances(
                payment_entry=self.payment_entry,
                invoice_doctype=invoice_doctype,
                invoice_name=invoice_name,
                allocated_amount=allocated_amount,
                reference_exchange_rate=reference_exchange_rate or self.exchange_rate
            )
            
            # NEW: Create GL entries if using separate advance accounts
            company = frappe.get_cached_doc("Company", self.company)
            if company.use_separate_advance_accounts:
                from imogi_finance.advance_payment.gl_entries import create_advance_clearing_entries
                
                create_advance_clearing_entries(
                    ape_name=self.name,
                    invoice_doctype=invoice_doctype,
                    invoice_name=invoice_name,
                    allocated_amount=allocated_amount,
                    cancel=0
                )
```

**Also update clear_reference_allocations**:
```python
    def clear_reference_allocations(self, invoice_doctype: str, invoice_name: str) -> None:
        # ... existing code ...
        
        # NEW: Cancel GL entries if using separate advance accounts
        company = frappe.get_cached_doc("Company", self.company)
        if company.use_separate_advance_accounts and self.docstatus == 1:
            from imogi_finance.advance_payment.gl_entries import create_advance_clearing_entries
            
            create_advance_clearing_entries(
                ape_name=self.name,
                invoice_doctype=invoice_doctype,
                invoice_name=invoice_name,
                allocated_amount=flt(cleared_row.allocated_amount),
                cancel=1  # Cancel GL
            )
```

**Testing Checklist**:
- [ ] Enable "Use Separate Advance Accounts" in Company
- [ ] Set advance accounts for each party type
- [ ] Create advance PE → verify account auto-set
- [ ] Allocate to invoice → verify GL entries created
- [ ] Check GL Entry: Advance account cleared, Party account reduced
- [ ] Cancel allocation → verify GL reversed
- [ ] Test with multi-currency
- [ ] Test without enabling setting → verify native flow works

**Estimated Effort**: 12-16 hours
**Dependencies**: Task 1.1
**Risk**: Medium (accounting logic)

---

## Phase 2: Enhanced Functionality (P1)

### 🟡 Task 2.1: Payment Terms Support

**Investigate and test current support for payment_schedule table**

**File**: `imogi_finance/advance_payment/native_bridge.py`

```python
# Add after sync_allocation_to_native_advances

def update_payment_schedule(invoice, payment_entry, allocated_amount, payment_term=None):
    """
    Update payment schedule table when advance is allocated.
    
    Args:
        invoice: Invoice document
        payment_entry: Payment Entry name
        allocated_amount: Amount allocated
        payment_term: Specific payment term (optional)
    """
    if not hasattr(invoice, "payment_schedule") or not invoice.payment_schedule:
        return  # No payment terms
    
    if payment_term:
        # Update specific term
        for row in invoice.payment_schedule:
            if row.payment_term == payment_term:
                row.paid_amount = flt(row.paid_amount) + flt(allocated_amount)
                break
    else:
        # Distribute to terms proportionally
        total_outstanding = sum(flt(row.payment_amount) - flt(row.paid_amount or 0) 
                               for row in invoice.payment_schedule)
        
        remaining = flt(allocated_amount)
        for row in invoice.payment_schedule:
            if remaining <= 0:
                break
            
            term_outstanding = flt(row.payment_amount) - flt(row.paid_amount or 0)
            if term_outstanding > 0:
                term_allocation = min(remaining, term_outstanding)
                row.paid_amount = flt(row.paid_amount) + term_allocation
                remaining -= term_allocation
    
    frappe.logger().info(
        f"Updated payment schedule for {invoice.doctype} {invoice.name}: "
        f"allocated {allocated_amount} to {'specific term' if payment_term else 'proportional terms'}"
    )
```

**Testing**: Create test case with payment terms

**Estimated Effort**: 6-8 hours
**Dependencies**: Task 1.1, 1.2
**Risk**: Low

---

### 🟡 Task 2.2: Budget Control Integration

**Implement budget checking for advance payments**

**File**: `imogi_finance/advance_payment/budget_control.py` (CREATE NEW)

```python
"""
Budget Control for Advance Payments
Integrates APE with existing budget control system
"""

import frappe
from frappe import _
from frappe.utils import flt


def check_budget_for_advance(ape_doc):
    """
    Check budget before creating/submitting advance payment.
    
    Called from APE.validate() or APE.on_submit()
    """
    # Get company budget settings
    company = frappe.get_cached_doc("Company", ape_doc.company)
    
    # Skip if budget control not enabled
    if not frappe.db.get_single_value("Accounts Settings", "check_budget_on_payment_entry"):
        return
    
    # Get cost center from payment entry
    if not ape_doc.payment_entry:
        return
    
    pe = frappe.get_doc("Payment Entry", ape_doc.payment_entry)
    cost_center = getattr(pe, "cost_center", None)
    
    if not cost_center:
        return
    
    # Import budget control
    from imogi_finance.budget_control.checker import check_budget_available
    
    # Check budget
    try:
        check_budget_available(
            cost_center=cost_center,
            expense_account=get_expense_account_for_party(ape_doc.party_type),
            amount=flt(ape_doc.advance_amount),
            posting_date=ape_doc.posting_date,
            company=ape_doc.company,
            voucher_type="Advance Payment Entry",
            voucher_no=ape_doc.name
        )
    except frappe.ValidationError as e:
        # Re-throw with APE context
        frappe.throw(
            _("Budget exceeded for advance payment: {0}").format(str(e)),
            title=_("Budget Control")
        )


def get_expense_account_for_party(party_type):
    """Get default expense account for budget checking"""
    if party_type == "Supplier":
        return frappe.db.get_single_value("Buying Settings", "default_expense_account")
    elif party_type == "Employee":
        return frappe.db.get_single_value("HR Settings", "payroll_payable_account")
    return None
```

**Integrate in APE**:
```python
# advance_payment_entry.py
def validate(self):
    # ... existing ...
    
    # NEW: Budget check
    if self.docstatus < 1:  # Before submit
        from imogi_finance.advance_payment.budget_control import check_budget_for_advance
        check_budget_for_advance(self)
```

**Estimated Effort**: 4-6 hours
**Dependencies**: Existing budget control module
**Risk**: Low

---

## Phase 3: Reporting & Analytics (P2)

### 🟢 Task 3.1: Advance Payment Dashboard

**Create comprehensive dashboard for advance tracking**

**File**: `imogi_finance/imogi_finance/page/advance_payment_dashboard/advance_payment_dashboard.json`

```json
{
  "name": "Advance Payment Dashboard",
  "page_name": "advance-payment-dashboard",
  "title": "Advance Payment Dashboard",
  "icon": "money",
  "module": "Imogi Finance",
  "standard": "Yes"
}
```

**Charts to Include**:
1. Unallocated Advances by Party Type (Donut)
2. Advance Aging (Bar)
3. Monthly Advance Trend (Line)
4. Top 10 Parties with Advances (Bar)
5. Allocation Rate (%)

**Estimated Effort**: 16-20 hours
**Dependencies**: None
**Risk**: Low

---

### 🟢 Task 3.2: Custom Reports

**Create reports**:

1. **Unallocated Advances Report**
   - Show all APE with unallocated_amount > 0
   - Group by party, company, branch
   - Aging buckets: 0-30, 31-60, 61-90, 90+ days

2. **Advance Allocation History Report**
   - Show all allocations
   - From APE to invoices
   - Track who allocated when

3. **Advance Reconciliation Report**
   - Compare APE vs Invoice.advances
   - Flag mismatches
   - Audit trail

**Estimated Effort**: 12-16 hours
**Dependencies**: None
**Risk**: Low

---

## Phase 4: Performance & Optimization (P3)

### 🔵 Task 4.1: Query Optimization

**Add indexes**:
```python
# In advance_payment_entry.json
{
  "indexes": [
    "party_type,party,docstatus,unallocated_amount",
    "company,status,docstatus",
    "posting_date,company,docstatus"
  ]
}
```

### 🔵 Task 4.2: Caching Layer

**Implement Redis caching for frequently accessed APE data**

---

## Implementation Timeline

```
Week 1-2: Phase 1 (Critical)
├─ Day 1-2: Task 1.1 (Customer support)
├─ Day 3-5: Task 1.2 (Separate accounts - Step 1 & 2)
└─ Day 6-10: Task 1.2 (GL entries - Step 3 & 4)

Week 3: Phase 2 (Enhanced)
├─ Day 1-3: Task 2.1 (Payment terms)
└─ Day 4-5: Task 2.2 (Budget control)

Week 4-5: Phase 3 (Reporting)
├─ Week 4: Task 3.1 (Dashboard)
└─ Week 5: Task 3.2 (Reports)

Week 6: Testing & Documentation
├─ Integration testing
├─ User acceptance testing
└─ Documentation updates
```

---

## Success Criteria

### Phase 1 Complete ✅
- [ ] Customer advances work end-to-end
- [ ] Separate advance account mode functional
- [ ] All existing tests pass
- [ ] GL entries balanced and correct

### Phase 2 Complete ✅
- [ ] Payment terms allocation works
- [ ] Budget control prevents over-spending
- [ ] All edge cases handled

### Phase 3 Complete ✅
- [ ] Dashboard deployed and accessible
- [ ] Reports generating correct data
- [ ] Users trained on new features

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| GL entries incorrect | Medium | High | Thorough testing, peer review, staging deployment |
| Performance degradation | Low | Medium | Query optimization, indexes, caching |
| User confusion | Medium | Low | Training, documentation, tooltips |
| Data migration needed | Low | High | Backward compatibility, migration script |

---

## Rollout Plan

### Stage 1: Development (Week 1-3)
- Feature development
- Unit testing
- Code review

### Stage 2: Staging (Week 4)
- Deploy to staging
- Integration testing
- UAT with key users

### Stage 3: Production (Week 5-6)
- Gradual rollout (10% → 50% → 100%)
- Monitor performance
- Support tickets

### Stage 4: Post-Launch (Week 7+)
- Gather feedback
- Bug fixes
- Documentation improvements

---

## Conclusion

Following this action plan akan membuat IMOGI Finance advance payment system **complete parity dengan ERPNext v15** sambil **mempertahankan keunggulan arsitektur** yang sudah ada.

**Total Estimated Effort**: 60-80 hours (1.5-2 months dengan 1 developer)

**Priority Order**:
1. 🔴 Phase 1 (Critical) - 20-24 hours
2. 🟡 Phase 2 (Enhanced) - 10-14 hours
3. 🟢 Phase 3 (Reporting) - 28-36 hours
4. 🔵 Phase 4 (Optimization) - As needed

**Next Steps**:
1. Review dan approve action plan
2. Assign tasks ke developer
3. Setup project tracking (GitHub Issues/Projects)
4. Begin Phase 1 implementation

---

**Document Version**: 1.0  
**Created**: 2026-01-23  
**Author**: GitHub Copilot for IMOGI Finance Team
