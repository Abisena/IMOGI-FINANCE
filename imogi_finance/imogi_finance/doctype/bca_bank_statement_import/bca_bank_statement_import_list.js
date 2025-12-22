frappe.listview_settings['BCA Bank Statement Import'] = {
  add_fields: ['imported_on', 'company', 'bank_account', 'import_status', 'hash_id'],
  refresh(listview) {
    const hasImportedOn = listview.columns.some(({ fieldname }) => fieldname === 'imported_on');

    if (!hasImportedOn) {
      listview.columns.splice(1, 0, {
        type: 'Datetime',
        fieldname: 'imported_on',
        label: __('Imported On'),
        width: '12rem',
      });
    }
  },
};
