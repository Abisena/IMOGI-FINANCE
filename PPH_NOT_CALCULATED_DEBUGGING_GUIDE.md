# PPh Not Calculated in Purchase Invoice - Debugging Guide

## Problem Statement
**Symptom:** Total PPh shown in Expense Request (Rp 84.800,00) is NOT transferred to Purchase Invoice when creating PI from ER.

**Observed Behavior:**
- ✅ Expense Request shows: Total PPh Rp 84.800,00
- ❌ Purchase Invoice shows: No PPh row in taxes table
- ✅ PPN transfers correctly: Rp 466.400,00

---

## Root Cause Analysis

### Potential Issues:

#### 1. **Item Level "Apply WHT" Not Checked**
**Most Common Cause** (90% of cases)

**Check:**
1. Open Expense Request ER-2026-000099
2. Go to **Tab Items**
3. Click on item "Administrative Expenses - TPT"
4. Check if column **"Apply WHT"** is CHECKED ✅

**Fix:**
```
If Apply WHT is NOT checked:
1. Edit Expense Request (if still Draft)
2. Check "Apply WHT" checkbox on the item
3. Save and recalculate
4. Recreate Purchase Invoice
```

**Why This Matters:**
```python
# In accounting.py line 228
pph_items = [item for item in request_items if getattr(item, "is_pph_applicable", 0)]
apply_pph = items_with_pph > 0  # Only true if ANY item has Apply WHT checked
```

---

#### 2. **Header "Apply WHT" Not Checked**
**Check:**
1. Open Expense Request
2. Go to **Tab Tax**
3. Check if **"Apply WHT"** checkbox is CHECKED ✅
4. Check if **"PPh Type"** is filled (e.g., "Pasal 23 - Jasa")

**Fix:**
```
If header Apply WHT is NOT checked:
1. Tab Tax → Check "Apply WHT"
2. Select PPh Type (e.g., Pasal 23)
3. Save
4. Recreate Purchase Invoice
```

**Code Reference:**
```python
# In accounting.py line 250-257
if apply_pph:
    pph_type = getattr(request, "pph_type", None)
    if not pph_type:
        frappe.throw(
            _("Found {0} item(s) with 'Apply WHT' checked but PPh Type is NOT specified")
        )
```

---

#### 3. **PPh Already Exists in PI (Not Visible)**
**Sometimes PPh is calculated but hidden**

**Check Database:**
```sql
SELECT
    name,
    apply_tds,
    tax_withholding_category,
    withholding_tax_base_amount
FROM `tabPurchase Invoice`
WHERE name = 'ACC-PINV-2026-00024';

-- Check tax rows
SELECT
    parent,
    idx,
    charge_type,
    account_head,
    description,
    rate,
    tax_amount
FROM `tabPurchase Taxes and Charges`
WHERE parent = 'ACC-PINV-2026-00024'
ORDER BY idx;
```

**Expected Results:**
- `apply_tds` should be = 1
- `tax_withholding_category` should have value (e.g., "Pasal 23 - Jasa")
- Should have tax row with account like "PPh 23 Dibayar - TPT"

---

#### 4. **set_tax_withholding() Not Called/Failed**
**PPh calculation method failed silently**

**Check Error Log:**
```python
# In Frappe Console or Error Log
frappe.log_error(title="PPh Calculation Error")
```

**Check if method exists:**
```python
# In bench console
pi = frappe.get_doc("Purchase Invoice", "ACC-PINV-2026-00024")
print(hasattr(pi, "set_tax_withholding"))  # Should be True
print(callable(getattr(pi, "set_tax_withholding", None)))  # Should be True
```

**Manual Trigger:**
```python
# In bench console
pi = frappe.get_doc("Purchase Invoice", "ACC-PINV-2026-00024")
pi.apply_tds = 1
pi.tax_withholding_category = "Pasal 23 - Jasa"
pi.withholding_tax_base_amount = 4240000  # DPP amount
pi.set_tax_withholding()
pi.save()
```

---

#### 5. **Tax Withholding Category Not Configured**
**Master data issue**

**Check:**
```sql
SELECT
    name,
    tax_type,
    rate,
    is_active
FROM `tabTax Withholding Category`
WHERE name = 'Pasal 23 - Jasa';
```

