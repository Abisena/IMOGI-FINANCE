# Perbandingan Arsitektur: ERPNext v15 vs IMOGI Finance

## Diagram Alur (Flow Comparison)

### 1. ERPNext v15 Standard - Advance Payment Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    ERPNEXT V15 STANDARD                      │
└─────────────────────────────────────────────────────────────┘

Step 1: Create Advance Payment Entry
┌──────────────────┐
│  Payment Entry   │
│  Type: Pay       │
│  Party: Supplier │
│  Amount: 10,000  │
│  References: []  │ ◄─── Empty = Advance
└────────┬─────────┘
         │
         │ on_validate()
         ├──► Check: book_advance_payments_in_separate_party_account?
         │    ├─ Yes ──► Set paid_to = "Supplier Advances - XYZ"
         │    └─ No  ──► Set paid_to = "Accounts Payable - Supplier"
         │
         │ on_submit()
         └──► Create GL Entry:
              ┌────────────────────────────────────┐
              │ Dr: Supplier Advances - XYZ  10,000│ (if separate mode)
              │   Cr: Bank Account              10,000│
              └────────────────────────────────────┘
              OR
              ┌────────────────────────────────────┐
              │ Dr: Accounts Payable     10,000│ (normal mode)
              │   Cr: Bank Account           10,000│
              └────────────────────────────────────┘

Step 2: Create Invoice
┌──────────────────────┐
│  Purchase Invoice    │
│  Supplier: Same      │
│  Amount: 8,000       │
│  Outstanding: 8,000  │
└──────────────────────┘

Step 3: Allocate Advance to Invoice
┌──────────────────┐
│ Payment Entry    │
│ (or Invoice UI)  │
└────────┬─────────┘
         │
         │ Click "Get Advances"
         ├──► Query: get_outstanding_reference_documents()
         │    Returns: PE with unallocated_amount > 0
         │
         │ User selects advance, submits
         │
         │ on_submit()
         ├──► Update PE.references[]
         │    └─ reference_type: "Purchase Invoice"
         │       reference_name: "PI-00001"
         │       allocated_amount: 8,000
         │
         ├──► Update Invoice.advances[]
         │    └─ reference_type: "Payment Entry"
         │       reference_name: "PE-00001"
         │       allocated_amount: 8,000
         │
         └──► make_advance_gl_entries()
              ┌─────────────────────────────────────────┐
              │ Dr: Accounts Payable         8,000  │ (clear liability)
              │   Cr: Supplier Advances - XYZ    8,000  │ (if separate mode)
              └─────────────────────────────────────────┘

