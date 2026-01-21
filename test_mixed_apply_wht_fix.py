"""
MIXED APPLY WHT FIX - Test Visualization

This script demonstrates the fix for the "double PPh" issue when Expense Request
has MIXED Apply WHT (some items checked, some not).

PROBLEM (Before Fix):
===================
Expense Request:
  Item 1: Rp 200,000 (Apply WHT ❌ NOT checked)
  Item 2: Rp 100,000 (Apply WHT ✅ CHECKED)

Purchase Invoice Result (WRONG):
  PPh - ITB: Rp 6,000 (double - both items taxed by supplier)
  ❌ Item 1 shouldn't have any tax
  ❌ Item 2 gets ER tax (Rp 2,000) + supplier tax (Rp 2,000) = Rp 4,000 WRONG!

Why it happened:
- Logic was: "Are there ANY items with Apply WHT?" → YES
- So: Apply ER's pph_type to ALL items in PI
- BUT: Supplier's category was ALSO applied to all items
- Result: DOUBLE calculation on all items

SOLUTION (After Fix):
===================
Expense Request:
  Item 1: Rp 200,000 (Apply WHT ❌ NOT checked)
  Item 2: Rp 100,000 (Apply WHT ✅ CHECKED)

Purchase Invoice Result (CORRECT):
  PPh - ITB: Rp 2,000 (single - only item 2)
  ✅ Item 1: Rp 0 tax (no Apply WHT)
  ✅ Item 2: Rp 2,000 tax (only ER's Apply WHT)

How it works:
- Detect MIXED mode: "Are there items with AND without Apply WHT?" → YES
- If MIXED:
  - Disable PI-level PPh (apply_tds = 0)
  - Disable supplier's category (tax_withholding_category = None)
  - Let items calculate PPh individually (item-level logic)
- Result: Only items with Apply WHT get taxed

KEY CHANGE IN LOGIC:
===================
Old code:
  if apply_pph:  # "Are there ANY items with Apply WHT?"
      # Set PI-level PPh to ER's type
      # But supplier's category also applies!

New code:
  if has_mixed_pph:  # "Are there items with AND without Apply WHT?"
      # Disable BOTH PI-level PPh and supplier's category
      # Items handle PPh individually
  elif apply_pph:  # "Do ALL items (or no items) have same Apply WHT state?"
      # Safe to use PI-level PPh

VISUALIZATION:
==============
"""

