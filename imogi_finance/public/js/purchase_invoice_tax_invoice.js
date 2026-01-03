frappe.require('/assets/imogi_finance/js/tax_invoice_fields.js');

const PI_TAX_INVOICE_FIELDS = (imogi_finance?.tax_invoice?.getFieldMap && imogi_finance.tax_invoice.getFieldMap('Purchase Invoice')) || {
  fp_no: 'ti_fp_no',
  fp_date: 'ti_fp_date',
  npwp: 'ti_fp_npwp',
  dpp: 'ti_fp_dpp',
  ppn: 'ti_fp_ppn',
  ppnbm: 'ti_fp_ppnbm',
  ppn_type: 'ti_fp_ppn_type',
  verification_status: 'ti_verification_status',
  verification_notes: 'ti_verification_notes',
  duplicate_flag: 'ti_duplicate_flag',
  npwp_match: 'ti_npwp_match',
};

async function syncPiUpload(frm) {
  if (!frm.doc.ti_tax_invoice_upload) {
    return;
  }

  const cachedUpload = frm.taxInvoiceUploadCache?.[frm.doc.ti_tax_invoice_upload];
  const upload = cachedUpload || await frappe.db.get_doc('Tax Invoice OCR Upload', frm.doc.ti_tax_invoice_upload);
  const updates = {};

  Object.entries(PI_TAX_INVOICE_FIELDS).forEach(([source, target]) => {
    updates[target] = upload[source] ?? null;
  });

  await frm.set_value(updates);
}

function lockPiTaxInvoiceFields(frm) {
  Object.values(PI_TAX_INVOICE_FIELDS).forEach((field) => {
    frm.set_df_property(field, 'read_only', true);
  });
}

async function setPiUploadQuery(frm) {
  let usedUploads = [];
  let verifiedUploads = [];

  try {
    const { message } = await frappe.call({
      method: 'imogi_finance.api.tax_invoice.get_tax_invoice_upload_context_api',
      args: { target_doctype: 'Purchase Invoice', target_name: frm.doc.name },
    });
    usedUploads = message?.used_uploads || [];
    verifiedUploads = message?.verified_uploads || [];
  } catch (error) {
    console.error('Unable to load available Tax Invoice uploads', error);
  }

  frm.taxInvoiceUploadCache = (verifiedUploads || []).reduce((acc, upload) => {
    acc[upload.name] = upload;
    return acc;
  }, {});

  frm.set_query('ti_tax_invoice_upload', () => ({
    filters: {
      verification_status: 'Verified',
      ...(usedUploads.length ? { name: ['not in', usedUploads] } : {}),
    },
  }));
}

frappe.ui.form.on('Purchase Invoice', {
  async refresh(frm) {
    lockPiTaxInvoiceFields(frm);
    await setPiUploadQuery(frm);

    const addOcrButton = async () => {
      const enabled = await frappe.db.get_single_value('Tax Invoice OCR Settings', 'enable_tax_invoice_ocr');
      if (!enabled || !frm.doc.ti_tax_invoice_upload || frm.doc.docstatus === 1) {
        return;
      }

      frm.add_custom_button(__('Run OCR'), async () => {
        await frappe.call({
          method: 'imogi_finance.api.tax_invoice.run_ocr_for_upload',
          args: { upload_name: frm.doc.ti_tax_invoice_upload },
          freeze: true,
          freeze_message: __('Queueing OCR...'),
        });
        frappe.show_alert({ message: __('OCR queued.'), indicator: 'green' });
        await syncPiUpload(frm);
      }, __('Tax Invoice'));
    };

    const addOpenButton = () => {
      if (!frm.doc.ti_tax_invoice_upload) {
        return;
      }
      frm.add_custom_button(__('Open Tax Invoice Upload'), () => {
        frappe.set_route('Form', 'Tax Invoice OCR Upload', frm.doc.ti_tax_invoice_upload);
      }, __('Tax Invoice'));
    };

    await syncPiUpload(frm);
    addOcrButton();
    addOpenButton();
  },

  async ti_tax_invoice_upload(frm) {
    await syncPiUpload(frm);
  },
});