Result:
- Payment Entry: unallocated_amount = 2,000
- Invoice: outstanding_amount = 0
- Supplier Advances: Balance = 2,000
```

---

### 2. IMOGI Finance - Advance Payment Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    IMOGI FINANCE SYSTEM                      │
└─────────────────────────────────────────────────────────────┘

Step 1: Create Advance Payment Entry
┌──────────────────┐
│  Payment Entry   │
│  Type: Pay       │
│  Party: Supplier │
│  Amount: 10,000  │
│  References: []  │ ◄─── Empty = Advance
└────────┬─────────┘
         │
         │ on_validate() [Hook]
         ├──► workflow.on_payment_entry_validate()
         │    ├─ Check: is_advance_payment()? YES
         │    ├─ Check: party_type in ALLOWED_PARTIES? YES
         │    └─ Check: amount > 0? YES
         │
         │ on_submit() [Hook]
         └──► workflow.on_payment_entry_submit()
              │
              ├──► upsert_advance_payment()
              │    └─ Create Advance Payment Entry (APE)
              │       ┌──────────────────────────────┐
              │       │ Advance Payment Entry (APE)  │
              │       │ ─────────────────────────── │
              │       │ payment_entry: PE-00001     │
              │       │ party_type: Supplier        │
              │       │ party: SUPP-001            │
              │       │ advance_amount: 10,000     │
              │       │ allocated_amount: 0        │
              │       │ unallocated_amount: 10,000 │
              │       │ status: Draft              │
              │       │ references: []             │ ◄─── Tracking table
              │       └──────────────────────────────┘
              │
              └──► APE.submit() ──► status = "Draft" (unallocated)

Step 2: Create Invoice
┌──────────────────────┐
│  Purchase Invoice    │
│  Supplier: Same      │
│  Amount: 8,000       │
│  Outstanding: 8,000  │
└──────────────────────┘

Step 3: Allocate Advance to Invoice
┌──────────────────┐
│ Invoice Form     │
└────────┬─────────┘
         │
         │ Click "Get Advances" [Custom Button]
         ├──► api.get_available_advances()
         │    └─ Query APE: docstatus=1, unallocated_amount > 0
         │       Returns: APE-00001 (10,000 available)
         │
         │ Custom Dialog shows advances
         │ User selects: APE-00001, Amount: 8,000
         │ Clicks "Allocate"
         │
         │ api.allocate_advances()
         ├──► Validate allocation
         │    ├─ Currency match? ✓
         │    ├─ Amount <= unallocated? ✓
         │    └─ Invoice submitted? ✓
         │
         ├──► APE.allocate_reference()
         │    ├─ Add to APE.references[]
         │    │  └─ invoice_doctype: "Purchase Invoice"
         │    │     invoice_name: "PI-00001"
         │    │     allocated_amount: 8,000
         │    │     allocation_date: "2026-01-23"
         │    │     allocated_by: "user@example.com"
         │    │
         │    ├─ Update APE amounts
         │    │  ├─ allocated_amount: 8,000
         │    │  └─ unallocated_amount: 2,000
         │    │
         │    └─ Update APE status: "Partially Allocated"
         │
         └──► native_bridge.sync_allocation_to_native_advances()
              │
              ├──► Get Invoice: PI-00001
              │
              ├──► Add to Invoice.advances[]
              │    └─ reference_type: "Payment Entry"
              │       reference_name: "PE-00001"
              │       allocated_amount: 8,000
              │       remarks: "Auto-allocated from APE-00001"
              │
              └──► Invoice.save()
                   └─ ERPNext native handles GL entries
                      (No custom GL logic needed!)

Result:
- Payment Entry: unchanged (original advance PE)
- APE: status = "Partially Allocated", unallocated = 2,000
- Invoice.advances[]: Has PE-00001 allocation
- Invoice: outstanding_amount = 0 (ERPNext native calculation)

┌────────────────────────────────────────────────────────────┐
│                   DASHBOARD VIEW (APE)                      │
│ ─────────────────────────────────────────────────────────  │
│ Advance Amount:      10,000                                │
│ Allocated Amount:     8,000                                │
│ Unallocated Amount:   2,000                                │
│                                                            │
│ Allocations:                                               │
│ ┌────────────────────────────────────────────────┐        │
│ │ Purchase Invoice: PI-00001      8,000          │        │
│ │ Allocated: 2026-01-23 by user@example.com      │        │
│ └────────────────────────────────────────────────┘        │
│                                                            │
│ [Reconcile Payments] [View Invoice]                       │
└────────────────────────────────────────────────────────────┘
```

---

## Perbandingan Komponen Arsitektur

### ERPNext v15 Components

```
┌────────────────────────────────────────────────────────┐
│                 ERPNEXT V15 ARCHITECTURE                │
└────────────────────────────────────────────────────────┘

Core Components:
├── Payment Entry (DocType)
│   ├── Fields:
│   │   ├── payment_type
│   │   ├── party_type
│   │   ├── party
│   │   ├── paid_from / paid_to
│   │   ├── paid_amount / received_amount
│   │   ├── unallocated_amount
│   │   └── book_advance_payments_in_separate_party_account (computed)
│   │
│   ├── Methods:
│   │   ├── set_liability_account()       ◄─── Auto-set advance account
│   │   ├── make_advance_gl_entries()     ◄─── Create GL for advance clearing
│   │   ├── add_advance_gl_for_reference()
│   │   └── delink_advance_entry_references()
│   │
│   └── Child Tables:
│       └── references[] (Payment Entry Reference)
│           ├── reference_doctype
│           ├── reference_name
│           ├── allocated_amount
│           └── outstanding_amount
│
├── Company (DocType)
│   └── Settings:
│       ├── book_advance_payments_in_separate_party_account (Check)
│       ├── default_advance_received_account (Link to Account)
│       └── default_advance_paid_account (Link to Account)
│
├── Invoice (Sales/Purchase Invoice)
│   ├── Methods:
│   │   ├── get_advance_entries()        ◄─── Fetch available advances
│   │   └── delink_advance_entries()     ◄─── Clear on cancel
│   │
│   └── Child Tables:
│       └── advances[] (Sales/Purchase Invoice Advance)
│           ├── reference_type: "Payment Entry"
│           ├── reference_name
│           ├── advance_amount
│           ├── allocated_amount
│           └── ref_exchange_rate
│
└── Utils (erpnext/accounts/utils.py)
    ├── get_outstanding_reference_documents() ◄─── Query advances
    ├── get_advance_payment_doctypes()        ◄─── SO, PO
    ├── get_party_account()                   ◄─── Get accounts
    └── get_reconciliation_effect_date()

Limitations:
❌ No separate tracking DocType
❌ No status field for advances
❌ No allocation history
❌ Limited UI/UX
❌ Tight coupling with core code
```

