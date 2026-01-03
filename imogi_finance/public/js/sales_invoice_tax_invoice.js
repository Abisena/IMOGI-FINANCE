frappe.require('/assets/imogi_finance/js/tax_invoice_fields.js');

const SI_TAX_INVOICE_FIELDS = (imogi_finance?.tax_invoice?.getFieldMap && imogi_finance.tax_invoice.getFieldMap('Sales Invoice')) || {
  fp_no: 'out_fp_no',
  fp_date: 'out_fp_date',
  npwp: 'out_buyer_tax_id',
  dpp: 'out_fp_dpp',
  ppn: 'out_fp_ppn',
  ppn_type: 'out_fp_ppn_type',
  verification_status: 'out_fp_status',
  verification_notes: 'out_fp_verification_notes',
  duplicate_flag: 'out_fp_duplicate_flag',
  npwp_match: 'out_fp_npwp_match',
};

async function syncSiUpload(frm) {
  if (!frm.doc.out_fp_tax_invoice_upload) {
    return;
  }
  const upload = await frappe.db.get_doc('Tax Invoice OCR Upload', frm.doc.out_fp_tax_invoice_upload);
  const updates = {};
  Object.entries(SI_TAX_INVOICE_FIELDS).forEach(([source, target]) => {
    updates[target] = upload[source] || null;
  });
  await frm.set_value(updates);
}

function lockSiTaxInvoiceFields(frm) {
  Object.values(SI_TAX_INVOICE_FIELDS).forEach((field) => {
    frm.set_df_property(field, 'read_only', true);
  });
}

function setSiUploadQuery(frm) {
  frm.set_query('out_fp_tax_invoice_upload', () => ({
    filters: {
      verification_status: 'Verified',
    },
  }));
}

frappe.ui.form.on('Sales Invoice', {
  async refresh(frm) {
    lockSiTaxInvoiceFields(frm);
    setSiUploadQuery(frm);
    await syncSiUpload(frm);

    const ensureSettings = async () => {
      const enabled = await frappe.db.get_single_value('Tax Invoice OCR Settings', 'enable_tax_invoice_ocr');
      return Boolean(enabled);
    };

    const addOcrButton = async () => {
      const enabled = await ensureSettings();
      if (!enabled || !frm.doc.out_fp_tax_invoice_upload || frm.doc.docstatus === 1) {
        return;
      }

      frm.add_custom_button(__('Run OCR'), async () => {
        await frappe.call({
          method: 'imogi_finance.api.tax_invoice.run_ocr_for_upload',
          args: { upload_name: frm.doc.out_fp_tax_invoice_upload },
          freeze: true,
          freeze_message: __('Queueing OCR...'),
        });
        frappe.show_alert({ message: __('OCR queued.'), indicator: 'green' });
        await syncSiUpload(frm);
      }, __('Tax Invoice'));
    };

    const addUploadButtons = () => {
      if (!frm.doc.out_fp_tax_invoice_upload) {
        return;
      }

      frm.add_custom_button(__('Open Tax Invoice Upload'), () => {
        frappe.set_route('Form', 'Tax Invoice OCR Upload', frm.doc.out_fp_tax_invoice_upload);
      }, __('Tax Invoice'));

      frm.add_custom_button(__('Refresh Tax Invoice Data'), async () => {
        await frappe.call({
          method: 'imogi_finance.api.tax_invoice.apply_tax_invoice_upload',
          args: { target_doctype: 'Sales Invoice', target_name: frm.doc.name },
          freeze: true,
          freeze_message: __('Refreshing...'),
        });
        await frm.reload_doc();
      }, __('Tax Invoice'));
    };

    addOcrButton();
    addUploadButtons();
  },

  async out_fp_tax_invoice_upload(frm) {
    await syncSiUpload(frm);
  },
});
