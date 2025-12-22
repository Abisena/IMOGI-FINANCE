const ensureImportedOnColumn = (listview) => {
  if (!listview || !Array.isArray(listview.columns) || !listview.columns.length) return;

  const existingIndex = listview.columns.findIndex(
    ({ fieldname, id }) => fieldname === 'imported_on' || id === 'imported_on',
  );

  const importedOnColumn =
    existingIndex > -1
      ? listview.columns.splice(existingIndex, 1)[0]
      : {
          id: 'imported_on',
          fieldname: 'imported_on',
          label: __('Imported On'),
          fieldtype: 'Datetime',
          width: 180,
        };

  listview.columns.splice(1, 0, importedOnColumn);
  listview.datatable?.setColumns(listview.columns);
  listview.datatable?.refresh(listview.data);
};

frappe.listview_settings['BCA Bank Statement Import'] = {
  add_fields: ['imported_on', 'company', 'bank_account', 'import_status', 'hash_id'],
  onload(listview) {
    ensureImportedOnColumn(listview);
  },
  refresh(listview) {
    ensureImportedOnColumn(listview);
  },
};
