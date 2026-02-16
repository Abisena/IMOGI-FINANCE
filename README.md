### Imogi Finance

**Version**: v1.5.0 (Released Feb 10, 2026)  
**Status**: ✅ Production Ready

App for managing expenses at IMOGI with comprehensive expense request workflows, OCR-powered tax invoice processing, budget control, and payment automation.

> **📖 For detailed documentation, see [DOCUMENTATION_MASTER_INDEX.md](DOCUMENTATION_MASTER_INDEX.md) and [START_HERE.md](START_HERE.md)**

**⚠️ Requirements**:
- ERPNext v14+ (v15+ recommended for native Payment Ledger features)
- Frappe v14+
- Python 3.8+

### Key Features

#### Expense Request & Approvals

- **Dynamic approval routes**: routes are calculated from Expense Approval Settings per Cost Center + expense account + amount, stored on the document, and must be refreshed before approval (configuration changes are detected and block approval until refreshed). Submit is restricted to the creator, approvers must match the user/role on the route, and levels cannot be skipped.
- **Edit controls & post-submit states**: changing amount/cost center/expense account while Pending resets to Pending Review (level 1) with an audit comment; key fields cannot change in Approved/Linked/Closed. Pending edits are limited to the owner or approver, and all rejections/overrides are recorded in the timeline.
- **Protected reopen & close**: reopen is reserved for System Manager unless an override flag is set; it enforces audit when active links to Payment Entry/Purchase Invoice/Asset exist. Close validates the latest route or final snapshot; an emergency override flag is available with audit trail.
- **Status guardrails & audit trail**: off-workflow status changes are blocked, approval routes are snapshotted when Approved to validate Close, and automatic comments are posted for denied workflow actions, pending edits, or reopen overrides.

#### Budget Control & Internal Charge

- **Staged budget lock**: Budget Control Settings can lock budgets at Approved/Linked, reserving per Cost Center + Account (+Project/Branch) and releasing automatically on Reject/Reopen. Consumption occurs on Purchase Invoice submit and is reversed on cancel.
- **Overrun handling & special role**: the `allow_budget_overrun_role` can permit overruns when reservation fails. Lock status (`Locked/Overrun Allowed/Consumed/Released`) is synchronized to the Expense Request.
- **Integrated internal charge**: the "Allocated via Internal Charge" mode requires an Approved Internal Charge Request before approval/PI; the `create_internal_charge_from_expense_request` helper auto-creates a draft with a starter line. "Auto JE on PI Submit" posts a reclass Journal Entry across Cost Centers according to allocation.

#### Accounting & Downstream Documents

- **Purchase Invoice creation from Expense Request**: a whitelisted helper ensures the request is Approved, type (Expense/Asset) matches, no duplicate links exist, and copies items (including VAT/WHT) with pending/submitted markers to prevent duplicate invoices.
- **Asset & Payment Entry linking**: hooks on Asset, Purchase Invoice, and Payment Entry maintain request status, prevent duplicate links, and verify downstream documents are submitted before payment. Requests are automatically Closed after Payment Entry succeeds.
- **Multi-branch compliance**: branch is derived from Cost Center/Finance Control Settings when creating PI from Expense Request; PI/PE/Asset links validate branch alignment when enforcement is enabled.

#### Customer Receipt & Payment Validation

- **Customer Receipt document**: chooses default print layout from Finance Control Settings, validates Sales Invoice/Sales Order references by customer & company, locks items after Issued, and computes Issued/Partially Paid/Paid status based on incoming payments.
- **Payment safeguards**: Payment Entry hook enforces "Mandatory Strict" mode (must link to a Customer Receipt when open receipts exist), blocks over-allocation or unrelated references except in mixed payment mode, and automatically updates/removes payment notes on Receipt during submit/cancel.
- **Collection automation**: the `make_payment_entry` button on Receipt creates Payment Entry with automatic allocation per outstanding reference.
- **Stamp policy & Jinja utilities**: Receipts apply digital/physical stamp policy per configuration (mandatory/threshold/fallback) and expose Jinja filters `terbilang_id` and `build_verification_url` for print templates.

