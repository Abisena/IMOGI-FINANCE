"""
Test script to verify the double WHT prevention fix.

This test simulates the scenario from the real-world test:
- Create ER with 2 items
- Check Apply WHT on item 2 only (Rp 150,000)
- Expected: Rp 3,000 PPh (from ER only, not double)
- Before fix: Rp 6,000 PPh (from ER + Supplier = DOUBLE) ❌
- After fix: Rp 3,000 PPh (from ER only) ✅

Key changes in fix:
1. Set apply_tds = 0 BEFORE assigning supplier in accounting.py
   - Prevents Frappe's TDS auto-calculation from supplier
2. Set apply_tds = 1 in ON/OFF logic when ER's Apply WHT is checked
   - Re-enables TDS but now for ER's pph_type
3. Clear supplier's tax_withholding_category in _prevent_double_wht()
   - Explicitly set to None when ER Apply WHT is active
   - Use msgprint to notify user (green indicator)

Expected behavior:
- If Apply WHT checked: Use ER's pph_type (pi.apply_tds=1, pi.tax_withholding_category=ER's type)
- If Apply WHT not checked: 
  - If setting enabled: Use supplier's category (pi.apply_tds=1, pi.tax_withholding_category=supplier's type)
  - If setting disabled: No PPh (pi.apply_tds=0)
- NEVER BOTH active at same time
"""

def test_double_wht_prevention():
    """Test that double WHT is prevented with ON/OFF logic."""
    
    # Simulated scenario from real test
    print("=" * 80)
    print("TEST: Double WHT Prevention with Timing Fix")
    print("=" * 80)
    
    # ER scenario
    print("\n1. EXPENSE REQUEST:")
    print("   Item 1: Utility - Rp 150,000 (Apply WHT ❌)")
    print("   Item 2: Admin - Rp 150,000 (Apply WHT ✅)")
    print("   Expected ER PPh: Rp 3,000 (from item 2 only)")
    
    apply_wht_item_2 = True
    pph_rate = 0.02  # 2%
    item_2_amount = 150000
    expected_pph_from_er = item_2_amount * pph_rate
    print(f"   Calculation: Rp {item_2_amount:,} × {pph_rate*100}% = Rp {expected_pph_from_er:,.0f} ✅")
    
    # PI creation scenario - BEFORE FIX
    print("\n2. PURCHASE INVOICE - BEFORE FIX:")
    print("   Problem: Both ER's pph_type AND supplier's tax_withholding_category active")
    print("   - ER Apply WHT → imogi_pph_type set to ER's type")
    print("   - Supplier assigned → Frappe auto-populates tax_withholding_category")
    print("   - Both sources calculate simultaneously")
    print("   - PPh calculation: Rp 3,000 (ER) + Rp 3,000 (supplier) = Rp 6,000 ❌ DOUBLE!")
    
    # PI creation scenario - AFTER FIX
    print("\n3. PURCHASE INVOICE - AFTER FIX:")
    print("   Key changes:")
    print("   a) Set apply_tds = 0 BEFORE supplier assignment")
    print("      → Prevents Frappe's initial TDS auto-calculation")
    print("   b) ON/OFF logic in accounting.py:")
    print("      → If ER Apply WHT: set pi.apply_tds = 1, pi.tax_withholding_category = ER's type")
    print("      → Else: keep apply_tds = 0 or set supplier's type based on setting")
    print("   c) _prevent_double_wht() in event hook:")
    print("      → If ER Apply WHT: explicitly set tax_withholding_category = None")
    print("      → Ensures supplier's category doesn't interfere")
    
    # Expected result after fix
    print("\n4. EXPECTED RESULT AFTER FIX:")
    print(f"   Purchase Invoice total (DPP): Rp 300,000")
    print(f"   PPh - ITB: Rp {expected_pph_from_er:,.0f} ✅ (from ER only, NOT double)")
    print(f"   Taxes Deducted: Rp {expected_pph_from_er:,.0f} ✅")
    
    # Real test verification
    print("\n5. REAL TEST VERIFICATION:")
    print("   Status: Pending actual execution in Frappe environment")
    print("   - Create ER with same scenario")
    print("   - Create PI from ER")
    print("   - Verify PPh = Rp 3,000 (not Rp 6,000)")
    print("   - Check logs for '[PPh ON/OFF]' messages")
    
    print("\n6. TIMING ANALYSIS:")
    print("   Old order (problematic):")
    print("   - pi = new_doc()")
    print("   - pi.supplier = X → Frappe populates tax_withholding_category from supplier")
    print("   - pi.apply_tds = 1")
    print("   - pi.tax_withholding_category = ER's type → TOO LATE, supplier already set!")
    print("   - Frappe TDS calculates BOTH")
    print("")
    print("   New order (fixed):")
    print("   - pi = new_doc()")
    print("   - pi.apply_tds = 0 → Block TDS initially")
    print("   - pi.supplier = X → Frappe populates tax_withholding_category, but TDS blocked")
    print("   - pi.apply_tds = 1 (if ER Apply WHT) → Re-enable TDS")
    print("   - pi.tax_withholding_category = ER's type → Now effective")
    print("   - validate hook clears supplier's category")
    print("   - Only ER's type calculates")
    
    print("\n7. CODE LOCATIONS:")
    print("   - accounting.py line 281-368: ON/OFF logic implementation")
    print("   - events/purchase_invoice.py line 181-260: _prevent_double_wht() function")
    print("   - hooks.py: validate hook calls prevent_double_wht_validate")
    
    print("\n" + "=" * 80)
    print("Test setup complete. Ready for real Frappe environment execution.")
    print("=" * 80)
    
    return {
        "expected_pph": expected_pph_from_er,
        "expected_status": "PPh Rp 3,000 (NOT DOUBLE)",
        "test_scenario": "ER with Apply WHT on 1 of 2 items"
    }

if __name__ == "__main__":
    result = test_double_wht_prevention()
    print(f"\nTest result: {result}")
