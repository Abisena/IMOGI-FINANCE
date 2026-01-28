/**
 * UI Integration untuk manual amortization trigger
 *
 * Add ke Purchase Invoice doktype custom script
 * Location: Customization → Custom Script
 */

// Purchase Invoice - Custom Script
frappe.ui.form.on('Purchase Invoice', {
    refresh(frm) {
        // Add button untuk generate amortization jika ada deferred items
        if (frm.doc.docstatus === 1) {  // Only untuk submitted docs
            const has_deferred = frm.doc.items.some(item => item.enable_deferred_expense);

            if (has_deferred) {
                frm.add_custom_button(__('Generate Amortization'), function() {
                    frappe.call({
                        method: 'imogi_finance.services.amortization_processor.create_amortization_schedule_for_pi',
                        args: {
                            pi_name: frm.doc.name
                        },
                        btn: frm.page.btn_primary,
                        callback: function(r) {
                            if (r.message) {
                                let result = r.message;
                                frappe.msgprint({
                                    title: __('Amortization Created'),
                                    message: `
                                        <div class="frappe-control">
                                            <table class="table table-bordered">
                                                <tr>
                                                    <td>Total Schedules</td>
                                                    <td><strong>${result.total_schedules}</strong></td>
                                                </tr>
                                                <tr>
                                                    <td>Total Amount</td>
                                                    <td><strong>${frappe.utils.format_currency(result.total_amount, frm.doc.currency)}</strong></td>
                                                </tr>
                                                <tr>
                                                    <td>Journal Entries Created</td>
                                                    <td><strong>${result.journal_entries.length}</strong></td>
                                                </tr>
                                            </table>
                                            <h5>Journal Entries:</h5>
                                            <ul>
                                                ${result.journal_entries.map(je =>
                                                    `<li><a href="/app/journal-entry/${je}">${je}</a></li>`
                                                ).join('')}
                                            </ul>
                                        </div>
                                    `,
                                    indicator: 'green'
                                });

                                // Reload form
                                frm.reload_doc();
                            }
                        }
                    });
                }, 'btn-primary');

                frm.add_custom_button(__('View Schedule'), function() {
                    frappe.call({
                        method: 'imogi_finance.services.amortization_processor.get_amortization_schedule',
                        args: {
                            pi_name: frm.doc.name
                        },
                        callback: function(r) {
                            if (r.message) {
                                let schedule = r.message.schedule;

                                let html = `
                                    <div class="frappe-control">
                                        <h4>Amortization Schedule: ${r.message.pi}</h4>
                                        <p><strong>Total Deferred:</strong> ${frappe.utils.format_currency(r.message.total_deferred, 'IDR')}</p>
                                        <p><strong>Total Periods:</strong> ${r.message.total_periods}</p>
                                        <table class="table table-bordered table-striped" style="font-size: 12px;">
                                            <thead>
                                                <tr>
                                                    <th>Period</th>
                                                    <th>Bulan</th>
                                                    <th>Posting Date</th>
                                                    <th>Amount</th>
                                                    <th>Item Code</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                `;

                                schedule.forEach(row => {
                                    html += `
                                        <tr>
                                            <td>${row.period}</td>
                                            <td>${row.bulan}</td>
                                            <td>${row.posting_date}</td>
                                            <td style="text-align: right;">${frappe.utils.format_currency(row.amount, 'IDR')}</td>
                                            <td>${row.item_code}</td>
                                        </tr>
                                    `;
                                });

                                html += `
                                            </tbody>
                                        </table>
                                    </div>
                                `;

                                let d = new frappe.ui.Dialog({
                                    title: 'Amortization Schedule Breakdown',
                                    size: 'large',
                                    fields: [
                                        {
                                            fieldname: 'schedule_html',
                                            fieldtype: 'HTML'
                                        }
                                    ]
                                });

                                d.fields_dict.schedule_html.$wrapper.html(html);
                                d.show();
                            }
                        }
                    });
                }, 'btn-default');
            }
        }
    }
});


/**
 * OPTIONAL: List View Settings untuk Purchase Invoice
 * Menambahkan badge "Deferred" untuk PI yang punya deferred items
 */

frappe.listview_settings['Purchase Invoice'] = {
    collapses: {
        'deferred_status': true
    },
    formatters: {
        'name': function(value, df, data) {
            let has_deferred = false;
            if (data && data.enable_deferred_expense) {
                has_deferred = true;
            }

            let html = `<a href="/app/purchase-invoice/${value}">${value}</a>`;
            if (has_deferred) {
                html += ` <span class="badge badge-warning">Deferred</span>`;
            }
            return html;
        }
    },
    add_fields: ['enable_deferred_expense', 'docstatus']
};
