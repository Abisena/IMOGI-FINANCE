// Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
// For license information, please see license.txt

frappe.ui.form.on('VAT OUT Batch', {
	refresh: function(frm) {
		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) {
			// Draft state - Get Available Invoices button
			if (!frm.doc.exported_on) {
				frm.add_custom_button(__('Get Available Invoices'), function() {
					get_available_invoices(frm);
				}).css({'background-color': '#4CAF50', 'color': 'white', 'font-weight': 'bold'});
				
				frm.add_custom_button(__('Generate CoreTax Upload File'), function() {
					generate_coretax_file(frm);
				}, __('Actions'));
			}
			
			// Upload status buttons
			if (frm.doc.exported_on) {
				frm.add_custom_button(__('Mark Upload In Progress'), function() {
					mark_upload_status(frm, 'In Progress');
				}, __('Upload Status'));
				
				frm.add_custom_button(__('Mark Upload Completed'), function() {
					mark_upload_status(frm, 'Completed');
				}, __('Upload Status'));
				
				frm.add_custom_button(__('Mark Upload Failed'), function() {
					mark_upload_status(frm, 'Failed');
				}, __('Upload Status'));
			}
			
			// Import buttons
			if (frm.doc.exported_on && !frm.is_new()) {
				frm.add_custom_button(__('Import FP Numbers'), function() {
					show_import_dialog(frm);
				}, __('Import'));
				
				frm.add_custom_button(__('Upload PDFs'), function() {
					show_pdf_upload_dialog(frm);
				}, __('Import'));
			}
		}
		
		// Reconciliation button (always available after export)
		if (frm.doc.exported_on) {
			frm.add_custom_button(__('Generate Reconciliation File'), function() {
				generate_reconciliation_file(frm);
			}, __('Actions'));
		}
		
		// View Invoices button
		if (!frm.is_new()) {
			frm.add_custom_button(__('View Batch Invoices'), function() {
				show_batch_invoices(frm);
			});
		}
		
		// Clone button for cancelled batches
		if (frm.doc.docstatus === 2) {
			frm.add_custom_button(__('Clone Batch'), function() {
				clone_batch(frm);
			});
		}
		
		// Add instructions HTML
		add_instructions_html(frm);
	}
});

function get_available_invoices(frm) {
	if (!frm.doc.company || !frm.doc.date_from || !frm.doc.date_to) {
		frappe.msgprint(__('Please set Company, Date From, and Date To first.'));
		return;
	}
	
	frappe.call({
		method: 'get_available_invoices',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Auto-grouping invoices...'),
		callback: function(r) {
			if (r.message) {
				frm.reload_doc();
				
				// Show summary dialog
				let groups = r.message.groups || [];
				let html = '<div style="margin-bottom: 15px;">';
				html += `<p><strong>Total Invoices:</strong> ${r.message.total_invoices}</p>`;
				html += `<p><strong>Total Groups:</strong> ${r.message.total_groups}</p>`;
				html += '</div>';
				
				if (groups.length > 0) {
					html += '<table class="table table-bordered table-sm">';
					html += '<thead><tr>';
					html += '<th>Group</th><th>Customer</th><th>NPWP</th><th>Invoices</th><th>DPP</th><th>PPN</th>';
					html += '</tr></thead><tbody>';
					
					groups.forEach(function(g) {
						html += '<tr>';
						html += `<td>${g.group_id}</td>`;
						html += `<td>${g.customer_name || g.customer}</td>`;
						html += `<td>${g.customer_npwp || '-'}</td>`;
						html += `<td>${g.invoice_count}</td>`;
						html += `<td>${format_currency(g.total_dpp)}</td>`;
						html += `<td>${format_currency(g.total_ppn)}</td>`;
						html += '</tr>';
					});
					
					html += '</tbody></table>';
				}
				
				frappe.msgprint({
					title: __('Invoices Grouped Successfully'),
					message: html,
					indicator: 'green'
				});
			}
		}
	});
}

function show_batch_invoices(frm) {
	frappe.route_options = {
		"out_fp_batch": frm.doc.name
	};
	frappe.set_route("List", "Sales Invoice");
}

function generate_coretax_file(frm) {
	frappe.confirm(
		__('Generate Excel file for CoreTax DJP upload? This will lock the grouping.'),
		function() {
			frappe.call({
				method: 'imogi_finance.vat_out_batch_api.generate_coretax_upload_file',
				args: {
					batch_name: frm.doc.name
				},
				freeze: true,
				freeze_message: __('Generating export file...'),
				callback: function(r) {
					if (r.message && r.message.status === 'success') {
						frappe.show_alert({
							message: __('Export file generated successfully'),
							indicator: 'green'
						}, 5);
						frm.reload_doc();
					}
				}
			});
		}
	);
}

function mark_upload_status(frm, status) {
	frm.set_value('coretax_upload_status', status);
	
	if (status === 'Completed') {
		frm.set_value('uploaded_on', frappe.datetime.now_datetime());
	}
	
	frm.save();
}

