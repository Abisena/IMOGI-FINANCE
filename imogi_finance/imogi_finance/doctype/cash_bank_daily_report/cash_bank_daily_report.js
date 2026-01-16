frappe.ui.form.on('Cash Bank Daily Report', {
  refresh(frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__('Regenerate Snapshot'), () => {
        frappe.call({
          method: 'imogi_finance.imogi_finance.doctype.cash_bank_daily_report.cash_bank_daily_report.regenerate',
          args: { name: frm.doc.name },
          freeze: true,
          freeze_message: __('Regenerating daily report...'),
          callback(r) {
            if (r.message) {
              frm.set_value('snapshot_json', r.message.snapshot_json);
              frm.set_value('status', r.message.status);
              frm.set_value('opening_balance', r.message.opening_balance);
              frm.set_value('inflow', r.message.inflow);
              frm.set_value('outflow', r.message.outflow);
              frm.set_value('closing_balance', r.message.closing_balance);
            }
            frm.reload_doc();
          },
        });
      });
    }

    // Show mode indicator
    show_report_mode_indicator(frm);

    // Render read-only preview from snapshot_json
    render_daily_report_preview(frm);
  },
  bank_account(frm) {
    if (frm.doc.bank_account && frm.doc.cash_account) {
      frm.set_value('cash_account', null);
    }
    show_report_mode_indicator(frm);
  },
  cash_account(frm) {
    if (frm.doc.cash_account && frm.doc.bank_account) {
      frm.set_value('bank_account', null);
    }
    show_report_mode_indicator(frm);
  },
});

function show_report_mode_indicator(frm) {
  if (!frm.dashboard) return;
  
  frm.dashboard.clear_headline();
  
  if (frm.doc.cash_account) {
    frm.dashboard.set_headline_alert(
      __('Mode: GL Entry (Cash Ledger)') + ' — ' + 
      __('Fetching transactions directly from General Ledger'),
      'blue'
    );
  } else if (frm.doc.bank_account) {
    frm.dashboard.set_headline_alert(
      __('Mode: Bank Transaction') + ' — ' + 
      __('Fetching from imported bank statement records'),
      'green'
    );
  } else {
    frm.dashboard.set_headline_alert(
      __('Please select either Bank Account or Cash Account to generate the report'),
      'orange'
    );
  }
}

