/**
 * Browser Console Debug Commands for Budget Control Entry
 * 
 * Jalankan di browser console untuk troubleshoot Budget Control Entry
 * 
 * Usage:
 * 1. Buka Expense Request di browser
 * 2. Buka browser console (F12 atau Cmd+Option+I)
 * 3. Copy-paste command yang diperlukan
 */

// ============================================================================
// 1. CEK APAKAH BUDGET CONTROL ENTRY SUDAH DIBUAT
// ============================================================================
window.check_bce_exists = function(expense_request_name) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Budget Control Entry',
            filters: {
                ref_doctype: 'Expense Request',
                ref_name: expense_request_name || cur_frm.doc.name
            },
            fields: ['name', 'entry_type', 'amount', 'direction', 'posting_date', 'docstatus']
        },
        callback: function(r) {
            console.log('=== Budget Control Entries ===');
            if (r.message && r.message.length > 0) {
                console.table(r.message);
                console.log(`Found ${r.message.length} entries`);
            } else {
                console.log('❌ NO Budget Control Entry found!');
            }
        }
    });
}

// ============================================================================
// 2. CEK KONFIGURASI BUDGET CONTROL SETTING
// ============================================================================
window.check_budget_settings = function() {
    frappe.call({
        method: 'imogi_finance.budget_control.utils.get_settings',
        callback: function(r) {
            console.log('=== Budget Control Settings ===');
            if (r.message) {
                console.log('Enable Budget Lock:', r.message.enable_budget_lock);
                console.log('Lock on Workflow State:', r.message.lock_on_workflow_state);
                console.log('Budget Controller Role:', r.message.budget_controller_role);
                console.log('Allow Budget Overrun Role:', r.message.allow_budget_overrun_role);
                console.log('Enable Budget Reclass:', r.message.enable_budget_reclass);
                console.log('Enable Additional Budget:', r.message.enable_additional_budget);
                console.log('\nFull Settings:', r.message);
            } else {
                console.log('❌ Budget Control Setting not found!');
            }
        },
        error: function(r) {
            console.error('❌ Error loading settings:', r);
            console.log('⚠️ Trying alternative method...');
            
            // Alternative: Try via frappe.db.get_single_value
            frappe.db.get_single_value('Budget Control Setting', 'enable_budget_lock')
                .then(enable_budget_lock => {
                    console.log('Enable Budget Lock:', enable_budget_lock);
                    return frappe.db.get_single_value('Budget Control Setting', 'lock_on_workflow_state');
                })
                .then(lock_on_workflow_state => {
                    console.log('Lock on Workflow State:', lock_on_workflow_state);
                })
                .catch(err => {
                    console.error('❌ All methods failed:', err);
                });
        }
    });
}

// ============================================================================
// 3. CEK DIMENSI BUDGET (COST CENTER, ACCOUNT, DLL)
// ============================================================================
window.check_budget_dimensions = function() {
    if (!cur_frm || cur_frm.doctype !== 'Expense Request') {
        console.error('Please open an Expense Request first!');
        return;
    }
    
    const doc = cur_frm.doc;
    console.log('=== Budget Dimensions ===');
    console.log('Cost Center:', doc.cost_center);
    console.log('Project:', doc.project);
    console.log('Branch:', doc.branch);
    console.log('Company:', doc.company);
    console.log('Status:', doc.status);
    console.log('Workflow State:', doc.workflow_state);
    console.log('Allocation Mode:', doc.allocation_mode);
    console.log('Budget Lock Status:', doc.budget_lock_status);
    console.log('Budget Workflow State:', doc.budget_workflow_state);
    
    console.log('\n=== Items ===');
    if (doc.items && doc.items.length > 0) {
        console.table(doc.items.map(item => ({
            item_code: item.item_code,
            expense_account: item.expense_account,
            amount: item.amount,
            qty: item.qty,
            rate: item.rate
        })));
    } else {
        console.log('❌ No items found!');
    }
}

