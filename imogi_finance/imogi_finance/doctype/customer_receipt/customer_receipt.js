// Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
// For license information, please see license.txt

frappe.ui.form.on('Customer Receipt', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.outstanding_amount > 0) {
            frm.add_custom_button(__('Make Payment Entry'), function() {
                frappe.call({
                    method: 'make_payment_entry',
                    doc: frm.doc,
                    callback: function(r) {
                        if (r.message) {
                            frappe.set_route('Form', 'Payment Entry', r.message.name);
                        }
                    }
                });
            });
        }

        // Track print action
        if (frm.doc.docstatus === 1) {
            frm.page.on('print', function() {
                frappe.call({
                    method: 'track_print',
                    doc: frm.doc,
                    callback: function(r) {
                        if (r.message) {
                            frm.reload_doc();
                        }
                    }
                });
            });
        }
    },

    receipt_purpose: function(frm) {
        // Clear items when receipt purpose changes
        frm.clear_table('items');
        frm.refresh_field('items');
        // Update query filters for future rows
        setup_item_query_filters(frm);
    },

    customer: function(frm) {
        // Clear items when customer changes
        frm.clear_table('items');
        frm.refresh_field('items');
        // Update query filters for future rows
        setup_item_query_filters(frm);
    },

    company: function(frm) {
        // Clear items when company changes
        frm.clear_table('items');
        frm.refresh_field('items');
        // Update query filters for future rows
        setup_item_query_filters(frm);
    }
});

// Helper function to setup query filters
function setup_item_query_filters(frm) {
    // Set up query filters for Sales Invoice
    if (frm.doc.receipt_purpose === 'Billing (Sales Invoice)') {
        frm.set_query('sales_invoice', 'items', function() {
            return {
                filters: {
                    'customer': frm.doc.customer || '',
                    'company': frm.doc.company || '',
                    'docstatus': 1,
                    'outstanding_amount': ['>', 0]
                }
            };
        });
        // Clear sales_order query
        frm.set_query('sales_order', 'items', function() {
            return { filters: { 'name': ['=', ''] } }; // Return empty to hide
        });
    }
    // Set up query filters for Sales Order
    else if (frm.doc.receipt_purpose === 'Before Billing (Sales Order)') {
        frm.set_query('sales_order', 'items', function() {
            return {
                filters: {
                    'customer': frm.doc.customer || '',
                    'company': frm.doc.company || '',
                    'docstatus': 1
                }
            };
        });
        // Clear sales_invoice query
        frm.set_query('sales_invoice', 'items', function() {
            return { filters: { 'name': ['=', ''] } }; // Return empty to hide
        });
    }
}
