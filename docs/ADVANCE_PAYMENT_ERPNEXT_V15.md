# Advance Payment Flow - ERPNext v15 Documentation

## Table of Contents
1. [Overview](#overview)
2. [Configuration & Settings](#configuration--settings)
3. [Payment Flow](#payment-flow)
4. [Reconciliation Process](#reconciliation-process)
5. [Accounting Entries](#accounting-entries)
6. [Key Methods & Functions](#key-methods--functions)
7. [Important Fields](#important-fields)
8. [Use Cases & Examples](#use-cases--examples)

---

## Overview

Advance payment di ERPNext v15 adalah pembayaran yang diterima dari Customer atau dibayar ke Supplier **sebelum** invoice dibuat. System mendukung 2 mode:

1. **Normal Mode**: Advance dicatat langsung ke Party Account (Receivable/Payable)
2. **Separate Advance Account Mode**: Advance dicatat ke akun liability/asset terpisah

---

## Configuration & Settings

### 1. Company Settings

**Location**: `Company` DocType

**Field**: `book_advance_payments_in_separate_party_account` (Check)

**Ketika Enabled**:
- Advance payments dicatat di akun terpisah
- Memerlukan konfigurasi advance accounts

**Required Accounts**:
```python
# Untuk Customer (Sales)
default_advance_received_account  # Liability Account
  - Account Type: Payable
  - Menyimpan advance yang diterima dari customer
  
# Untuk Supplier (Purchase)  
default_advance_paid_account  # Asset Account
  - Account Type: Receivable
  - Menyimpan advance yang dibayar ke supplier
```

**Cara Setting**:
1. Go to: Company Master
2. Enable: "Book Advance Payments in Separate Party Account"
3. Set: Default Advance Received Account (e.g., "Customer Advances - Company")
4. Set: Default Advance Paid Account (e.g., "Supplier Advances - Company")

### 2. Accounts Settings

**Location**: `Accounts Settings` DocType

**Relevant Settings**:
```python
show_party_balance = 1  # Show party balance in Payment Entry
show_account_balance = 1  # Show account balance in Payment Entry
```

### 3. Account Configuration

**Chart of Accounts Structure**:
```
Assets
  └── Current Assets
      └── Supplier Advances - [Company]
      
Liabilities
  └── Current Liabilities
      └── Customer Advances - [Company]
```

---

## Payment Flow

### Flow 1: Advance Payment (Tanpa Invoice)

#### For Customer (Receive Advance)

**Step 1: Create Payment Entry**
```
Payment Type: Receive
Party Type: Customer
Party: [Select Customer]
Paid From: [Customer Account / Advance Account]
Paid To: [Bank Account]
References: [Empty atau Sales Order]
```

**Conditions**:
- Jika `book_advance_payments_in_separate_party_account` = True
  - `paid_from` = Default Advance Received Account
  - `is_opening` = "No"
- Jika References = Sales Order → dianggap advance
- Jika References = kosong → unallocated advance

**Step 2: System Logic**
```python
def set_liability_account(self):
    # Auto setting liability account during 'draft' status
    if self.docstatus > 0 or self.payment_type == "Internal Transfer":
        return
        
    if not frappe.db.get_value("Company", self.company, 
        "book_advance_payments_in_separate_party_account"):
        return
        
    # Set separate advance account
    accounts = get_party_account(self.party_type, self.party, 
        self.company, include_advance=True)
    liability_account = accounts[1] if len(accounts) > 1 else None
    
    self.set(self.party_account_field, liability_account)
```

#### For Supplier (Pay Advance)

**Step 1: Create Payment Entry**
```
Payment Type: Pay
Party Type: Supplier
Party: [Select Supplier]
Paid From: [Bank Account]
Paid To: [Supplier Account / Advance Account]
References: [Empty atau Purchase Order]
```

---

### Flow 2: Regular Payment (Against Invoice)

#### Payment Against Sales Invoice

**Step 1: Create Payment Entry**
```
Payment Type: Receive
Party Type: Customer
References: [Select Sales Invoice]
Allocated Amount: [Amount to allocate]
```

**System Behavior**:
- `book_advance_payments_in_separate_party_account` = False (automatically)
- Uses normal party account (Accounts Receivable)
- No advance account involved

---

### Flow 3: Advance Allocation (Reconcile Advance to Invoice)

#### Scenario: Customer sudah bayar advance, sekarang ada invoice

**Method 1: Get Advances Automatically**

Saat membuat Payment Entry untuk Invoice:
```python
# System automatically calls
get_outstanding_reference_documents({
    "party_type": "Customer",
    "party": "CUST-001",
    "posting_date": "2026-01-23",
    "company": "My Company",
    "get_outstanding_invoices": True,
    "get_orders_to_be_billed": False
})
```

**Method 2: Manual Allocation**

1. Open Sales Invoice/Purchase Invoice
2. Click "Get Advances" button
3. System fetch available advances from:
   - Payment Entries with Sales Order reference
   - Payment Entries without any reference (unallocated)
4. Select advance to allocate
5. Save & Submit

**System Function**:
```python
def delink_advance_entries(payment_entry_name):
    """
    Called when invoice is cancelled
    Remove advance allocation from invoice
    """
    # Remove reference from Payment Entry
    # Restore advance as unallocated
```

---

## Reconciliation Process

### Automatic Reconciliation

**Ketika Payment Entry di-submit dengan reference ke Invoice**:

```python
def make_advance_gl_entries(self, cancel=0):
    """
    Create GL entries for advance reconciliation
    """
    if self.book_advance_payments_in_separate_party_account:
        for ref in self.references:
            if ref.reference_doctype in ("Sales Invoice", "Purchase Invoice"):
                self.add_advance_gl_for_reference(gl_entries, ref)
```

**Process**:
1. Check if invoice has advance allocated
2. Get `reconcile_effect_on` date (posting date of reconciliation)
3. Create GL entries to clear advance vs invoice outstanding

### Reconciliation Effect Date

```python
def get_reconciliation_effect_date(reference_doctype, reference_name, 
                                   company, posting_date):
    """
    Determine the effective date for reconciliation
    Used for accurate GL posting
    """
    # Returns the date when reconciliation should take effect
    # Important for backdated entries
```

---

## Accounting Entries

### Entry 1: Receive Advance (Separate Account Mode)

**Payment Entry** - Customer pays advance
```
Dr: Bank Account                    10,000
  Cr: Customer Advances - XYZ              10,000
```

**GL Entry Details**:
```python
{
    "account": "Bank Account",
    "debit": 10000,
    "credit": 0,
    "against": "Customer Advances - XYZ"
}
{
    "account": "Customer Advances - XYZ",  # Liability account
    "debit": 0,
    "credit": 10000,
    "party_type": "Customer",
    "party": "CUST-001",
    "against_voucher_type": "Payment Entry",
    "against_voucher": "PE-00001"
}
```

---

### Entry 2: Create Sales Invoice

**Sales Invoice** - Invoice created
```
Dr: Accounts Receivable - CUST-001    11,800
  Cr: Sales                                  10,000
  Cr: Output Tax (PPN 11%)                    1,100
  Cr: Rounding                                  700
```

**Outstanding Amount** = 11,800

---

### Entry 3: Allocate Advance to Invoice

**Payment Entry** - Allocate advance to invoice
```
# Main payment entry (if any additional payment)
Dr: Bank Account                     1,800
  Cr: Accounts Receivable - CUST-001         1,800

# Advance allocation entry (automatically created)
Dr: Customer Advances - XYZ         10,000
  Cr: Accounts Receivable - CUST-001        10,000
```

**GL Entry Details**:
```python
# Main party GL (for additional payment)
{
    "account": "Accounts Receivable - CUST-001",
    "debit": 0,
    "credit": 1800,
    "party_type": "Customer",
    "party": "CUST-001",
    "against_voucher_type": "Sales Invoice",
    "against_voucher": "SINV-00001"
}

# Advance clearing GL
{
    "account": "Customer Advances - XYZ",
    "debit": 10000,  # Clear advance
    "credit": 0,
    "party_type": "Customer",
    "party": "CUST-001",
    "against_voucher_type": "Sales Invoice",
    "against_voucher": "SINV-00001",
    "advance_voucher_type": "Payment Entry",
    "advance_voucher_no": "PE-00001"  # Original advance PE
}
{
    "account": "Accounts Receivable - CUST-001",
    "debit": 0,
    "credit": 10000,  # Reduce receivable
    "party_type": "Customer",
    "party": "CUST-001",
    "against_voucher_type": "Sales Invoice",
    "against_voucher": "SINV-00001"
}
```

**Result**:
- Customer Advances balance: 0
- Accounts Receivable outstanding: 0 (11,800 - 10,000 - 1,800)

---

### Entry 4: Normal Payment Mode (No Separate Account)

**Payment Entry** - Customer pays advance
```
Dr: Bank Account                    10,000
  Cr: Accounts Receivable - CUST-001        10,000
```

**Characteristics**:
- Recorded directly to Receivable/Payable
- No advance account involved
- Simpler but less tracking

---

## Key Methods & Functions

### 1. Payment Entry Methods

```python
class PaymentEntry:
    
    def set_liability_account(self):
        """
        Auto-set advance liability account if enabled
        Called during validate
        """
        # Check company setting
        # Determine if advance account should be used
        # Set party_account accordingly
        
    def make_advance_gl_entries(self, cancel=0):
        """
        Create GL entries for advance allocation
        Called during submit/cancel
        """
        if self.book_advance_payments_in_separate_party_account:
            for ref in self.references:
                if ref.reference_doctype in ("Sales Invoice", "Purchase Invoice"):
                    self.add_advance_gl_for_reference(gl_entries, ref)
    
    def add_advance_gl_for_reference(self, gl_entries, invoice):
        """
        Add specific GL entry for advance allocation
        """
        # Determine Dr/Cr based on invoice type
        # Calculate allocated amount
        # Create clearing entries
        
    def delink_advance_entry_references(self):
        """
        Remove advance allocation when PE is cancelled
        """
        for reference in self.references:
            if reference.reference_doctype in ("Sales Invoice", "Purchase Invoice"):
                doc = frappe.get_doc(reference.reference_doctype, 
                                    reference.reference_name)
                doc.delink_advance_entries(self.name)
    
    def get_dr_and_account_for_advances(self, reference):
        """
        Determine debit/credit and account for advance allocation
        Returns: (dr_or_cr, account)
        """
        if reference.reference_doctype == "Sales Invoice":
            return "credit", reference.account
        elif reference.reference_doctype == "Purchase Invoice":
            return "debit", reference.account
```

---

### 2. Utility Functions

```python
def get_outstanding_reference_documents(args, validate=False):
    """
    Get outstanding invoices and orders for payment allocation
    
    Args:
        args: {
            "party_type": "Customer",
            "party": "CUST-001",
            "company": "My Company",
            "posting_date": "2026-01-23",
            "get_outstanding_invoices": True,
            "get_orders_to_be_billed": True,
            "book_advance_payments_in_separate_party_account": True
        }
    
    Returns: List of outstanding documents with amounts
    """
    # Get party account
    # Handle advance account if enabled
    # Fetch outstanding invoices
    # Fetch orders for advance
    # Return combined list

def get_advance_payment_doctypes():
    """
    Returns list of doctypes considered as advance payments
    """
    return ["Sales Order", "Purchase Order"]

def get_party_account(party_type, party, company, include_advance=False):
    """
    Get party account(s)
    
    Args:
        include_advance: If True, returns [normal_account, advance_account]
    
    Returns:
        - Single account (string) if include_advance=False
        - List [normal_account, advance_account] if include_advance=True
    """

def get_reconciliation_effect_date(reference_doctype, reference_name, 
                                   company, posting_date):
    """
    Get the effective date for reconciliation
    Important for backdated entries
    """
```

---

### 3. Invoice Methods

```python
class SalesInvoice:
    
    def delink_advance_entries(self, payment_entry_name):
        """
        Remove advance allocation from invoice
        Called when payment entry is cancelled
        """
        # Find advance entries linked to this invoice
        # Remove the linkage
        # Restore advance as unallocated
        
    def get_advance_entries(self):
        """
        Get available advances for this customer
        Returns list of advance payment entries
        """
        # Query Payment Entry with:
        #   - Same customer
        #   - References to Sales Order or no reference
        #   - Has unallocated amount
```

---

## Important Fields

### Payment Entry Fields

```python
# Main Fields
payment_type = "Receive" | "Pay" | "Internal Transfer"
party_type = "Customer" | "Supplier" | "Employee"
party = Link to party
posting_date = Date of payment
reference_date = Reference date for transaction

# Account Fields
paid_from = Link(Account)  # Source account
paid_to = Link(Account)    # Destination account
paid_from_account_currency = Currency
paid_to_account_currency = Currency
party_account = Link(Account)  # Auto-set based on party
party_account_currency = Currency

# Amount Fields
paid_amount = Currency
received_amount = Currency
source_exchange_rate = Float
target_exchange_rate = Float
total_allocated_amount = Currency
unallocated_amount = Currency

# Advance Control
book_advance_payments_in_separate_party_account = Check
is_opening = "Yes" | "No"

# Status
status = "Draft" | "Submitted" | "Cancelled"
```

---

### Payment Entry Reference (Child Table)

```python
# Reference Document
reference_doctype = "Sales Invoice" | "Purchase Invoice" | "Sales Order" | "Purchase Order" | "Journal Entry"
reference_name = Link to reference document
payment_term = Link(Payment Term) # For split payments

# Amounts
total_amount = Currency  # Total amount of reference
outstanding_amount = Currency  # Outstanding of reference
allocated_amount = Currency  # Amount being allocated
exchange_rate = Float
exchange_gain_loss = Currency

# Advance Tracking
advance_voucher_type = "Payment Entry"
advance_voucher_no = Link(Payment Entry)  # Original advance PE
reconcile_effect_on = Date  # When reconciliation takes effect

# Invoice Details
account = Link(Account)  # Party account from invoice
due_date = Date
```

---

### Company Fields (Related to Advance)

```python
# Advance Settings
book_advance_payments_in_separate_party_account = Check

# Advance Accounts
default_advance_received_account = Link(Account)  # For customer advances
default_advance_paid_account = Link(Account)  # For supplier advances

# Other Related
default_currency = Link(Currency)
exchange_gain_loss_account = Link(Account)
cost_center = Link(Cost Center)
```

---

## Use Cases & Examples

### Use Case 1: Simple Advance Receipt (Separate Account Mode)

**Scenario**: Customer bayar advance 10,000,000 sebelum invoice

**Step 1: Setup Company**
```python
Company.book_advance_payments_in_separate_party_account = 1
Company.default_advance_received_account = "Customer Advances - XYZ"
```

**Step 2: Create Payment Entry**
```python
pe = frappe.new_doc("Payment Entry")
pe.payment_type = "Receive"
pe.party_type = "Customer"
pe.party = "CUST-001"
pe.posting_date = "2026-01-23"
pe.paid_to = "Bank Account - XYZ"
pe.paid_amount = 10000000
pe.received_amount = 10000000
# Don't add any references for unallocated advance
pe.save()
pe.submit()
```

**Result**:
- GL Entry created with Customer Advances account
- Payment Entry shows unallocated_amount = 10,000,000

**Step 3: Create Sales Invoice**
```python
si = frappe.new_doc("Sales Invoice")
si.customer = "CUST-001"
si.posting_date = "2026-01-25"
si.append("items", {
    "item_code": "ITEM-001",
    "qty": 100,
    "rate": 100000
})
si.save()
si.submit()
# Outstanding = 10,000,000
```

**Step 4: Allocate Advance to Invoice**
```python
pe2 = frappe.new_doc("Payment Entry")
pe2.payment_type = "Receive"
pe2.party_type = "Customer"
pe2.party = "CUST-001"
pe2.posting_date = "2026-01-25"
pe2.paid_to = "Bank Account - XYZ"
pe2.paid_amount = 0  # No new payment
pe2.received_amount = 0

# Add reference to invoice
pe2.append("references", {
    "reference_doctype": "Sales Invoice",
    "reference_name": si.name,
    "allocated_amount": 10000000,
    "outstanding_amount": 10000000
})

pe2.save()
pe2.submit()
```

**Result**:
- Advance cleared from Customer Advances
- Invoice outstanding = 0
- GL entries created for reconciliation

---

### Use Case 2: Advance with Sales Order Reference

**Scenario**: Customer bayar DP untuk Sales Order

**Step 1: Create Sales Order**
```python
so = frappe.new_doc("Sales Order")
so.customer = "CUST-001"
so.delivery_date = "2026-02-01"
so.append("items", {
    "item_code": "ITEM-001",
    "qty": 100,
    "rate": 100000
})
so.save()
so.submit()
```

**Step 2: Create Payment Entry for Advance**
```python
pe = frappe.new_doc("Payment Entry")
pe.payment_type = "Receive"
pe.party_type = "Customer"
pe.party = "CUST-001"
pe.paid_to = "Bank Account - XYZ"
pe.paid_amount = 5000000

# Reference to Sales Order = Advance
pe.append("references", {
    "reference_doctype": "Sales Order",
    "reference_name": so.name,
    "allocated_amount": 5000000
})

pe.save()
pe.submit()
```

**Characteristics**:
- System recognizes this as advance (Sales Order in `get_advance_payment_doctypes()`)
- Uses advance account if enabled
- Shows in "Get Advances" when creating invoice

**Step 3: Create Invoice from Sales Order**
```python
# Create Sales Invoice from SO
si = frappe.get_doc(frappe.get_mapped_doc("Sales Order", so.name, {
    "Sales Order": {
        "doctype": "Sales Invoice"
    }
}))
si.save()
```

**Step 4: Get Advances on Invoice**
- Click "Get Advances" button
- System shows PE with 5,000,000 allocated to SO
- Select and allocate to invoice

---

### Use Case 3: Multiple Advances with Payment Terms

**Scenario**: Multiple advances, invoice dengan payment terms

**Step 1: Multiple Advance Payments**
```python
# Advance 1
pe1 = create_payment_entry("CUST-001", 3000000)
pe1.submit()

# Advance 2  
pe2 = create_payment_entry("CUST-001", 2000000)
pe2.submit()

# Total advances = 5,000,000
```

**Step 2: Create Invoice with Payment Terms**
```python
si = frappe.new_doc("Sales Invoice")
si.customer = "CUST-001"
si.payment_terms_template = "50-50 Net 30"  # Template with terms
si.append("items", {
    "item_code": "ITEM-001",
    "qty": 100,
    "rate": 100000
})
si.save()
# System auto-creates payment_schedule table
si.submit()
```

**Step 3: Allocate Advances to Terms**
```python
pe = frappe.new_doc("Payment Entry")
pe.payment_type = "Receive"
pe.party = "CUST-001"

# Allocate to Term 1
pe.append("references", {
    "reference_doctype": "Sales Invoice",
    "reference_name": si.name,
    "payment_term": "Term 1",
    "allocated_amount": 3000000,
    "outstanding_amount": 5000000
})

# Allocate to Term 2
pe.append("references", {
    "reference_doctype": "Sales Invoice",
    "reference_name": si.name,
    "payment_term": "Term 2",
    "allocated_amount": 2000000,
    "outstanding_amount": 5000000
})

pe.save()
pe.submit()
```

**System Behavior**:
```python
# Updates Payment Schedule table
update_payment_schedule()
# - Term 1: paid_amount += 3,000,000
# - Term 2: paid_amount += 2,000,000
```

---

### Use Case 4: Supplier Advance Payment

**Scenario**: Bayar advance ke supplier untuk PO

**Step 1: Create Purchase Order**
```python
po = frappe.new_doc("Purchase Order")
po.supplier = "SUPP-001"
po.schedule_date = "2026-02-01"
po.append("items", {
    "item_code": "RM-001",
    "qty": 1000,
    "rate": 50000
})
po.save()
po.submit()
```

**Step 2: Pay Advance**
```python
pe = frappe.new_doc("Payment Entry")
pe.payment_type = "Pay"
pe.party_type = "Supplier"
pe.party = "SUPP-001"
pe.paid_from = "Bank Account - XYZ"
pe.paid_to = "Supplier Advances - XYZ"  # Auto-set if enabled
pe.paid_amount = 20000000
pe.received_amount = 20000000

# Reference to PO
pe.append("references", {
    "reference_doctype": "Purchase Order",
    "reference_name": po.name,
    "allocated_amount": 20000000
})

pe.save()
pe.submit()
```

**GL Entry**:
```
Dr: Supplier Advances - XYZ     20,000,000  (Asset)
  Cr: Bank Account                         20,000,000
```

**Step 3: Create Purchase Invoice**
```python
pi = frappe.get_doc(frappe.get_mapped_doc("Purchase Order", po.name, {
    "Purchase Order": {
        "doctype": "Purchase Invoice"
    }
}))
pi.save()
pi.submit()
```

**Step 4: Get Advances**
- Click "Get Advances" on PI
- Select advance PE
- Allocate advance to invoice

**Reconciliation GL**:
```
Dr: Accounts Payable - SUPP-001    20,000,000
  Cr: Supplier Advances - XYZ                 20,000,000
```

---

### Use Case 5: Cancellation & Reversal

**Scenario**: Cancel payment entry yang sudah allocate advance

**Original Entries**:
1. Advance PE: PE-00001 (10,000,000)
2. Invoice: SINV-00001 (10,000,000)
3. Allocation PE: PE-00002 (allocate advance)

**Cancel PE-00002** (Allocation):
```python
pe2 = frappe.get_doc("Payment Entry", "PE-00002")
pe2.cancel()

# System automatically:
# 1. Reverse GL entries
# 2. Call delink_advance_entry_references()
# 3. Restore advance as unallocated
# 4. Restore invoice outstanding
```

**Result**:
- PE-00001: unallocated_amount = 10,000,000 (restored)
- SINV-00001: outstanding_amount = 10,000,000 (restored)
- Customer Advances account balance restored

---

## Integration Points for IMOGI Finance

### 1. Budget Control Integration

```python
def before_submit(self):
    """In Payment Entry"""
    # Check budget before creating advance payment
    if self.payment_type == "Pay":
        check_budget_for_advance_payment(
            cost_center=self.cost_center,
            amount=self.paid_amount,
            posting_date=self.posting_date
        )
```

### 2. Multi-Branch Support

```python
# Separate advance accounts per branch
Customer Advances - Branch A - Company
Customer Advances - Branch B - Company
Supplier Advances - Branch A - Company
Supplier Advances - Branch B - Company
```

### 3. Approval Workflow

```python
# Add approval for advance payments above threshold
def validate(self):
    if self.paid_amount > threshold:
        if not self.workflow_state == "Approved":
            frappe.throw("Advance payment requires approval")
```

---

## Best Practices

### 1. Account Setup
✅ Always create separate advance accounts per currency
✅ Use proper account types (Receivable/Payable for advances)
✅ Set company defaults before processing advances

### 2. Payment Entry
✅ Use clear naming/numbering for payment entries
✅ Add remarks explaining the advance purpose
✅ Reference Sales/Purchase Order when possible
✅ Verify unallocated_amount before submitting

### 3. Reconciliation
✅ Reconcile advances promptly when invoice is created
✅ Use "Get Advances" button instead of manual entry
✅ Check reconcile_effect_on date for backdated entries
✅ Verify GL entries after reconciliation

### 4. Reporting
✅ Create reports for:
  - Unallocated advances by customer/supplier
  - Advance aging report
  - Advance vs invoice reconciliation report

---

## Common Issues & Solutions

### Issue 1: Advance account not auto-set

**Symptom**: Payment Entry uses normal party account instead of advance account

**Solution**:
1. Check Company.book_advance_payments_in_separate_party_account = 1
2. Verify Company.default_advance_received_account is set
3. Ensure Payment Entry is in Draft (auto-set only works in draft)

---

### Issue 2: Cannot find advances when allocating

**Symptom**: "Get Advances" shows no results

**Solution**:
1. Verify advance PE is submitted
2. Check party matches exactly
3. Ensure advance has unallocated_amount > 0
4. Verify company matches between advance and invoice

---

### Issue 3: Double advance allocation

**Symptom**: Same advance allocated to multiple invoices

**Solution**:
- System prevents this automatically
- unallocated_amount is updated on each allocation
- Validate allocated_amount <= outstanding_amount

---

### Issue 4: GL entries incorrect for advance

**Symptom**: Wrong accounts used in GL entries

**Solution**:
1. Check `book_advance_payments_in_separate_party_account` setting
2. Verify advance accounts are properly configured
3. Review `get_dr_and_account_for_advances()` logic
4. Check account types match expected (Receivable/Payable)

---

## Summary

**Key Takeaways**:

1. **Two Modes**: Normal vs Separate Advance Account
2. **Auto-Detection**: System auto-sets advance accounts based on company settings
3. **Reference Types**: SO/PO = advance, Invoice = payment, None = unallocated
4. **Reconciliation**: Automatic GL entries when allocating advance to invoice
5. **Tracking**: Full audit trail via advance_voucher_type/no fields

**For IMOGI Finance Implementation**:
- ✅ Use separate advance account mode for better tracking
- ✅ Integrate with budget control for advance approvals
- ✅ Support multi-branch advance accounts
- ✅ Add custom reports for advance monitoring
- ✅ Implement approval workflow for large advances

---

## References

**Source Code** (ERPNext v15):
- `erpnext/accounts/doctype/payment_entry/payment_entry.py`
- `erpnext/accounts/utils.py`
- `erpnext/accounts/party.py`

**Documentation**:
- ERPNext Accounting Documentation
- Payment Entry User Guide
- Advance Payments Best Practices

---

**Document Version**: 1.0
**Last Updated**: 2026-01-23
**ERPNext Version**: v15.x
**Author**: IMOGI Finance Development Team