---

### IMOGI Finance Components

```
┌────────────────────────────────────────────────────────┐
│              IMOGI FINANCE ARCHITECTURE                 │
└────────────────────────────────────────────────────────┘

Core Components:

1. TRACKING LAYER (Custom)
   ├── Advance Payment Entry (DocType)  ◄─── MAIN INNOVATION
   │   ├── Fields:
   │   │   ├── payment_entry (Link to PE)
   │   │   ├── posting_date
   │   │   ├── company
   │   │   ├── party_type
   │   │   ├── party
   │   │   ├── party_name (computed)
   │   │   ├── currency
   │   │   ├── exchange_rate
   │   │   ├── advance_amount
   │   │   ├── allocated_amount (computed)
   │   │   ├── unallocated_amount (computed)
   │   │   └── status (Draft/Allocated/Partially Allocated/Cancelled)
   │   │
   │   ├── Methods:
   │   │   ├── validate()
   │   │   ├── on_submit()
   │   │   ├── on_cancel()
   │   │   ├── allocate_reference()         ◄─── Add allocation
   │   │   ├── clear_reference_allocations()◄─── Remove allocation
   │   │   ├── _set_defaults()
   │   │   ├── _set_amounts()              ◄─── Compute totals
   │   │   ├── _validate_allocations()     ◄─── Strict validation
   │   │   └── _update_status()            ◄─── Set status
   │   │
   │   └── Child Tables:
   │       └── references[] (Advance Payment Reference)
   │           ├── invoice_doctype
   │           ├── invoice_name
   │           ├── allocated_amount
   │           ├── remaining_amount
   │           ├── reference_currency
   │           ├── reference_exchange_rate
   │           ├── allocation_date        ◄─── Audit
   │           ├── allocated_by           ◄─── Audit
   │           ├── reference_posting_date ◄─── Track
   │           └── reference_status       ◄─── Track

2. WORKFLOW MODULE (workflow.py)
   ├── Event Handlers:
   │   ├── on_payment_entry_validate()    ◄─── Hook: PE validate
   │   ├── on_payment_entry_submit()      ◄─── Hook: PE submit
   │   ├── on_payment_entry_cancel()      ◄─── Hook: PE cancel
   │   └── on_payment_entry_update_after_submit()
   │
   ├── Business Logic:
   │   ├── is_advance_payment()           ◄─── Detect advance
   │   ├── upsert_advance_payment()       ◄─── Create/update APE
   │   ├── get_payment_amount()           ◄─── Extract amount
   │   └── get_currency_and_rate()        ◄─── Extract currency
   │
   └── Constants:
       └── ALLOWED_PARTIES = {"Supplier", "Employee"}

3. API MODULE (api.py)
   ├── Whitelisted Methods:
   │   ├── get_available_advances()       ◄─── Fetch unallocated
   │   ├── get_allocations_for_reference()◄─── Get invoice allocations
   │   ├── allocate_advances()            ◄─── Main allocation API
   │   └── release_allocations()          ◄─── Clear on cancel
   │
   ├── Validation Functions:
   │   ├── validate_party_inputs()
   │   ├── validate_advance_for_party()
   │   ├── validate_allocation_currency()
   │   └── validate_allocation_amount()
   │
   └── Constants:
       └── SUPPORTED_REFERENCE_DOCTYPES = {
           "Purchase Invoice", "Sales Invoice",
           "Expense Claim", "Payroll Entry", 
           "Purchase Order", "Journal Entry",
           "Expense Request", "Branch Expense Request"
       }

4. NATIVE BRIDGE MODULE (native_bridge.py)  ◄─── KEY INNOVATION
   ├── Purpose: Sync APE ↔ ERPNext Native
   │
   ├── Functions:
   │   ├── sync_allocation_to_native_advances()
   │   │   └─► Add/Update Invoice.advances[]
   │   │
   │   ├── remove_allocation_from_native_advances()
   │   │   └─► Remove from Invoice.advances[]
   │   │
   │   └── sync_all_allocations_for_ape()
   │       └─► Bulk sync all allocations
   │
   └── Principles:
       ├─ Native First: ERPNext handles accounting
       ├─ Non-Invasive: Zero core modifications
       └─ Scalable: APE removable without breaking

5. UI/UX LAYER (JavaScript)
   ├── advance_payment_entry.js
   │   ├── Custom buttons: Reconcile Payments
   │   ├── Dashboard: show_allocation_summary()
   │   └── Auto-recalculate on changes
   │
   └── advance_payment_allocation.js
       ├── "Get Advances" button on invoices
       ├── Custom allocation dialog
       ├── Visual warnings
       └── Real-time validation

6. HOOKS INTEGRATION (hooks.py)
   ├── Payment Entry Events:
   │   ├── validate ──► workflow.on_payment_entry_validate
   │   ├── on_submit ──► workflow.on_payment_entry_submit
   │   ├── on_cancel ──► workflow.on_payment_entry_cancel
   │   └── on_update_after_submit ──► workflow.on_payment_entry_update_after_submit
   │
   ├── Invoice Events (PI, SI, EC, PE):
   │   ├── on_submit ──► api.on_reference_update
   │   ├── on_update_after_submit ──► api.on_reference_update
   │   ├── before_cancel ──► api.on_reference_before_cancel
   │   └── on_cancel ──► api.on_reference_cancel
   │
   └── DocType JS:
       ├── Purchase Invoice ──► advance_payment_allocation.js
       ├── Expense Claim ──► advance_payment_allocation.js
       └── Payroll Entry ──► advance_payment_allocation.js

Advantages:
✅ Modular: Each component independent
✅ Non-Invasive: Hooks only, no core changes
✅ Scalable: APE can be removed safely
✅ Extensible: Easy to add features
✅ Auditable: Full history tracking
✅ Flexible: Support custom doctypes
```

