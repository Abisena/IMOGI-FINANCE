(() => {
  const STANDARD_FIELD_MAP = {
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

  const FIELD_MAPS = {
    'Branch Expense Request': STANDARD_FIELD_MAP,
    'Expense Request': STANDARD_FIELD_MAP,
    'Purchase Invoice': STANDARD_FIELD_MAP,
    'Sales Invoice': {
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
    },
  };

  frappe.provide('imogi_finance.tax_invoice');

  imogi_finance.tax_invoice.getFieldMap = (doctype) => {
    const mapping = FIELD_MAPS[doctype] || STANDARD_FIELD_MAP;
    return { ...mapping };
  };
})();
