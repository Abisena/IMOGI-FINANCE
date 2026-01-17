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

frappe.ui.form.on('Customer Receipt Item', {
    items_add: function(frm) {
        // Query filters are already set at parent level
        setup_item_query_filters(frm);
    },

    sales_invoice: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.sales_invoice) return;

        // Enforce mode: only allow Sales Invoice in Billing mode
        if (frm.doc.receipt_purpose !== 'Billing (Sales Invoice)') {
            frappe.msgprint(__('Please set Receipt Purpose to "Billing (Sales Invoice)" to use Sales Invoice'));
            frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
            return;
        }

        // Clear opposite field using official API
        if (row.sales_order) {
            frappe.model.set_value(cdt, cdn, 'sales_order', '');
        }

        fetch_sales_invoice_data(frm, cdt, cdn);
    },

    sales_order: function(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.sales_order) return;

        // Enforce mode: only allow Sales Order in Before Billing mode
        if (frm.doc.receipt_purpose !== 'Before Billing (Sales Order)') {
            frappe.msgprint(__('Please set Receipt Purpose to "Before Billing (Sales Order)" to use Sales Order'));
            frappe.model.set_value(cdt, cdn, 'sales_order', '');
            return;
        }

        // Clear opposite field using official API
        if (row.sales_invoice) {
            frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
        }

        fetch_sales_order_data(frm, cdt, cdn);
    }
});

function fetch_sales_invoice_data(frm, cdt, cdn) {
    const current = locals[cdt][cdn];
    if (!current || !current.sales_invoice) return;

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Sales Invoice',
            name: current.sales_invoice,
            fields: ['customer', 'company', 'posting_date', 'outstanding_amount', 'grand_total', 'docstatus']
        },
        callback: function(r) {
            const row = locals[cdt][cdn];
            if (!row || !r.message) return; // row might have been deleted/changed

            // Auto-populate customer/company if empty (standard pattern in v15)
            if (!frm.doc.customer) {
                frm.set_value('customer', r.message.customer);
            }
            if (!frm.doc.company) {
                frm.set_value('company', r.message.company);
            }

            // Basic validations
            if (r.message.customer !== frm.doc.customer) {
                frappe.msgprint(__('Sales Invoice customer does not match Customer Receipt customer'));
                frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                return;
            }
            if (r.message.company !== frm.doc.company) {
                frappe.msgprint(__('Sales Invoice company does not match Customer Receipt company'));
                frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                return;
            }
            if (r.message.docstatus !== 1) {
                frappe.msgprint(__('Sales Invoice must be submitted before linking'));
                frappe.model.set_value(cdt, cdn, 'sales_invoice', '');
                return;
            }

            // Use frappe.model.set_value so grid refresh stays in core control
            frappe.model.set_value(cdt, cdn, 'reference_date', r.message.posting_date);
            frappe.model.set_value(cdt, cdn, 'reference_outstanding', r.message.outstanding_amount);
            if (!row.amount_to_collect || row.amount_to_collect === 0) {
                frappe.model.set_value(cdt, cdn, 'amount_to_collect', r.message.outstanding_amount);
            }

            frappe.show_alert({
                message: __('Sales Invoice data fetched: Customer={0}, Amount={1}', [r.message.customer, format_currency(r.message.outstanding_amount)]),
                indicator: 'green'
            }, 5);
        }
    });
}

function fetch_sales_order_data(frm, cdt, cdn) {
    const current = locals[cdt][cdn];
    if (!current || !current.sales_order) return;

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Sales Order',
            name: current.sales_order,
            fields: ['customer', 'company', 'transaction_date', 'advance_paid', 'grand_total', 'docstatus']
        },
        callback: function(r) {
            const row = locals[cdt][cdn];
            if (!row || !r.message) return;

            // Auto-populate customer/company if empty
            if (!frm.doc.customer) {
                frm.set_value('customer', r.message.customer);
            }
            if (!frm.doc.company) {
                frm.set_value('company', r.message.company);
            }

            // Basic validations
            if (r.message.customer !== frm.doc.customer) {
                frappe.msgprint(__('Sales Order customer does not match Customer Receipt customer'));
                frappe.model.set_value(cdt, cdn, 'sales_order', '');
                return;
            }
            if (r.message.company !== frm.doc.company) {
                frappe.msgprint(__('Sales Order company does not match Customer Receipt company'));
                frappe.model.set_value(cdt, cdn, 'sales_order', '');
                return;
            }
            if (r.message.docstatus !== 1) {
                frappe.msgprint(__('Sales Order must be submitted before linking'));
                frappe.model.set_value(cdt, cdn, 'sales_order', '');
                return;
            }

            // Compute outstanding (standard pattern for SO advance vs total)
            const outstanding = (r.message.grand_total || 0) - (r.message.advance_paid || 0);

            frappe.model.set_value(cdt, cdn, 'reference_date', r.message.transaction_date);
            frappe.model.set_value(cdt, cdn, 'reference_outstanding', outstanding);
            if (!row.amount_to_collect || row.amount_to_collect === 0) {
                frappe.model.set_value(cdt, cdn, 'amount_to_collect', outstanding);
            }

            frappe.show_alert({
                message: __('Sales Order data fetched: Customer={0}, Amount={1}', [r.message.customer, format_currency(outstanding)]),
                indicator: 'green'
            }, 5);
        }
    });
}
