frappe.ui.form.on('Transfer Application Item', {
  party(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    
    if (!row.party || !row.party_type) {
      return;
    }
    
    // Fetch party details based on party type
    if (row.party_type === 'Supplier') {
      fetch_supplier_details(frm, row);
    } else if (row.party_type === 'Employee') {
      fetch_employee_details(frm, row);
    }
  },
  
  party_type(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    // Clear party when party type changes
    frappe.model.set_value(cdt, cdn, 'party', '');
  }
});

function fetch_supplier_details(frm, row) {
  frappe.call({
    method: 'frappe.client.get',
    args: {
      doctype: 'Supplier',
      name: row.party
    },
    callback: (r) => {
      if (r.message) {
        let supplier = r.message;
        
        // Try to get bank details from first bank account
        frappe.call({
          method: 'frappe.client.get_list',
          args: {
            doctype: 'Bank Account',
            filters: {
              party_type: 'Supplier',
              party: row.party,
              is_default: 1
            },
            fields: ['bank', 'bank_account_no', 'branch_code', 'account_name'],
            limit: 1
          },
          callback: (bank_res) => {
            if (bank_res.message && bank_res.message.length > 0) {
              let bank = bank_res.message[0];
              frappe.model.set_value(row.doctype, row.name, 'beneficiary_name', supplier.supplier_name || row.party);
              frappe.model.set_value(row.doctype, row.name, 'bank_name', bank.bank || '');
              frappe.model.set_value(row.doctype, row.name, 'account_number', bank.bank_account_no || '');
              frappe.model.set_value(row.doctype, row.name, 'account_holder_name', bank.account_name || '');
              frappe.model.set_value(row.doctype, row.name, 'bank_branch', bank.branch_code || '');
            } else {
              // No bank account, just set beneficiary name
              frappe.model.set_value(row.doctype, row.name, 'beneficiary_name', supplier.supplier_name || row.party);
            }
          }
        });
      }
    }
  });
}

function fetch_employee_details(frm, row) {
  frappe.call({
    method: 'frappe.client.get',
    args: {
      doctype: 'Employee',
      name: row.party
    },
    callback: (r) => {
      if (r.message) {
        let employee = r.message;
        
        // Try to get bank details
        frappe.call({
          method: 'frappe.client.get_list',
          args: {
            doctype: 'Bank Account',
            filters: {
              party_type: 'Employee',
              party: row.party
            },
            fields: ['bank', 'bank_account_no', 'branch_code', 'account_name'],
            limit: 1
          },
          callback: (bank_res) => {
            if (bank_res.message && bank_res.message.length > 0) {
              let bank = bank_res.message[0];
              frappe.model.set_value(row.doctype, row.name, 'beneficiary_name', employee.employee_name || row.party);
              frappe.model.set_value(row.doctype, row.name, 'bank_name', bank.bank || '');
              frappe.model.set_value(row.doctype, row.name, 'account_number', bank.bank_account_no || '');
              frappe.model.set_value(row.doctype, row.name, 'account_holder_name', bank.account_name || '');
              frappe.model.set_value(row.doctype, row.name, 'bank_branch', bank.branch_code || '');
            } else {
              // No bank account, just set beneficiary name
              frappe.model.set_value(row.doctype, row.name, 'beneficiary_name', employee.employee_name || row.party);
            }
          }
        });
      }
    }
  });
}
