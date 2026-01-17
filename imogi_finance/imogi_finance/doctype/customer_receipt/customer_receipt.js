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

// Child table behavior: only help set parent customer/company; 
// reference fields are computed in Python (set_reference_meta).
frappe.ui.form.on('Customer Receipt Item', {
    items_add: function(frm) {
        setup_item_query_filters(frm);
    },

    sales_invoice: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.sales_invoice) return;

        // If purpose not set, assume Billing (Sales Invoice)
        if (!frm.doc.receipt_purpose) {
            frm.set_value('receipt_purpose', 'Billing (Sales Invoice)');
            setup_item_query_filters(frm);
        } else if (frm.doc.receipt_purpose !== 'Billing (Sales Invoice)') {
            frappe.msgprint(__('Please set Receipt Purpose to "Billing (Sales Invoice)" to use Sales Invoice'));
            frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
            return;
        }

        // Clear opposite reference if filled
        if (row.sales_order) {
            frappe.model.set_value(cdt, cdn, 'sales_order', '');
        }

        // Only use fetched data to populate parent fields; 
        // child reference fields stay server-driven.
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Sales Invoice',
                name: row.sales_invoice,
                fields: ['customer', 'company', 'docstatus']
            },
            callback: function(r) {
                if (!r.message) return;

                if (r.message.docstatus !== 1) {
                    frappe.msgprint(__('Sales Invoice must be submitted before linking'));
                    frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                    return;
                }

                // Auto-fill customer/company if missing; else validate match
                if (!frm.doc.customer) {
                    frm.set_value('customer', r.message.customer);
                } else if (frm.doc.customer !== r.message.customer) {
                    frappe.msgprint(__('Sales Invoice customer does not match Customer Receipt customer'));
                    frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                    return;
                }

                if (!frm.doc.company) {
                    frm.set_value('company', r.message.company);
                } else if (frm.doc.company !== r.message.company) {
                    frappe.msgprint(__('Sales Invoice company does not match Customer Receipt company'));
                    frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                    return;
                }
            }
        });
    },

    sales_order: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.sales_order) return;

        // If purpose not set, assume Before Billing (Sales Order)
        if (!frm.doc.receipt_purpose) {
            frm.set_value('receipt_purpose', 'Before Billing (Sales Order)');
            setup_item_query_filters(frm);
        } else if (frm.doc.receipt_purpose !== 'Before Billing (Sales Order)') {
            frappe.msgprint(__('Please set Receipt Purpose to "Before Billing (Sales Order)" to use Sales Order'));
            frappe.model.set_value(cdt, cdn, 'sales_order', '');
            return;
        }

        // Clear opposite reference if filled
        if (row.sales_invoice) {
            frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
        }

        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Sales Order',
                name: row.sales_order,
                fields: ['customer', 'company', 'docstatus']
            },
            callback: function(r) {
                if (!r.message) return;

                if (r.message.docstatus !== 1) {
                    frappe.msgprint(__('Sales Order must be submitted before linking'));
                    frappe.model.set_value(cdt, cdn, 'sales_order', '');
                    return;
                }

                // Auto-fill customer/company if missing; else validate match
                if (!frm.doc.customer) {
                    frm.set_value('customer', r.message.customer);
                } else if (frm.doc.customer !== r.message.customer) {
                    frappe.msgprint(__('Sales Order customer does not match Customer Receipt customer'));
                    frappe.model.set_value(cdt, cdn, 'sales_order', '');
                    return;
                }

                if (!frm.doc.company) {
                    frm.set_value('company', r.message.company);
                } else if (frm.doc.company !== r.message.company) {
                    frappe.msgprint(__('Sales Order company does not match Customer Receipt company'));
                    frappe.model.set_value(cdt, cdn, 'sales_order', '');
                    return;
                }
            }
        });
    }
});