// ============================================================================
// 4. MANUAL TRIGGER RESERVE BUDGET
// ============================================================================
window.trigger_reserve_budget = function(expense_request_name) {
    const docname = expense_request_name || (cur_frm && cur_frm.doc.name);
    
    if (!docname) {
        console.error('Please provide expense request name or open the document!');
        return;
    }
    
    console.log('🔄 Triggering reserve_budget_for_request for:', docname);
    console.log('⏳ Please wait...');
    
    frappe.call({
        method: 'imogi_finance.budget_control.workflow.reserve_budget_for_request',
        args: {
            expense_request: docname
        },
        freeze: true,
        freeze_message: __('Creating Budget Control Entry...'),
        callback: function(r) {
            console.log('\n=== Reserve Budget Result ===');
            if (r.message) {
                console.log('✅ Success! Created entries:', r.message);
                console.table(r.message);
                
                // Reload document to show updated fields
                if (cur_frm && cur_frm.doc.name === docname) {
                    console.log('🔄 Reloading document...');
                    cur_frm.reload_doc();
                }
            } else if (r.exc) {
                console.error('❌ Error:', r.exc);
            } else {
                console.log('⚠️ Completed but no entries returned (check server logs)');
            }
            
            // Check if entries were created
            setTimeout(() => {
                console.log('\n🔍 Verifying entries...');
                window.check_bce_exists(docname);
            }, 1500);
        },
        error: function(r) {
            console.error('❌ Error calling reserve_budget:', r);
            console.log('\n💡 Possible reasons:');
            console.log('1. Budget lock is disabled in settings');
            console.log('2. Document status is not "Approved"');
            console.log('3. No items with expense accounts');
            console.log('4. Fiscal year not found');
            console.log('\nRun debug_budget_control() to investigate');
        }
    });
}

// ============================================================================
// 5. CEK APAKAH BUDGET DOCUMENT ADA
// ============================================================================
window.check_budget_exists = function() {
    if (!cur_frm || cur_frm.doctype !== 'Expense Request') {
        console.error('Please open an Expense Request first!');
        return;
    }
    
    const doc = cur_frm.doc;
    
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'Budget',
            filters: {
                company: doc.company,
                cost_center: doc.cost_center
            },
            fields: ['name', 'fiscal_year', 'cost_center', 'docstatus']
        },
        callback: function(r) {
            console.log('=== Budget Documents ===');
            if (r.message && r.message.length > 0) {
                console.table(r.message);
                console.log(`✅ Found ${r.message.length} budget(s)`);
            } else {
                console.log('❌ NO Budget found for this Cost Center!');
                console.log('Cost Center:', doc.cost_center);
                console.log('Company:', doc.company);
            }
        }
    });
}

// ============================================================================
// 6. FULL DEBUG - JALANKAN SEMUA CHECKS
// ============================================================================
window.debug_budget_control = function(expense_request_name) {
    const docname = expense_request_name || (cur_frm && cur_frm.doc.name);
    
    console.log('======================================');
    console.log('BUDGET CONTROL FULL DEBUG');
    console.log('======================================');
    console.log('Document:', docname);
    console.log('Time:', new Date().toISOString());
    console.log('');
    
    // 1. Check settings
    check_budget_settings();
    
    setTimeout(() => {
        // 2. Check dimensions
        check_budget_dimensions();
        
        setTimeout(() => {
            // 3. Check budget exists
            check_budget_exists();
            
            setTimeout(() => {
                // 4. Check BCE exists
                check_bce_exists(docname);
                
                console.log('\n======================================');
                console.log('DEBUG COMPLETED');
                console.log('======================================');
            }, 500);
        }, 500);
    }, 500);
}

// ============================================================================
// 7. HELPER: RELOAD DOCUMENT
// ============================================================================
window.reload_doc = function() {
    if (cur_frm) {
        cur_frm.reload_doc();
        console.log('✅ Document reloaded');
    }
}

// ============================================================================
// INSTRUCTIONS
// ============================================================================
console.log('==============================================');
console.log('Budget Control Debug Commands Loaded!');
console.log('==============================================');
console.log('');
console.log('Available Commands:');
console.log('1. check_bce_exists()        - Cek apakah Budget Control Entry sudah dibuat');
console.log('2. check_budget_settings()   - Cek konfigurasi Budget Control Setting');
console.log('3. check_budget_dimensions() - Cek dimensi budget (cost center, account, dll)');
console.log('4. trigger_reserve_budget()  - Manual trigger reserve budget');
console.log('5. check_budget_exists()     - Cek apakah Budget document ada');
console.log('6. debug_budget_control()    - Jalankan semua checks');
console.log('7. reload_doc()              - Reload document');
console.log('');
console.log('Quick Start:');
console.log('1. Buka Expense Request yang sudah Approved');
console.log('2. Run: debug_budget_control()');
console.log('3. Lihat hasil di console');
console.log('');
console.log('Manual Trigger:');
console.log('trigger_reserve_budget("ER-2026-000027")');
console.log('==============================================');