function show_import_dialog(frm) {
	let d = new frappe.ui.Dialog({
		title: __('Import FP Numbers from CoreTax'),
		fields: [
			{
				fieldname: 'fp_file',
				fieldtype: 'Attach',
				label: __('FP Numbers Excel File'),
				reqd: 1,
				description: __('Upload the Excel file downloaded from CoreTax DJP after generating FP numbers')
			},
			{
				fieldname: 'instructions',
				fieldtype: 'HTML',
				options: `
					<div class="alert alert-info" style="margin-top: 10px;">
						<strong>Instructions:</strong><br>
						1. Upload Excel file from CoreTax DJP<br>
						2. Must contain columns: Group ID, FP No Seri, FP No Faktur, FP Date<br>
						3. FP numbers will be matched by Group ID
					</div>
				`
			}
		],
		primary_action_label: __('Import'),
		primary_action: function(values) {
			frappe.call({
				method: 'imogi_finance.vat_out_batch_api.import_fp_numbers_from_file',
				args: {
					batch_name: frm.doc.name,
					file_url: values.fp_file
				},
				freeze: true,
				freeze_message: __('Importing FP numbers...'),
				callback: function(r) {
					if (r.message && r.message.status === 'success') {
						frappe.show_alert({
							message: __('FP numbers imported: {0}', [r.message.imported_count]),
							indicator: 'green'
						}, 5);
						d.hide();
						frm.reload_doc();
					}
				}
			});
		}
	});
	
	d.show();
}

function show_pdf_upload_dialog(frm) {
	let d = new frappe.ui.Dialog({
		title: __('Bulk Upload FP PDFs'),
		fields: [
			{
				fieldname: 'pdf_zip',
				fieldtype: 'Attach',
				label: __('ZIP File with FP PDFs'),
				reqd: 1,
				description: __('Upload ZIP file containing FP PDFs. Filename format: [FP Number].pdf')
			},
			{
				fieldname: 'instructions',
				fieldtype: 'HTML',
				options: `
					<div class="alert alert-info" style="margin-top: 10px;">
						<strong>Instructions:</strong><br>
						1. Download FP PDFs from CoreTax DJP<br>
						2. Create ZIP file with all PDFs<br>
						3. Filename must be: [16-digit FP Number].pdf<br>
						Example: 0109876543210001.pdf
					</div>
				`
			}
		],
		primary_action_label: __('Upload'),
		primary_action: function(values) {
			frappe.call({
				method: 'imogi_finance.vat_out_batch_api.bulk_upload_pdfs',
				args: {
					batch_name: frm.doc.name,
					zip_file_url: values.pdf_zip
				},
				freeze: true,
				freeze_message: __('Processing PDF uploads...'),
				callback: function(r) {
					if (r.message && r.message.status === 'success') {
						frappe.show_alert({
							message: __('PDFs uploaded: {0}', [r.message.uploaded_count]),
							indicator: 'green'
						}, 5);
						d.hide();
						frm.reload_doc();
					}
				}
			});
		}
	});
	
	d.show();
}

function generate_reconciliation_file(frm) {
	frappe.call({
		method: 'imogi_finance.vat_out_batch_api.generate_reconciliation_file',
		args: {
			batch_name: frm.doc.name
		},
		freeze: true,
		freeze_message: __('Generating reconciliation file...'),
		callback: function(r) {
			if (r.message && r.message.status === 'success') {
				frappe.show_alert({
					message: __('Reconciliation file generated'),
					indicator: 'green'
				}, 5);
				frm.reload_doc();
			}
		}
	});
}

function clone_batch(frm) {
	frappe.model.with_doctype('VAT OUT Batch', function() {
		let new_doc = frappe.model.copy_doc(frm.doc);
		new_doc.docstatus = 0;
		new_doc.status = 'Draft';
		new_doc.exported_on = null;
		new_doc.coretax_export_file = null;
		new_doc.reconciliation_file = null;
		new_doc.coretax_upload_status = 'Not Started';
		new_doc.uploaded_on = null;
		new_doc.submit_on = null;
		
		frappe.set_route('Form', 'VAT OUT Batch', new_doc.name);
	});
}

function add_instructions_html(frm) {
	if (frm.doc.docstatus === 0 && !frm.doc.exported_on) {
		frm.dashboard.add_comment(`
			<div class="alert alert-info">
				<strong>Workflow:</strong><br>
				1. Set date range and save<br>
				2. Click <strong>"Get Available Invoices"</strong> to auto-group<br>
				3. Generate CoreTax upload file<br>
				4. Upload to CoreTax DJP manually<br>
				5. Import FP numbers back<br>
				6. Submit batch
			</div>
		`, 'blue', true);
	}
	
	if (frm.doc.exported_on && frm.doc.docstatus === 0) {
		frm.dashboard.add_comment(`
			<div class="alert alert-warning">
				<strong>Next Steps:</strong><br>
				1. Upload Excel file to <a href="https://coretax.pajak.go.id" target="_blank">CoreTax DJP</a><br>
				2. Generate FP numbers in CoreTax<br>
				3. Download result Excel from CoreTax<br>
				4. Click <strong>"Import FP Numbers"</strong> to import back<br>
				5. Verify all invoices have FP numbers<br>
				6. Submit batch to finalize
			</div>
		`, 'orange', true);
	}
}

function format_currency(value) {
	return frappe.format(value, {fieldtype: 'Currency'});
}