#### Reconciliation & Bank Imports

- **BCA Bank Statement Import**: upload BCA CSV, the system hashes to prevent re-uploads, validates headers/numbers (detecting merged columns/"sep=" preamble), computes balances, and skips balance/pending rows. **Parse CSV BCA** prepares rows then **Convert to Bank Transaction** creates Unreconciled Bank Transactions with duplicate prevention and success/failure reporting. **Open Bank Reconciliation Tool** opens with the same date range & bank account.
- **Bank Transaction controls**: Unreconciled transactions cannot be cancelled (backend guard + hidden Cancel button) to preserve reconciliation history.

#### Cash/Bank Daily Reporting & Dashboard

- **Branch-aware cash/bank rollup**: `build_daily_report` partitions Bank Transactions per branch (with optional allowed branch filter), computes opening balances from earlier transactions, and aggregates inflow/outflow/closing for each branch plus a consolidated "All Branches" view.
- **Reporting snapshots & signers**: daily snapshots include signer blocks (`prepared_by/approved_by/acknowledged_by`) resolved from Finance Control Settings and can be cached via `run_daily_reporting`; dashboard payloads combine daily metrics with optional monthly reconciliation overlays.
- **Extensible inputs/exports**: helpers parse CSV bank statements, serialize combined daily + reconciliation data for export, and expose planning APIs for daily/monthly schedules without forcing a background worker.

#### Transfer Application & Payment Automation

- **Automatic Payment Entry creation**: helper button creates Payment Entry from Transfer Application with paid_from/paid_to defaults from settings or company accounts; can auto-submit and copy document references.
- **Bank Transaction matching**: on Bank Transaction submit/update, the system searches Transfer Application candidates by amount (with tolerance), account number/hint/payee name, and marks confidence Strong/Medium/Weak for review. Strong matches can auto-create Payment Entry and mark the TA as Paid.
- **Link protection**: Payment Entry hooks ensure a TA is not linked to multiple payments, update status/paid_amount/paid_date on submit, and clear links on cancel.

#### Advance Payments (Native First Strategy)

> **⚠️ IMPORTANT**: IMOGI Finance uses **ERPNext native Payment Ledger** for advance payment tracking. Custom APE module is deprecated.  
> **📖 Documentation**: [Native Payment Ledger User Guide](docs/NATIVE_PAYMENT_LEDGER_USER_GUIDE.md) | [Installation Guide](docs/NATIVE_PAYMENT_LEDGER_INSTALLATION.md)

- **Native Payment Ledger**: ERPNext v15+ automatically tracks all advances via Payment Ledger Entry (zero custom code needed for Supplier/Customer advances).
- **Enhanced Dashboard**: Custom report provides status visualization (Fully/Partially/Unallocated), aging analysis (0-30, 30-60, 60-90, 90+ days), and summary cards.
- **Employee Advance Extension**: IMOGI Finance adds "Get Employee Advances" button to Expense Claim with auto-allocation on submit (150 lines enhancement).

**Benefits**: Native Payment Ledger provides 77% less code, 95% less development time, 90% less maintenance vs custom APE. Zero upgrade conflicts.

#### Tax, OCR, & CoreTax Export (v1.5.0 Enhanced)

**OCR Improvements (v1.5.0)**:
- **Pre-compiled regex patterns**: 30-40% performance improvement for field extraction
- **Field swap auto-detection**: Automatically detects and flags swapped DPP/PPN fields with business logic correction
- **Zero-rated transaction support**: Handles 0% tax rate for exports and exempt goods
- **Confidence scoring**: Returns 0-0.95 confidence per extraction with multiple capping strategies
- **Structured error tracking**: Queryable `ParsingError` and `ParsingErrorCollector` classes for debugging

