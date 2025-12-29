frappe.ui.form.on('Expense Request', {
  refresh(frm) {
    frm.dashboard.clear_headline();

    if (!frm.doc.docstatus) {
      return;
    }

    const isSubmitted = frm.doc.docstatus === 1;
    const allowedStatuses = ['Approved'];
    const isAllowedStatus = allowedStatuses.includes(frm.doc.status);
    const isLinked = frm.doc.status === 'Linked';
    const hasLinkedPurchaseInvoice = Boolean(frm.doc.linked_purchase_invoice);
    const canCreatePurchaseInvoice = isSubmitted && isAllowedStatus && !hasLinkedPurchaseInvoice;

    const showPurchaseInvoiceAvailability = () => {
      if (hasLinkedPurchaseInvoice) {
        frm.dashboard.set_headline(__('Purchase Invoice {0} already linked to this request.', [
          frm.doc.linked_purchase_invoice,
        ]));
        return;
      }

      if (!isAllowedStatus) {
        frappe.show_alert({
          message: __('Purchase Invoice can be created after this request is Approved.'),
          indicator: 'orange',
        });
      }
    };

    if (isSubmitted && isLinked && hasLinkedPurchaseInvoice) {
      frm.dashboard.set_headline(__('Purchase Invoice {0} already linked to this request.', [
        frm.doc.linked_purchase_invoice,
      ]));
    }

    if (isSubmitted && isAllowedStatus && !hasLinkedPurchaseInvoice) {
      frm.dashboard.set_headline(
        '<span class="indicator orange">' +
        __('Expense Request is Approved and awaiting Purchase Invoice creation.') +
        '</span>',
      );
    }

    if (canCreatePurchaseInvoice) {
      const purchaseInvoiceBtn = frm.add_custom_button(__('Create Purchase Invoice'), async () => {
        purchaseInvoiceBtn.prop('disabled', true);

        try {
          const r = await frm.call('create_purchase_invoice', {
            expense_request: frm.doc.name,
          });

          if (r && r.message) {
            frappe.msgprint({
              title: __('Purchase Invoice Created'),
              message: __('Purchase Invoice {0} created from this request.', [r.message]),
              indicator: 'green',
            });
            frm.reload_doc();
          }
        } catch (error) {
          frappe.msgprint({
            title: __('Unable to Create Purchase Invoice'),
            message: error && error.message
              ? error.message
              : __('An unexpected error occurred while creating the Purchase Invoice. Please try again.'),
            indicator: 'red',
          });
        } finally {
          purchaseInvoiceBtn.prop('disabled', false);
        }
      }, __('Create'));
    } else {
      showPurchaseInvoiceAvailability();
    }
  },
});