function render_daily_report_preview(frm) {
  const wrapper = frm.fields_dict.preview_html && frm.fields_dict.preview_html.$wrapper;
  if (!wrapper) return;

  let data;
  try {
    data = frm.doc.snapshot_json ? JSON.parse(frm.doc.snapshot_json) : null;
  } catch (e) {
    wrapper.html('<div class="alert alert-warning"><i class="fa fa-exclamation-triangle"></i> Snapshot JSON is invalid.</div>');
    return;
  }

  if (!data) {
    wrapper.html('<div class="alert alert-info"><i class="fa fa-info-circle"></i> No snapshot available. Save the document to generate the daily report.</div>');
    return;
  }

  const consolidated = data.consolidated || {};
  const branches = data.branches || [];

  let html = '';
  
  // Modern Summary Cards
  html += '<style>';
  html += '.report-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }';
  html += '.report-card h3 { margin: 0 0 15px 0; font-size: 16px; font-weight: 600; opacity: 0.9; }';
  html += '.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }';
  html += '.summary-box { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 4px solid #667eea; }';
  html += '.summary-box.opening { border-left-color: #3b82f6; }';
  html += '.summary-box.inflow { border-left-color: #10b981; }';
  html += '.summary-box.outflow { border-left-color: #ef4444; }';
  html += '.summary-box.closing { border-left-color: #8b5cf6; }';
  html += '.summary-label { font-size: 11px; color: #6b7280; text-transform: uppercase; font-weight: 600; margin-bottom: 8px; }';
  html += '.summary-value { font-size: 20px; font-weight: 700; color: #1f2937; }';
  html += '.branch-section { background: white; border-radius: 8px; padding: 16px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }';
  html += '.branch-header { display: flex; justify-content: space-between; align-items: center; cursor: pointer; padding: 8px 0; border-bottom: 2px solid #e5e7eb; margin-bottom: 12px; }';
  html += '.branch-header:hover { background: #f9fafb; margin: 0 -8px 12px -8px; padding: 8px; border-radius: 4px; }';
  html += '.branch-name { font-size: 14px; font-weight: 600; color: #111827; }';
  html += '.branch-summary { font-size: 12px; color: #6b7280; }';
  html += '.branch-details { display: none; }';
  html += '.branch-details.show { display: block; }';
  html += '.tx-badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }';
  html += '.tx-badge.in { background: #d1fae5; color: #065f46; }';
  html += '.tx-badge.out { background: #fee2e2; color: #991b1b; }';
  html += '.tx-table { width: 100%; border-collapse: collapse; }';
  html += '.tx-table th { background: #f3f4f6; padding: 10px; text-align: left; font-size: 11px; color: #374151; font-weight: 600; border-bottom: 2px solid #e5e7eb; }';
  html += '.tx-table td { padding: 10px; border-bottom: 1px solid #f3f4f6; font-size: 13px; color: #1f2937; }';
  html += '.tx-table tr:hover { background: #f9fafb; }';
  html += '.toggle-icon { transition: transform 0.3s; font-size: 14px; color: #9ca3af; }';
  html += '.toggle-icon.rotate { transform: rotate(180deg); }';
  html += '.no-data { text-align: center; padding: 30px; color: #9ca3af; font-size: 13px; }';
  html += '</style>';

  // Summary Cards with modern design
  html += '<div class="summary-grid">';
  html += '<div class="summary-box opening">';
  html += '<div class="summary-label"><i class="fa fa-calendar-check-o"></i> Opening Balance</div>';
  html += `<div class="summary-value">${format_currency(consolidated.opening_balance || 0)}</div>`;
  html += '</div>';
  html += '<div class="summary-box inflow">';
  html += '<div class="summary-label"><i class="fa fa-arrow-down"></i> Inflow</div>';
  html += `<div class="summary-value">${format_currency(consolidated.inflow || 0)}</div>`;
  html += '</div>';
  html += '<div class="summary-box outflow">';
  html += '<div class="summary-label"><i class="fa fa-arrow-up"></i> Outflow</div>';
  html += `<div class="summary-value">${format_currency(consolidated.outflow || 0)}</div>`;
  html += '</div>';
  html += '<div class="summary-box closing">';
  html += '<div class="summary-label"><i class="fa fa-check-circle"></i> Closing Balance</div>';
  html += `<div class="summary-value">${format_currency(consolidated.closing_balance || 0)}</div>`;
  html += '</div>';
  html += '</div>';

  // Branch sections with collapsible details
  if (branches.length > 0) {
    branches.forEach((br, idx) => {
      const txs = br.transactions || [];
      const branchId = `branch-${idx}`;
      
      html += '<div class="branch-section">';
      html += `<div class="branch-header" onclick="toggleBranchDetails('${branchId}')">`;
      html += '<div>';
      html += `<div class="branch-name"><i class="fa fa-building-o"></i> ${frappe.utils.escape_html(br.branch || 'Unknown Branch')}</div>`;
      html += `<div class="branch-summary">${txs.length} transaction(s) · Closing: ${format_currency(br.closing_balance || 0)}</div>`;
      html += '</div>';
      html += `<i class="fa fa-chevron-down toggle-icon" id="icon-${branchId}"></i>`;
      html += '</div>';
      
      html += `<div class="branch-details" id="${branchId}">`;
      
      if (!txs.length) {
        html += '<div class="no-data"><i class="fa fa-inbox"></i><br>No transactions for this branch</div>';
      } else {
        html += '<table class="tx-table">';
        html += '<thead><tr>';
        html += '<th style="width:15%">Date</th>';
        html += '<th style="width:40%">Reference</th>';
        html += '<th style="width:15%" class="text-center">Direction</th>';
        html += '<th style="width:30%" class="text-right">Amount</th>';
        html += '</tr></thead><tbody>';
        
        txs.forEach((tx) => {
          const date = tx.posting_date ? frappe.datetime.str_to_user(tx.posting_date) : '';
          const ref = frappe.utils.escape_html(tx.reference || '');
          const direction = (tx.direction || '').toLowerCase();
          const directionBadge = direction === 'in' 
            ? '<span class="tx-badge in"><i class="fa fa-arrow-down"></i> IN</span>' 
            : '<span class="tx-badge out"><i class="fa fa-arrow-up"></i> OUT</span>';
          const amount = format_currency(tx.amount || 0);
          
          html += '<tr>';
          html += `<td>${date}</td>`;
          html += `<td>${ref}</td>`;
          html += `<td class="text-center">${directionBadge}</td>`;
          html += `<td class="text-right"><strong>${amount}</strong></td>`;
          html += '</tr>';
        });
        
        html += '</tbody></table>';
      }
      
      html += '</div>';
      html += '</div>';
    });
  } else {
    html += '<div class="no-data"><i class="fa fa-building-o" style="font-size:24px;margin-bottom:10px;"></i><br>No branch data available</div>';
  }

  wrapper.html(html);
  
  // Add toggle function to window scope
  window.toggleBranchDetails = function(branchId) {
    const details = document.getElementById(branchId);
    const icon = document.getElementById(`icon-${branchId}`);
    if (details && icon) {
      details.classList.toggle('show');
      icon.classList.toggle('rotate');
    }
  };
}

function format_currency(value) {
  try {
    return frappe.format(value, { fieldtype: 'Currency' });
  } catch (e) {
    return (value || 0).toString();
  }
}
