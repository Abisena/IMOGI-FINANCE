frappe.ui.form.on("Advance Payment Entry", {
    refresh(frm) {
        frm.trigger("recalculate_totals");
        frm.trigger("toggle_allocation_status");
        
        // Add "Reconcile Payments" button if there are allocations
        if (frm.doc.docstatus === 1 && frm.doc.payment_entry && frm.doc.references && frm.doc.references.length > 0) {
            frm.add_custom_button(__("Reconcile Payments"), () => {
                open_payment_reconciliation(frm);
            }, __("Actions"));
            
            // Show allocation summary in dashboard
            show_allocation_summary(frm);
        }
    },

    advance_amount(frm) {
        frm.trigger("recalculate_totals");
    },

    exchange_rate(frm) {
        frm.trigger("recalculate_totals");
    },

    recalculate_totals(frm) {
        const allowUpdates = frm.doc.docstatus === 0;
        const flt = (frappe.utils && frappe.utils.flt) || window.flt || ((value) => parseFloat(value) || 0);
        const allocated = (frm.doc.references || []).reduce((acc, row) => acc + flt(row.allocated_amount), 0);
        const unallocated = flt(frm.doc.advance_amount) - allocated;

        if (allowUpdates) {
            frm.set_value("allocated_amount", allocated);
            frm.set_value("unallocated_amount", unallocated);
            frm.set_value("base_advance_amount", flt(frm.doc.advance_amount) * flt(frm.doc.exchange_rate || 1));
            frm.set_value("base_allocated_amount", allocated * flt(frm.doc.exchange_rate || 1));
            frm.set_value("base_unallocated_amount", flt(frm.doc.base_advance_amount) - flt(frm.doc.base_allocated_amount));
        }

        if (allowUpdates) {
            (frm.doc.references || []).forEach((row) => {
                row.remaining_amount = Math.max(unallocated, 0);
                if (!row.reference_currency) {
                    row.reference_currency = frm.doc.currency;
                }
                if (!row.reference_exchange_rate) {
                    row.reference_exchange_rate = frm.doc.exchange_rate;
                }
            });
        }

        frm.refresh_field("references");
    },

    toggle_allocation_status(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.unallocated_amount && frm.doc.unallocated_amount <= 0) {
            frm.set_value("status", "Reconciled");
        }
    },

    references_remove(frm) {
        frm.trigger("recalculate_totals");
    },
});

frappe.ui.form.on("Advance Payment Reference", {
    allocated_amount(frm) {
        frm.trigger("recalculate_totals");
    },
    
    references_remove(frm, cdt, cdn) {
        // Handle row deletion - just recalculate, cleanup handled on save
        frm.trigger("recalculate_totals");
    },
});

// Helper function to open Payment Reconciliation with pre-filters
function open_payment_reconciliation(frm) {
    if (!frm.doc.party_type || !frm.doc.party) {
        frappe.msgprint(__("Party Type and Party are required for reconciliation."));
        return;
    }
    
    // Get unique invoice names from references
    const invoice_names = [...new Set(
        (frm.doc.references || [])
            .filter(row => row.invoice_name)
            .map(row => row.invoice_name)
    )];
    
    if (!invoice_names.length) {
        frappe.msgprint(__("No invoices found to reconcile."));
        return;
    }
    
    frappe.call({
        method: "imogi_finance.advance_payment.api.get_payment_reconciliation_data",
        args: {
            party_type: frm.doc.party_type,
            party: frm.doc.party,
            payment_entry: frm.doc.payment_entry,
            invoice_names: invoice_names,
        },
        callback: function(r) {
            if (r.message) {
                // Set route options to pre-fill form fields
                frappe.route_options = {
                    "company": frm.doc.company,
                    "party_type": frm.doc.party_type,
                    "party": frm.doc.party,
                    "receivable_payable_account": r.message.account
                };
                
                // Open Payment Reconciliation tool (will auto-populate from route_options)
                frappe.new_doc("Payment Reconciliation");
                
                // Auto-trigger "Get Unreconciled Entries" after form loads
                setTimeout(() => {
                    if (cur_frm && cur_frm.doctype === "Payment Reconciliation") {
                        // Trigger the get_unreconciled_entries method
                        cur_frm.trigger("get_unreconciled_entries");
                        
                        frappe.show_alert({
                            message: __("Loading invoices and payments automatically..."),
                            indicator: "blue"
                        }, 5);
                    }
                }, 1000);
            }
        }
    });
}

// Helper function to show allocation summary with warnings for partial allocations
function show_allocation_summary(frm) {
    if (!frm.doc.references || !frm.doc.references.length) {
        return;
    }
    
    frappe.call({
        method: "imogi_finance.advance_payment.api.check_allocation_coverage",
        args: {
            references: frm.doc.references
        },
        callback: function(r) {
            if (!r.message) return;
            
            const { partial_allocations, over_allocations } = r.message;
            
            // Handle over-allocations (critical)
            if (over_allocations && over_allocations.length > 0) {
                let message = __("<b>⚠️ Over-Allocation Detected:</b><br>");
                
                over_allocations.forEach(item => {
                    message += __("• {0}: Allocated {1}, but invoice total is only {2} (excess: {3})<br>", [
                        item.invoice_name,
                        frappe.format(item.allocated, {fieldtype: "Currency"}),
                        frappe.format(item.total, {fieldtype: "Currency"}),
                        frappe.format(item.excess, {fieldtype: "Currency"})
                    ]);
                });
                
                message += __("<br><i>This can happen when a credit note is issued after allocation. Click 'Fix Over-Allocation' to auto-adjust.</i>");
                
                frm.dashboard.set_headline_alert(message, "red");
                
                // Add button to fix over-allocation
                frm.add_custom_button(__("Fix Over-Allocation"), () => {
                    frappe.confirm(
                        __("This will proportionally reduce all allocations to match the invoice total. Continue?"),
                        () => {
                            over_allocations.forEach(item => {
                                frappe.call({
                                    method: "imogi_finance.advance_payment.api.fix_over_allocation",
                                    args: {
                                        invoice_doctype: item.invoice_doctype,
                                        invoice_name: item.invoice_name
                                    },
                                    callback: function(r2) {
                                        if (r2.message && r2.message.success) {
                                            frappe.show_alert({
                                                message: __("Over-allocation fixed: {0}", [r2.message.message]),
                                                indicator: "green"
                                            }, 5);
                                            frm.reload_doc();
                                        }
                                    }
                                });
                            });
                        }
                    );
                }, __("Actions"));
                
                return; // Don't show partial warning if there's over-allocation
            }
            
            // Handle partial allocations (warning)
            if (partial_allocations && partial_allocations.length > 0) {
                let message = __("<b>Partial Allocation Warning:</b><br>");
                
                partial_allocations.forEach(item => {
                    message += __("• {0}: Allocated {1} of {2} ({3} remaining)<br>", [
                        item.invoice_name,
                        frappe.format(item.allocated, {fieldtype: "Currency"}),
                        frappe.format(item.total, {fieldtype: "Currency"}),
                        frappe.format(item.remaining, {fieldtype: "Currency"})
                    ]);
                });
                
                message += __("<br><i>Tip: Use 'Reconcile Payments' button to complete the payment, or allocate more advances from other entries.</i>");
                
                frm.dashboard.set_headline_alert(message, "orange");
            }
        }
    });
}