**Expected:**
- Should exist in database
- `is_active` = 1
- `rate` = 2.0 (for 2% WHT)

**Check Accounts:**
```sql
SELECT
    name,
    parent,
    company,
    account
FROM `tabTax Withholding Account`
WHERE parent = 'Pasal 23 - Jasa';
```

**Expected:**
- Should have account for company "_Test Company PT"
- Account should be like "PPh 23 Dibayar - TPT"

---

#### 6. **Item-Level apply_tds Not Set**
**Critical for per-item WHT**

**Check Code Execution:**
```python
# In accounting.py line 471-481
# Set item-level apply_tds flag if PPh applies
if apply_pph and hasattr(pi_item_doc, "apply_tds"):
    if getattr(item, "is_pph_applicable", 0):
        pi_item_doc.apply_tds = 1  # ✓ Item should get WHT
    else:
        pi_item_doc.apply_tds = 0  # ✗ Item exempt from WHT
```

**Verify in Database:**
```sql
SELECT
    parent,
    idx,
    item_name,
    amount,
    apply_tds
FROM `tabPurchase Invoice Item`
WHERE parent = 'ACC-PINV-2026-00024';
```

**Expected:**
- Row 1 (Administrative Expenses): `apply_tds` = 1

---

## Step-by-Step Debugging Process

### Step 1: Check Expense Request Configuration
```bash
# Open ER-2026-000099 in browser
https://tigaperkasateknik.j.frappe.cloud/app/expense-request/ER-2026-000099
```

**Checklist:**
- [ ] Tab Items: Item "Administrative Expenses - TPT" has **"Apply WHT" ✅**
- [ ] Tab Tax: Header **"Apply WHT" ✅**
- [ ] Tab Tax: **"PPh Type"** = filled (e.g., "Pasal 23 - Jasa")
- [ ] Tab Items: **Summary shows "Total PPh: Rp 84.800,00"**

### Step 2: Check Purchase Invoice
```bash
# Open PI in browser
https://tigaperkasateknik.j.frappe.cloud/app/purchase-invoice/ACC-PINV-2026-00024
```

**Checklist:**
- [ ] Go to **Details** tab
- [ ] Scroll to bottom: Check **"Apply Tax Withholding Amount" ✅**
- [ ] Field **"Tax Withholding Category"** = filled
- [ ] Field **"Withholding Tax Base Amount"** = Rp 4.240.000,00

### Step 3: Check Taxes Table
```bash
# In Purchase Invoice → Tab "Terms"
# Section: "Purchase Taxes and Charges"
```

**Expected Rows:**
1. **PPN (VAT):**
   - Type: On Net Total
   - Account: VAT IN - TPT
   - Rate: 11%
   - Amount: Rp 466.400,00 ✅

2. **PPh (WHT):** ← **THIS SHOULD EXIST**
   - Type: On Net Total
   - Account: PPh 23 Dibayar - TPT (or similar)
   - Rate: 2%
   - Amount: **Rp 84.800,00** ← **MISSING IF BUG**

### Step 4: Manual Fix (If PPh Missing)
```python
# In Frappe Console (bench console)
pi = frappe.get_doc("Purchase Invoice", "ACC-PINV-2026-00024")

# Check current status
print(f"apply_tds: {pi.apply_tds}")
print(f"tax_withholding_category: {pi.tax_withholding_category}")
print(f"withholding_tax_base_amount: {pi.withholding_tax_base_amount}")

# If any is missing/wrong, fix it:
pi.apply_tds = 1
pi.tax_withholding_category = "Pasal 23 - Jasa"  # Adjust based on your setup
pi.withholding_tax_base_amount = 4240000

# Recalculate WHT
if hasattr(pi, "set_tax_withholding"):
    pi.set_tax_withholding()

# Save
pi.save(ignore_permissions=True)
pi.reload()

# Verify
print(f"\nTaxes and Charges Deducted: {pi.taxes_and_charges_deducted}")
for tax in pi.taxes:
    print(f"  {tax.idx}. {tax.description}: {tax.tax_amount}")
```

---

## Prevention (Future Cases)

