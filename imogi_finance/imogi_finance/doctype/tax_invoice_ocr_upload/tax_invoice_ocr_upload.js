frappe.ui.form.on('Tax Invoice OCR Upload', {
  refresh(frm) {
    const addOcrButton = async () => {
      const enabled = await frappe.db.get_single_value('Tax Invoice OCR Settings', 'enable_tax_invoice_ocr');
      if (!enabled || !frm.doc.name || frm.doc.__islocal || !frm.doc.tax_invoice_pdf) {
        return;
      }

      frm.add_custom_button(__('Run OCR'), async () => {
        await frappe.call({
          method: 'imogi_finance.api.tax_invoice.run_ocr_for_upload',
          args: { upload_name: frm.doc.name },
          freeze: true,
          freeze_message: __('Queueing OCR...'),
        });
        frappe.show_alert({ message: __('OCR queued.'), indicator: 'green' });
        frm.reload_doc();
      }, __('Tax Invoice'));
    };

    const addVerifyButton = () => {
      if (frm.doc.__islocal) {
        return;
      }

      frm.add_custom_button(__('Verify Tax Invoice'), async () => {
        const r = await frappe.call({
          method: 'imogi_finance.api.tax_invoice.verify_tax_invoice_upload',
          args: { upload_name: frm.doc.name },
          freeze: true,
          freeze_message: __('Verifying...'),
        });
        if (r && r.message) {
          frappe.show_alert({ message: __('Verification status: {0}', [r.message.status]), indicator: 'green' });
          frm.reload_doc();
        }
      }, __('Tax Invoice'));
    };

    addOcrButton();
    addVerifyButton();
  },
});
