/**
 * Payment Entry UI Enhancements
 * - Reverse Entry button for reversing payment entries included in printed reports
 * - Status indicators for reversed/reversal entries
 */

frappe.ui.form.on('Payment Entry', {
  refresh(frm) {
    // Show Reverse Entry button if PE is submitted and not already reversed
    if (frm.doc.docstatus === 1 && !frm.doc.is_reversed) {
      frm.add_custom_button(__('Reverse Entry'), () => {
        const d = new frappe.ui.Dialog({
          title: __('Reverse Payment Entry'),
          fields: [
            {
              label: __('Reversal Date'),
              fieldname: 'reversal_date',
              fieldtype: 'Date',
              default: frappe.datetime.get_today(),
              reqd: 1,
              description: __('The posting date for the reversal entry (typically today)')
            },
            {
              fieldtype: 'HTML',
              options: `
                <div class="alert alert-info" style="margin-top: 10px;">
                  <strong>${__('Note:')}</strong><br>
                  ${__('This creates a reversal entry with flipped accounts at the selected date.')}<br>
                  ${__('Use this when the original entry is included in a printed Cash/Bank Daily Report.')}
                </div>
              `
            }
          ],
          primary_action_label: __('Create Reversal'),
          primary_action(values) {
            d.hide();
            
            frappe.call({
              method: 'imogi_finance.events.payment_entry.reverse_payment_entry',
              args: {
                payment_entry_name: frm.doc.name,
                reversal_date: values.reversal_date
              },
              freeze: true,
              freeze_message: __('Creating reversal entry...'),
              callback: (r) => {
                if (r.message) {
                  frappe.show_alert({
                    message: __('Reversal Entry {0} created', [r.message.name]),
                    indicator: 'green'
                  });
                  frm.reload_doc().then(() => {
                    frappe.set_route('Form', 'Payment Entry', r.message.name);
                  });
                }
              },
              error: (r) => {
                frappe.msgprint({
                  title: __('Error Creating Reversal'),
                  indicator: 'red',
                  message: r.message || __('An error occurred while creating the reversal entry')
                });
              }
            });
          }
        });
        d.show();
      }, __('Actions'));
    }
    
    // Show indicator if this entry has been reversed
    if (frm.doc.is_reversed && frm.doc.reversal_entry) {
      frm.dashboard.add_indicator(
        __('Reversed by {0}', [frm.doc.reversal_entry]),
        'orange'
      );
      
      // Add button to view reversal entry
      frm.add_custom_button(__('View Reversal Entry'), () => {
        frappe.set_route('Form', 'Payment Entry', frm.doc.reversal_entry);
      }, __('Actions'));
    }
    
    // Show indicator if this is a reversal entry
    if (frm.doc.is_reversal && frm.doc.reversed_entry) {
      frm.dashboard.add_indicator(
        __('Reversal of {0}', [frm.doc.reversed_entry]),
        'blue'
      );
      
      // Add button to view original entry
      frm.add_custom_button(__('View Original Entry'), () => {
        frappe.set_route('Form', 'Payment Entry', frm.doc.reversed_entry);
      }, __('Actions'));
    }
  }
});