**Tax Invoice Features**:
- **Tax Invoice OCR**: OCR configuration (provider/size limit/threshold) for Purchase Invoice, Expense Request, and Sales Invoice; parses tax invoice text (NPWP, number/date, DPP/VAT) with NPWP normalization and duplicate flag.
- **Tax Invoice Upload**: Verified uploads required whenever manual Faktur Pajak fields are filled on Purchase/Expense/Branch Expense Requests. Validation enforces unique 16-digit numbers, valid NPWP, and stored PDF; Sales Invoice sync copies verified upload to out_fp* fields with NPWP safeguards and status tracking.
- **Tax profile controls**: Each company's Tax Profile requires PPN input/output, PB1 payable, and PPh payable accounts for tax registers, closings, and payment posting.
- **Tax period closure**: Tax Period Closing blocks changes to tax/tax-mapping fields on ER/PI/SI when period is Closed, except for System Manager/Tax Reviewer roles.
- **Reporting & exports**: Utilities compute snapshots for input/output VAT registers, withholding tax, and PB1; CoreTax mappings required for DPP, PPN, NPWP, faktur date; Payment Entry/Journal Entry creation for Tax Payment Batch and VAT netting (debit output/credit input/payable).

#### Deferred Expense Amortization (New in v1.5.0)

- **Amortization processor module**: Python functions for generating monthly amortization schedule from prepaid expense Purchase Invoices
- **Monthly journal entry generation**: Automatically creates GL entries for prepaid expense amortization based on posting date
- **Status tracking**: Tracks amortization creation status to prevent duplicate processing
- **Flexible start date**: Amortization can start from invoice date or custom month

### Feature usage guide

Use this checklist to read through each feature area and verify behavior quickly in a bench site.

#### Expense Request & Approvals

1. Configure Expense Approval Settings per Cost Center with routes for each expense account/threshold.
2. Create an Expense Request, then click **Refresh Route** before approving to capture the current configuration snapshot.
3. Walk approvals level by level; approvers must match the user/role in the route, and submits are restricted to the owner.
4. Edit Pending requests only as the owner/approver; changing amount/account/cost center resets the status to **Pending Review** with an audit log entry.
5. Reopen only as System Manager (or with the override flag) and ensure linked PI/PE/Asset documents are in a safe state; closing validates the latest approval snapshot.

#### Budget Control & Internal Charge

1. Set Budget Control Settings to lock at **Approved** or **Linked** and decide whether branch/project affects reservations.
2. Submit an Expense Request and observe the reservation status (`Locked/Overrun Allowed/Consumed/Released`) as PI/PE events occur.
3. Assign `allow_budget_overrun_role` to testers who should be able to push a request through when reservations fail.
4. Enable **Allocated via Internal Charge** to require an Approved Internal Charge Request; use `create_internal_charge_from_expense_request` to auto-create a draft.
5. When using **Auto JE on PI Submit**, submit a PI and confirm the Journal Entry reclassifies amounts across Cost Centers.

#### Accounting & Downstream Documents

1. From an Approved Expense Request, run the helper to **Create Purchase Invoice**; verify type alignment (Expense vs Asset) and duplicate link prevention.
2. Link Assets and Payment Entries to a request and ensure status guards block duplicate or inconsistent links; closing should happen automatically after a successful Payment Entry.
3. With multi-branch enforcement enabled, confirm branch derivation from Cost Center/Finance Control Settings and that PI/PE/Asset links respect branch rules.

#### Customer Receipt & Payment Validation

1. Configure Finance Control Settings to pick the default Receipt print layout and stamp policy (digital/physical, mandatory/threshold/fallback).
2. Create a Customer Receipt referencing Sales Invoice/Sales Order; submission should lock items once Issued and compute the payment status.
3. Use the **make_payment_entry** button to generate Payment Entry with automatic allocation to outstanding references.
4. Submit/cancel Payment Entries to see automatic receipt updates and the guardrail that enforces Mandatory Strict mode when open receipts exist.

#### Reconciliation & Bank Imports

1. Import a BCA CSV using **Parse CSV BCA** and **Convert to Bank Transaction**; the system should skip balance/pending rows and prevent re-uploads via hashing.
2. Review the success/failure report, then click **Open Bank Reconciliation Tool** with the same date range and bank account.
3. Attempt to cancel an Unreconciled Bank Transaction to verify the backend guard and hidden Cancel button protection.

