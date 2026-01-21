"""
COMPREHENSIVE TESTING GUIDE FOR DOUBLE WHT PREVENTION FIX

This document provides step-by-step instructions to test the double WHT prevention
fix in a Frappe environment. The fix addresses the issue where both ER's Apply WHT
and Supplier's Tax Withholding Category were calculating simultaneously.

=================================================================================
TEST SCENARIO: ER with Apply WHT on 1 of 2 Items
=================================================================================

BEFORE FIX:
- Expected PPh: Rp 3,000 (from ER Apply WHT on Rp 150,000 item at 2%)
- Actual PPh: Rp 6,000 ❌ (double: Rp 3,000 ER + Rp 3,000 supplier)

AFTER FIX:
- Expected PPh: Rp 3,000 ✅ (from ER only)
- Double calculation prevented!

=================================================================================
STEP 1: SETUP TEST DATA
=================================================================================

1.1 Create Supplier
    - Name: TEST_SUPPLIER_PPh23
    - Tax Withholding Category: PPh 23%
    - (This is important - supplier must have a Tax Category to trigger double calc)

1.2 Create Tax Withholding Category
    If not exists:
    - Shorthand: PPh 23%
    - Rate: 2% (for easy math: Rp 150,000 × 2% = Rp 3,000)

1.3 Create Expense Request
    Navigation: Expense Request List → New
    
    Tab: Detail
    - Company: [Your Company]
    - Supplier: TEST_SUPPLIER_PPh23
    - Request Date: Today
    - Status: Approved (to allow PI creation)
    
    Tab: Items
    Item 1:
    - Expense Account: Travel Expenses (or similar)
    - Amount: 150,000
    - Apply WHT: ❌ UNCHECKED
    - Save
    
    Item 2:
    - Expense Account: Utilities
    - Amount: 150,000
    - Apply WHT: ✅ CHECKED
    - PPh Type: PPh 23% (2%)
    - Save
    
    Expected ER PPh: 150,000 × 2% = Rp 3,000
    (Only item 2 because Apply WHT only checked there)

=================================================================================
STEP 2: CREATE PURCHASE INVOICE FROM ER
=================================================================================

2.1 From Expense Request
    - Open the created ER
    - Click "Create" → "Purchase Invoice"
    - System will create PI with our ON/OFF logic

2.2 Watch for Messages
    During PI creation and validation:
    
    LOG MESSAGES TO LOOK FOR:
    ✓ "[PPh ON/OFF] PI xxx: Apply WHT di ER CENTANG"
    ✓ "[PPh ON/OFF] PI xxx: Clearing supplier's tax_withholding_category"
    ✓ "✅ PPh Configuration: Using... from Expense Request"
    ✓ "Supplier's Tax Withholding Category disabled"
    
    If these messages appear:
    ✅ The fix is working correctly!
    
    If these messages DON'T appear:
    ❌ The fix may not be deployed correctly
    → Check: Are event hooks registered in hooks.py?
    → Check: Did file changes get saved correctly?

2.3 Save PI
    - Let Frappe auto-calculate
    - Don't manually edit tax fields
    - Watch Frappe console for messages

=================================================================================
STEP 3: VERIFY THE RESULTS
=================================================================================

3.1 Check PI Tax Calculation
    In Purchase Invoice, look for:
    
    EXPECTED CORRECT RESULT:
    ✅ DPP (Total): Rp 300,000
    ✅ PPh - ITB: Rp 3,000 (SINGLE, from ER only)
    ✅ Taxes Deducted: Rp 3,000
    
    If you see this = FIX IS WORKING ✅
    
    INCORRECT RESULT (shows fix didn't work):
    ❌ DPP (Total): Rp 300,000
    ❌ PPh - ITB: Rp 6,000 (DOUBLE - still broken!)
    ❌ Taxes Deducted: Rp 6,000
    
    If you see this = FIX NOT DEPLOYED ❌

3.2 Check Field Values
    Click on "PPh - ITB" row in Taxes & Charges:
    - Item Tax Template: Should show ER's pph_type (not supplier's)
    - Amount: Should be Rp 3,000
    
    In main form (edit mode):
    - apply_tds: Should be 1 (enabled)
    - tax_withholding_category: Should be ER's type (PPh 23%)
                                NOT supplier's original type
    - imogi_pph_type: Should match ER's pph_type

3.3 Check Document State
    - PI should be valid (no validation errors)
    - Can save and submit without issues
    - All calculations complete

=================================================================================
STEP 4: CHECK SERVER LOGS FOR DEBUGGING
=================================================================================

4.1 Open Server Log
    Frappe interface → Developer Tools → Server Logs
    OR
    SSH to server → tail -f logs/bench.log | grep "PPh ON/OFF"

4.2 Search for Our Messages
    Filter for: "[PPh ON/OFF]"
    
    Expected sequence:
    1. "[PPh ON/OFF] PI xxx: Apply WHT di ER CENTANG → AKTIFKAN ER's pph_type"
       ↳ Shows PI created with ER's pph_type
    
    2. "[PPh ON/OFF] PI xxx: Clearing supplier's tax_withholding_category"
       ↳ Shows validate hook cleared supplier's category
    
    3. "PPh Configuration: Using... from Expense Request"
       ↳ Shows user notification fired

4.3 If Messages Not Found
    Problem: Event hooks not firing
    
    Solutions:
    1. Clear browser cache and refresh
    2. Check hooks.py has:
       "validate": [
           "imogi_finance.events.purchase_invoice.prevent_double_wht_validate",
           ...
       ]
    3. Restart Frappe bench:
       - bench restart
       - OR bench clear-cache
    4. Check if files were deployed correctly:
       - imogi_finance/accounting.py (lines 281+)
       - imogi_finance/events/purchase_invoice.py (line 63+)
       - imogi_finance/hooks.py (line 206+)

=================================================================================
STEP 5: REGRESSION TESTING
=================================================================================

5.1 Test WITHOUT Apply WHT in ER
    Purpose: Ensure supplier's category can still work
    
    Create ER:
    - Item 1: Rp 150,000 (Apply WHT ❌ NOT checked)
    - Item 2: Rp 150,000 (Apply WHT ❌ NOT checked)
    
    Create PI from ER
    
    Expected Result:
    ✅ Pi PPh = Rp 3,000 from supplier's Tax Withholding Category
    OR
    ✅ PI PPh = Rp 0 (if auto-copy setting disabled)
    
    Check Log:
    ✓ "[PPh ON/OFF] Apply WHT di ER TIDAK CENTANG"
    ✓ "Supplier's category will be used if enabled"

5.2 Test with Supplier WITHOUT Tax Withholding Category
    Purpose: Ensure no errors when supplier has no category
    
    Create Supplier without Tax Withholding Category
    Create ER with that supplier
    - Item 1: Rp 150,000 (Apply WHT ✅ CHECKED)
    
    Create PI from ER
    
    Expected Result:
    ✅ PI PPh = Rp 3,000 from ER only
    ✅ No error message
    
    Check Log:
    ✓ "[PPh ON/OFF] Clearing supplier's tax_withholding_category: None"
    ✓ No error about missing supplier category

5.3 Test with Auto-Copy Setting DISABLED
    Purpose: Ensure auto-copy feature respects setting
    
    In Settings: use_supplier_wht_if_no_er_pph = DISABLED
    
    Create ER WITHOUT Apply WHT:
    - Item 1: Rp 150,000 (Apply WHT ❌)
    
    Create PI from ER
    
    Expected Result:
    ✅ PI PPh = Rp 0 (no PPh at all)
    ✅ No supplier's category used
    
    Check Log:
    ✓ "[PPh ON/OFF] Apply WHT di ER TIDAK CENTANG (setting disabled)"
    ✓ "NO PPh dari supplier"

5.4 Test Apply WHT on BOTH Items
    Purpose: Ensure total PPh is correct when multiple items have Apply WHT
    
    Create ER:
    - Item 1: Rp 150,000 (Apply WHT ✅)
    - Item 2: Rp 150,000 (Apply WHT ✅)
    
    Create PI from ER
    
    Expected Result:
    ✅ PI PPh = Rp 6,000 (Rp 150,000 + Rp 150,000 × 2%)
    ✅ NO DOUBLE from supplier
    ✅ All PPh from ER only

=================================================================================
STEP 6: MONITORING & VERIFICATION
=================================================================================

6.1 Create 5-10 Test PIs
    Purpose: Verify fix works consistently
    
    Steps:
    1. Create multiple ERs with Apply WHT variations
    2. Create PIs from each
    3. Compare results
    4. Check logs for messages
    5. Verify no double calculations

6.2 Check Database Values
    If needed, query database:
    
    SELECT name, apply_tds, tax_withholding_category, 
           imogi_pph_type, imogi_expense_request
    FROM `tabPurchase Invoice`
    WHERE imogi_expense_request IS NOT NULL
    LIMIT 10;
    
    Expected:
    - apply_tds = 1 (when ER has Apply WHT)
    - tax_withholding_category = ER's pph_type (when Apply WHT checked)
    - imogi_pph_type = ER's pph_type
    
    NOT expected:
    - apply_tds = 0 with active tax category
    - Both tax_withholding_category and imogi_pph_type different

6.3 Verify No Performance Issues
    Purpose: Ensure fix doesn't slow down PI creation
    
    Monitor:
    - PI creation time (should be normal)
    - Server resource usage (should be normal)
    - No database locks
    - No slow queries in logs

=================================================================================
STEP 7: FINAL VERIFICATION
=================================================================================

7.1 Success Criteria - All Must Pass ✅
    ✅ PI PPh = Rp 3,000 (not Rp 6,000) when Apply WHT on 1 item
    ✅ "[PPh ON/OFF]" messages in logs
    ✅ "✅ PPh Configuration" user message appears
    ✅ PI can be saved and submitted without errors
    ✅ Supplier's category properly cleared when ER Apply WHT active
    ✅ Supplier's category used when ER Apply WHT NOT active (if setting enabled)
    ✅ No unexpected errors in logs
    ✅ Multiple test cases work consistently

7.2 If Any Criteria Fails
    ❌ PPh still shows double (Rp 6,000)?
       → Check server logs for error messages
       → Verify files deployed correctly
       → Check hooks.py has event hook registered
       → Restart Frappe bench
    
    ❌ Messages not appearing?
       → Clear cache: bench clear-cache
       → Restart bench
       → Check if files saved correctly
    
    ❌ Errors during PI creation?
       → Check Frappe console for error messages
       → Verify field names are correct
       → Check tax configuration is valid
    
    ❌ Supplier's category not cleared?
       → Check validate hook is firing
       → Verify _prevent_double_wht() function exists
       → Check event hook registration in hooks.py

=================================================================================
STEP 8: DEPLOYMENT CHECKLIST
=================================================================================

Before considering fix complete, verify:

□ All files modified and saved:
  ✓ imogi_finance/accounting.py (lines 281-370)
  ✓ imogi_finance/events/purchase_invoice.py (lines 63-260)
  ✓ imogi_finance/hooks.py (line 206+)

□ No syntax errors:
  ✓ Python files valid
  ✓ No import errors
  ✓ No undefined variables

□ Testing completed:
  ✓ Create 5+ test cases
  ✓ All scenarios work
  ✓ No errors in logs
  ✓ PPh calculations correct

□ Regression testing passed:
  ✓ ER without Apply WHT works
  ✓ Supplier without category works
  ✓ Auto-copy setting respected
  ✓ Multiple Apply WHT items work

□ Server logs reviewed:
  ✓ "[PPh ON/OFF]" messages present
  ✓ No error messages related to fix
  ✓ No slow queries
  ✓ No database lock issues

□ Performance verified:
  ✓ PI creation time normal
  ✓ No server resource spike
  ✓ Response times acceptable

□ User impact:
  ✓ Users see correct PPh amounts
  ✓ Notifications helpful (green indicators)
  ✓ No confusion about why PPh changed
  ✓ Documentation available

=================================================================================
QUICK REFERENCE: Expected Values
=================================================================================

Test Case 1: Apply WHT on 1 of 2 items (Rp 150,000 each)
├─ Apply WHT on Item 2 only
├─ Expected PPh: Rp 3,000 (150,000 × 2%)
└─ If shows Rp 6,000: FIX NOT WORKING ❌

Test Case 2: Apply WHT on both items (Rp 150,000 each)
├─ Apply WHT on both
├─ Expected PPh: Rp 6,000 (300,000 × 2%)
└─ Should NOT show Rp 9,000 or higher

Test Case 3: No Apply WHT (supplier has category)
├─ Apply WHT: NOT checked
├─ Supplier Tax Category: PPh 23%
├─ Expected PPh: Rp 6,000 from supplier (if setting enabled)
└─ If shows Rp 0: Setting might be disabled

Test Case 4: No Apply WHT, no supplier category
├─ Apply WHT: NOT checked
├─ Supplier Tax Category: None
├─ Expected PPh: Rp 0
└─ Should be error-free

=================================================================================
CONCLUSION
=================================================================================

When all tests pass:
✅ Double WHT prevention is working correctly!
✅ ON/OFF logic is functioning as designed!
✅ Ready for production use!

Document tested: [DATE]
Tested by: [YOUR NAME]
Status: [WORKING / ISSUE FOUND]

If any issues found, document them and investigate:
- Check if files modified are correct
- Verify logic implementation
- Check Frappe framework behavior
- Review server logs for clues
"""