def visualize_fix():
    print("=" * 80)
    print("MIXED APPLY WHT FIX - DETAILED ANALYSIS")
    print("=" * 80)
    
    print("\n1. EXPENSE REQUEST SETUP:")
    print("-" * 80)
    print("Item 1: Utility Expenses - Rp 200,000 (Apply WHT ❌ NOT checked)")
    print("Item 2: Administrative Expenses - Rp 100,000 (Apply WHT ✅ CHECKED)")
    print("")
    print("Detection Logic:")
    print("  - items_with_pph = 1 (only item 2)")
    print("  - total_items = 2")
    print("  - has_mixed_pph = (0 < 1 < 2) = TRUE ✅ MIXED MODE DETECTED!")
    
    print("\n2. ACCOUNTING.PY LOGIC - BEFORE FIX:")
    print("-" * 80)
    print("Old logic check:")
    print("  if apply_pph:  # \"Is there ANY item with Apply WHT?\" → YES")
    print("      pi.tax_withholding_category = request.pph_type")
    print("      pi.apply_tds = 1")
    print("")
    print("Problem:")
    print("  - This applies ER's pph_type to ALL items in PI")
    print("  - But supplier's category ALSO applies to all items")
    print("  - Result: Both sources calculate = DOUBLE")
    
    print("\n3. ACCOUNTING.PY LOGIC - AFTER FIX:")
    print("-" * 80)
    print("New logic chain:")
    print("")
    print("  if apply_pph AND NOT has_mixed_pph:")
    print("      # CONSISTENT mode (all items same, or no items)")
    print("      pi.tax_withholding_category = request.pph_type")
    print("      pi.apply_tds = 1")
    print("      log: 'consistent items'")
    print("")
    print("  elif has_mixed_pph:")
    print("      # MIXED mode (some items yes, some no) ← WE ARE HERE!")
    print("      pi.tax_withholding_category = None  # ← CRITICAL!")
    print("      pi.imogi_pph_type = None")
    print("      pi.apply_tds = 0  # ← DISABLE PI-level PPh")
    print("      log: 'Mixed Apply WHT detected - disabling PI-level PPh'")
    print("      msgprint: '⚠️ Mixed Apply WHT Detected - per-item calculation'")
    print("")
    print("  else:")
    print("      # NO Apply WHT in any item")
    print("      # Use supplier's category if enabled")
    print("      ...")
    
    print("\n4. EVENT HOOK LOGIC - AFTER FIX:")
    print("-" * 80)
    print("New check:")
    print("  is_mixed_mode = (")
    print("      expense_request AND")
    print("      NOT apply_tds AND  # apply_tds=0")
    print("      NOT pph_type AND   # pph_type=None")
    print("      supplier_tax_category  # But supplier category exists (auto-populated)")
    print("  ) = TRUE ← MIXED MODE")
    print("")
    print("Action:")
    print("  if supplier_tax_category exists:")
    print("      doc.tax_withholding_category = None  # ← CLEAR IT!")
    print("      msgprint: '✅ Item-level Apply WHT detected'")
    
    print("\n5. RESULT - PURCHASE INVOICE:")
    print("-" * 80)
    print("PI Configuration:")
    print("  - apply_tds = 0 (disabled)")
    print("  - tax_withholding_category = None (cleared)")
    print("  - imogi_pph_type = None (not set)")
    print("  - Purchase Taxes and Charges Template = \"PPh 23\" (from ER)")
    print("")
    print("Tax Calculation:")
    print("  - PI-level PPh = DISABLED (apply_tds=0)")
    print("  - Item-level PPh = ACTIVE (from ER's per-item Apply WHT)")
    print("")
    print("  Item 1 (Rp 200,000):")
    print("    - Apply WHT in ER = NO")
    print("    - PPh Amount = Rp 0 ✅ (correct!)")
    print("")
    print("  Item 2 (Rp 100,000):")
    print("    - Apply WHT in ER = YES")
    print("    - PPh Amount = Rp 100,000 × 2% = Rp 2,000 ✅ (correct!)")
    print("")
    print("Purchase Taxes and Charges:")
    print("  Type: Actual")
    print("  Account Head: PPh - ITB")
    print("  Tax Rate: 0")
    print("  Amount: Rp 2,000 ✅ (CORRECT! Not Rp 6,000!)")
    print("  Total: Rp 302,000 (300,000 + 2,000 PPh)")
    
    print("\n6. LOGGING OUTPUT:")
    print("-" * 80)
    print("[PPh MIXED DETECTION] ER xxx:")
    print("  1 of 2 items have Apply WHT. This is MIXED mode - supplier's category")
    print("  will NOT be used.")
    print("")
    print("[PPh MIXED MODE] PI xxx:")
    print("  Mixed Apply WHT detected (1/2 items). Disabling PI-level PPh - items will")
    print("  calculate individually. Supplier's category disabled to prevent applying")
    print("  to all items.")
    print("")
    print("[PPh PROTECT] PI xxx:")
    print("  Found supplier's category 'PPh 23%' conflicting with ER Apply WHT. Clearing")
    print("  it to prevent double/unwanted calculation.")
    print("")
    print("Message: ⚠️ Mixed Apply WHT Detected: 1 of 2 items have Apply WHT. PPh will")
    print("be calculated per-item, not at PI level. Supplier's Tax Withholding Category")
    print("is disabled.")
    
    print("\n7. KEY DIFFERENCES:")
    print("-" * 80)
    print("Scenario | Apply WHT on Item | PI-level PPh | Result | Status")
    print("-" * 80)
    print("ALL OFF  | NO items         | Supplier's   | Rp 6k  | ✅ OK (supplier taxed)")
    print("ALL ON   | ALL items        | ER's type    | Rp 4k  | ✅ OK (ER taxed)")
    print("MIXED    | Some yes, some no| DISABLED     | Rp 2k  | ✅ OK (item-level)")
    print("")
    print("In this case, we're in MIXED mode → Result should be Rp 2,000 ✅")
    
    print("\n8. VERIFICATION STEPS:")
    print("-" * 80)
    print("In Frappe, after creating PI:")
    print("  1. Check PI → Taxes & Charges → PPh - ITB should show Rp 2,000")
    print("  2. Check PI → apply_tds should be 0")
    print("  3. Check PI → tax_withholding_category should be None/empty")
    print("  4. Check logs for '[PPh MIXED DETECTION]' and '[PPh PROTECT]' messages")
    print("  5. See orange warning message: '⚠️ Mixed Apply WHT Detected'")
    
    print("\n" + "=" * 80)
    print("SUMMARY: With this fix, MIXED Apply WHT scenarios work correctly!")
    print("Only items with Apply WHT checked get taxed, others don't.")
    print("=" * 80)

if __name__ == "__main__":
    visualize_fix()