---

## Data Flow Comparison

### ERPNext v15 Data Flow

```
┌─────────┐     ┌──────────────┐     ┌─────────┐
│ Payment │────►│   GL Entry   │◄────│ Invoice │
│  Entry  │     │  (Advance)   │     │.advances│
└─────────┘     └──────────────┘     └─────────┘
     │                                      ▲
     │                                      │
     └──────── references[] ────────────────┘

Flow:
1. PE created → GL Entry (advance account)
2. Invoice created → outstanding amount
3. PE.references[] updated → allocate to invoice
4. Invoice.advances[] auto-populated
5. GL Entry created → clear advance account
```

---

### IMOGI Finance Data Flow

```
┌─────────┐     ┌──────────┐     ┌─────────────┐     ┌─────────┐
│ Payment │────►│   APE    │────►│Native Bridge│────►│ Invoice │
│  Entry  │     │(Tracking)│     │   (Sync)    │     │.advances│
└─────────┘     └────┬─────┘     └─────────────┘     └─────────┘
                     │                                      │
                     │                                      │
                     └─── Status & History ◄───────────────┘
                              ▲
                              │
                         ERPNext handles
                         GL Entry natively

Flow:
1. PE created → Hook triggers → APE created
2. APE tracks: status, party, amounts
3. User allocates → APE.allocate_reference()
4. Native Bridge → Sync to Invoice.advances[]
5. ERPNext native → Create GL Entry (no custom code)
6. APE updates → Status, history, dashboard

Benefits:
✓ Separation of Concerns: Tracking ≠ Accounting
✓ Single Source of Truth: ERPNext handles GL
✓ Enhanced Visibility: APE shows full picture
✓ Safe Operations: Can remove APE anytime
```

---

## Key Architectural Differences