### 1. **Client Script Validation**
Add validation to prevent PI creation without proper PPh config:

```javascript
// In expense_request.js
frappe.ui.form.on('Expense Request', {
    before_workflow_action: function(frm) {
        // Check if creating Purchase Invoice
        if (frm.selected_workflow_action === 'Create Purchase Invoice') {
            // Validate PPh setup
            let items_with_pph = frm.doc.items.filter(i => i.is_pph_applicable);

            if (items_with_pph.length > 0) {
                // Items have Apply WHT checked
                if (!frm.doc.is_pph_applicable) {
                    frappe.throw(__('Header "Apply WHT" must be checked when items have Apply WHT'));
                    return false;
                }

                if (!frm.doc.pph_type) {
                    frappe.throw(__('PPh Type is required when items have Apply WHT'));
                    return false;
                }
            }
        }
    }
});
```

### 2. **Server Validation Enhancement**
Add explicit validation in Python code:

```python
# In accounting.py, after line 257
if apply_pph:
    pph_type = getattr(request, "pph_type", None)
    if not pph_type:
        # Enhanced error message with debugging info
        frappe.throw(
            _(
                "<b>PPh Configuration Error</b><br><br>"
                "Found <b>{0}</b> item(s) with 'Apply WHT' checked:<br>"
                "{1}<br><br>"
                "But <b>PPh Type is NOT specified</b> in Tab Tax.<br><br>"
                "Action Required:<br>"
                "1. Go to Tab Tax<br>"
                "2. Check 'Apply WHT' checkbox<br>"
                "3. Select PPh Type (e.g., Pasal 23)<br>"
                "4. Save and retry creating Purchase Invoice"
            ).format(
                items_with_pph,
                "<br>".join([f"- {item.expense_account}" for item in pph_items[:5

]])
            ),
            title=_("PPh Type Required")
        )
```

### 3. **Post-Creation Verification**
Add automatic check after PI creation:

```python
# In accounting.py, after line 650 (after PI creation)
if apply_pph:
    # Verify PPh was actually applied
    pi.reload()

    if not pi.taxes_and_charges_deducted or pi.taxes_and_charges_deducted == 0:
        frappe.log_error(
            title=f"PPh Not Applied to PI {pi.name}",
            message=f"""
                Expense Request: {request.name}
                apply_pph: {apply_pph}
                tax_withholding_category: {pi.tax_withholding_category}
                apply_tds: {pi.apply_tds}
                withholding_tax_base_amount: {pi.withholding_tax_base_amount}
                taxes_and_charges_deducted: {pi.taxes_and_charges_deducted}

                Expected PPh Amount: {request.total_pph}
            """
        )

        frappe.msgprint(
            msg=_(
                "<b>Warning: PPh Not Calculated</b><br><br>"
                "Purchase Invoice created but PPh (Withholding Tax) was not applied.<br>"
                "Expected: Rp {0:,.2f}<br>"
                "Actual: Rp 0<br><br>"
                "Please check Purchase Invoice taxes manually."
            ).format(flt(request.total_pph)),
            title=_("PPh Calculation Warning"),
            indicator="orange"
        )
```

---

## Quick Fix Checklist

For immediate resolution of current issue:

1. **Open Expense Request ER-2026-000099**
   - [ ] Tab Items → Check "Apply WHT" on item
   - [ ] Tab Tax → Check "Apply WHT" header
   - [ ] Tab Tax → Select "PPh Type"
   - [ ] Save

2. **Delete Existing Purchase Invoice** (if not submitted)
   - [ ] Open ACC-PINV-2026-00024
   - [ ] Menu → Delete

3. **Recreate Purchase Invoice**
   - [ ] From ER-2026-000099
   - [ ] Click "Create Purchase Invoice"
   - [ ] Verify PPh appears in Taxes table

4. **If PI Already Submitted:**
   - [ ] Use manual fix Python script above
   - OR
   - [ ] Cancel PI
   - [ ] Recreate from ER with correct settings

---

**Last Updated:** 2026-02-23
**Related Files:**
- [accounting.py](../imogi_finance/accounting.py#L176-L650)
- [expense_request.py](../imogi_finance/doctype/expense_request/expense_request.py)