#### Transfer Application & Payment Automation

1. From a Transfer Application, use the helper button to create Payment Entry; confirm paid_from/paid_to defaults from settings/company accounts and optional auto-submit.
2. On Bank Transaction submit/update, review the candidate matches (Strong/Medium/Weak) by amount tolerance, account number/hint, and payee name.
3. Enable the automation to auto-create Payment Entry for Strong matches and ensure a TA cannot be linked to multiple payments.

#### Advance Payments

> **📖 See [Native Payment Ledger User Guide](docs/NATIVE_PAYMENT_LEDGER_USER_GUIDE.md) for complete workflows**

1. **Native Workflow (Supplier/Customer)**: Create Payment Entry → system auto-creates Payment Ledger Entry → use "Get Advances" button on invoice → allocate advance.
2. **Enhanced Dashboard**: Go to Accounting → Reports → Advance Payment Dashboard for status visualization with 🔴 Unallocated / 🟡 Partially Allocated / ✅ Fully Allocated indicators.
3. **Employee Advances (IMOGI Extension)**: Create Payment Entry (party_type=Employee) → Expense Claim → click "Get Employee Advances" → select advances → submit (auto-allocates).
4. **Verify Installation**: Run `bench --site [site] execute imogi_finance.test_native_payment_ledger.test_payment_ledger` to check Payment Ledger is working.

#### Tax, OCR, & CoreTax Export

1. Fill **Tax Profile** with mandatory accounts (PPN input/output, PB1 payable, PPh payable) and configure Tax Invoice OCR provider, size limit, and threshold.
2. Test OCR on PI/ER/SI uploads to capture NPWP, tax number/date, and DPP/VAT; verify field swap detection catches swapped DPP/PPN values.
3. Close a Tax Period and attempt to edit tax/tax-mapping fields on ER/PI/SI to ensure only System Manager/Tax Reviewer can bypass the block.
4. Generate input/output VAT registers, withholding tax, and PB1 exports; verify CoreTax mappings (DPP, PPN, NPWP, faktur date) are required before exporting CSV/XLSX.
5. Use provided utilities to create Payment Entry/Journal Entry for Tax Payment Batch and VAT netting (debit output/credit input/payable balances).

#### Deferred Expense Amortization

1. Create a Purchase Invoice with "Is Prepaid Expense" flag and submit it.
2. Run the amortization processor: `bench --site [site] execute imogi_finance.expense_request.amortization_processor.create_all_missing_amortization`
3. Verify that monthly Journal Entries are automatically created for the amortization period.
4. Check the Purchase Invoice to confirm amortization status is updated to "Amortization Created".

### Expense Request Workflow Controls & Risks

See [Expense Request Workflow Guardrails](WORKFLOW_GUARDRAILS.md) to understand site flag impacts, route rebuild behavior, and audit recommendations for reopen/close actions.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app imogi_finance
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/imogi_finance
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### Bench console checks

Use the following bench console snippet to verify the validations (e.g., status not yet Approved or already linked to other documents):

```python
request = frappe.get_doc("Expense Request", "<NAMA_REQUEST>")
# Should throw an error if status is not Approved or docstatus is not 1
frappe.call("imogi_finance.accounting.create_purchase_invoice_from_request", expense_request_name=request.name)

# Mark the request as linked to trigger duplicate error
request.db_set("linked_purchase_invoice", "PI-TEST")
frappe.call("imogi_finance.accounting.create_purchase_invoice_from_request", expense_request_name=request.name)
# For Asset requests, use Purchase Invoice (manual JE flow removed)
request.db_set({"linked_purchase_invoice": None, "request_type": "Asset"})
frappe.call("imogi_finance.accounting.create_purchase_invoice_from_request", expense_request_name=request.name)
```

### Credits

- PT. Inovasi Terbaik Bangsa © 2026
- Contributors: dannyaudian, abisena
- Contact: m.abisena.putrawan@cao-group.co.id

### License

MIT