| Aspect | ERPNext v15 | IMOGI Finance | Winner |
|--------|-------------|---------------|--------|
| **Separation of Concerns** | ❌ Mixed tracking + accounting in PE | ✅ APE (tracking) + ERPNext (accounting) | ⭐ IMOGI |
| **Code Location** | ❌ Core ERPNext (erpnext/accounts/) | ✅ Custom App (imogi_finance/) | ⭐ IMOGI |
| **Modification Type** | ❌ Core class methods | ✅ Hooks only | ⭐ IMOGI |
| **Upgrade Safety** | ⚠️ Risk of conflicts | ✅ Safe, isolated | ⭐ IMOGI |
| **Extensibility** | ⚠️ Fork core or monkey-patch | ✅ Extend APE or add modules | ⭐ IMOGI |
| **Removability** | ❌ Cannot remove | ✅ Remove APE, keep native | ⭐ IMOGI |
| **Testing** | ⚠️ Hard (core dependency) | ✅ Easy (isolated) | ⭐ IMOGI |
| **Documentation** | ⚠️ Scattered | ✅ Centralized | ⭐ IMOGI |

---

## Database Schema Comparison

### ERPNext v15 Schema

```sql
-- Payment Entry (tabPayment Entry)
┌────────────────────────────────────────┐
│ name                     VARCHAR(140)   │ PK
│ payment_type             VARCHAR(140)   │
│ party_type               VARCHAR(140)   │
│ party                    VARCHAR(140)   │
│ paid_from                VARCHAR(140)   │
│ paid_to                  VARCHAR(140)   │
│ paid_amount              DECIMAL(18,6)  │
│ received_amount          DECIMAL(18,6)  │
│ unallocated_amount       DECIMAL(18,6)  │ Computed
│ docstatus                INT            │
└────────────────────────────────────────┘
          │
          │ 1:N
          ▼
┌─────────────────────────────────────────────┐
│ Payment Entry Reference                     │
│ (tabPayment Entry Reference)                │
├─────────────────────────────────────────────┤
│ parent                   VARCHAR(140)       │ FK → PE
│ reference_doctype        VARCHAR(140)       │
│ reference_name           VARCHAR(140)       │
│ allocated_amount         DECIMAL(18,6)      │
│ outstanding_amount       DECIMAL(18,6)      │
│ advance_voucher_type     VARCHAR(140)       │ (for tracking)
│ advance_voucher_no       VARCHAR(140)       │
└─────────────────────────────────────────────┘

-- Invoice Advances (tabSales/Purchase Invoice Advance)
┌─────────────────────────────────────────────┐
│ parent                   VARCHAR(140)       │ FK → Invoice
│ reference_type           VARCHAR(140)       │ = "Payment Entry"
│ reference_name           VARCHAR(140)       │ FK → PE
│ advance_amount           DECIMAL(18,6)      │
│ allocated_amount         DECIMAL(18,6)      │
│ ref_exchange_rate        DECIMAL(18,6)      │
└─────────────────────────────────────────────┘

No dedicated advance tracking table!
```

---

### IMOGI Finance Schema

```sql
-- Payment Entry (tabPayment Entry) - UNCHANGED
-- (Same as ERPNext standard)

-- Advance Payment Entry (tabAdvance Payment Entry) ◄─── NEW!
┌────────────────────────────────────────┐
│ name                     VARCHAR(140)   │ PK
│ payment_entry            VARCHAR(140)   │ FK → PE (UNIQUE)
│ posting_date             DATE           │
│ company                  VARCHAR(140)   │
│ party_type               VARCHAR(140)   │
│ party                    VARCHAR(140)   │
│ party_name               VARCHAR(180)   │ Computed
│ currency                 VARCHAR(50)    │
│ exchange_rate            DECIMAL(18,6)  │
│ advance_amount           DECIMAL(18,6)  │
│ allocated_amount         DECIMAL(18,6)  │ Computed
│ unallocated_amount       DECIMAL(18,6)  │ Computed
│ base_advance_amount      DECIMAL(18,6)  │ Computed
│ base_allocated_amount    DECIMAL(18,6)  │ Computed
│ base_unallocated_amount  DECIMAL(18,6)  │ Computed
│ status                   VARCHAR(140)   │ Draft/Allocated/etc
│ docstatus                INT            │
└────────────────────────────────────────┘
          │
          │ 1:N
          ▼
┌─────────────────────────────────────────────┐
│ Advance Payment Reference                   │
│ (tabAdvance Payment Reference)              │
├─────────────────────────────────────────────┤
│ parent                   VARCHAR(140)       │ FK → APE
│ invoice_doctype          VARCHAR(140)       │
│ invoice_name             VARCHAR(140)       │
│ allocated_amount         DECIMAL(18,6)      │
│ remaining_amount         DECIMAL(18,6)      │
│ reference_currency       VARCHAR(50)        │
│ reference_exchange_rate  DECIMAL(18,6)      │
│ allocation_date          DATE               │ ◄─── Audit
│ allocated_by             VARCHAR(140)       │ ◄─── Audit
│ reference_posting_date   DATE               │ ◄─── Track
│ reference_status         VARCHAR(140)       │ ◄─── Track
└─────────────────────────────────────────────┘
          │
          │ Native Bridge
          ▼
┌─────────────────────────────────────────────┐
│ Invoice Advances (ERPNext Native)           │
│ (Same as ERPNext standard)                  │
│ - reference_type = "Payment Entry"          │
│ - reference_name = PE name                  │
│ - allocated_amount synced from APE          │
└─────────────────────────────────────────────┘

Key Advantages:
✓ Dedicated tracking table (APE)
✓ Rich status & history fields
✓ Full audit trail
✓ Independent from core schema
✓ Synced to native for accounting
```

---

## Summary: Why IMOGI Architecture is Superior

### 1. **Design Principles**

| Principle | ERPNext v15 | IMOGI Finance |
|-----------|-------------|---------------|
| Single Responsibility | ❌ PE does tracking + accounting | ✅ APE = tracking, ERPNext = accounting |
| Open/Closed | ❌ Need to modify core | ✅ Extend via hooks |
| Dependency Inversion | ❌ Tight coupling | ✅ Loose coupling via bridge |
| Interface Segregation | ❌ Monolithic | ✅ Modular interfaces |

### 2. **Operational Benefits**

- ✅ **Upgrade Safety**: No core modifications = easy upgrade
- ✅ **Testing**: Isolated components = easier unit tests
- ✅ **Debugging**: Clear boundaries = faster troubleshooting
- ✅ **Performance**: Dedicated indexes on APE = faster queries
- ✅ **Scalability**: Can add caching, queuing without touching core

### 3. **Business Value**

- ✅ **Better Visibility**: Dashboard shows advance status
- ✅ **Audit Trail**: Full history of who allocated what when
- ✅ **Compliance**: Track allocation for reporting
- ✅ **Flexibility**: Support custom doctypes easily
- ✅ **User Experience**: Enhanced UI/UX for operations

### 4. **Technical Excellence**

```python
# ERPNext v15: Monolithic
class PaymentEntry:
    def make_advance_gl_entries(self):
        # 100+ lines of GL logic
        # Tightly coupled with PE
        # Hard to test
        # Hard to extend
```

```python
# IMOGI Finance: Modular
class AdvancePaymentEntry:
    def allocate_reference(self):
        # Pure business logic
        # Clear responsibility
        # Easy to test
        # Easy to extend

# Separate concerns
def sync_allocation_to_native_advances():
    # Sync layer
    # Independent module
    # Can be swapped/upgraded
```

---

## Conclusion

**IMOGI Finance architecture represents a significant improvement** over ERPNext v15 standard approach. By separating tracking from accounting, using hooks instead of core modifications, and implementing a clean bridge pattern, IMOGI Finance achieves:

1. ⭐⭐⭐⭐⭐ **Better Maintainability**
2. ⭐⭐⭐⭐⭐ **Better Testability**
3. ⭐⭐⭐⭐⭐ **Better Extensibility**
4. ⭐⭐⭐⭐⭐ **Better User Experience**
5. ⭐⭐⭐⭐ **Better Accounting Integration**

The only gaps (separate advance account mode, customer support) are **feature completeness** issues, not architectural problems. Once these gaps are filled, IMOGI Finance will be the **definitive solution** for advance payment management in ERPNext.

---

**Document Version**: 1.0  
**Created**: 2026-01-23  
**Author**: GitHub Copilot for IMOGI Finance Team
