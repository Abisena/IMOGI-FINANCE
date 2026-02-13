// Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
// For license information, please see license.txt

frappe.ui.form.on('VAT OUT Batch', {
	refresh: function(frm) {
		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) {
			// Draft state
			if (!frm.doc.exported_on) {
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
		
		// Clone button for cancelled batches
		if (frm.doc.docstatus === 2) {
			frm.add_custom_button(__('Clone Batch'), function() {
				clone_batch(frm);
			});
		}
		
		// Add instructions HTML
		add_instructions_html(frm);
	},
	
	onload: function(frm) {
		// Set filters for groups and invoices
		setup_filters(frm);
	}
});

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
						
						// Download file
						if (r.message.file_url) {
							window.open(r.message.file_url, '_blank');
						}
					}
				}
			});
		}
	);
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
				
				// Download file
				if (r.message.file_url) {
					window.open(r.message.file_url, '_blank');
				}
			}
		}
	});
}

function mark_upload_status(frm, status) {
	let notes = '';
	
	frappe.prompt({
		label: __('Notes'),
		fieldname: 'notes',
		fieldtype: 'Text'
	}, function(values) {
		notes = values.notes;
		
		frappe.call({
			method: 'imogi_finance.imogi_finance.doctype.vat_out_batch.vat_out_batch.mark_upload_status',
			args: {
				batch_name: frm.doc.name,
				status: status,
				notes: notes
			},
			callback: function(r) {
				if (r.message && r.message.status === 'success') {
					frappe.show_alert({
						message: __('Upload status updated'),
						indicator: 'blue'
					}, 3);
					frm.reload_doc();
				}
			}
		});
	}, __('Update Upload Status'));
}

function show_import_dialog(frm) {
	let d = new frappe.ui.Dialog({
		title: __('Import FP Numbers'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `
					<div class="alert alert-info">
						<strong>${__('Import Format:')}</strong><br>
						${__('Upload CSV/Excel with columns: Group ID, FP Number, FP Date')}<br>
						${__('Optional fallback columns: Customer NPWP, Total DPP, Total PPN')}
					</div>
				`
			},
			{
				label: __('Upload File'),
				fieldname: 'import_file',
				fieldtype: 'Attach',
				reqd: 1
			}
		],
		primary_action_label: __('Import'),
		primary_action: function(values) {
			// Parse uploaded file
			parse_import_file(frm, values.import_file, d);
		}
	});
	
	d.show();
}

function parse_import_file(frm, file_url, dialog) {
	// For simplicity, we'll require user to paste JSON data
	// In production, you'd parse CSV/Excel on server side
	
	frappe.prompt({
		label: __('Import Data (JSON)'),
		fieldname: 'import_data',
		fieldtype: 'Code',
		options: 'JSON',
		default: '[\n  {"group_id": 1, "fp_no": "0123456789012345", "fp_date": "2026-02-01"}\n]'
	}, function(values) {
		frappe.call({
			method: 'imogi_finance.vat_out_batch_api.import_fp_numbers_from_file',
			args: {
				batch_name: frm.doc.name,
				file_data: values.import_data
			},
			freeze: true,
			freeze_message: __('Importing FP numbers...'),
			callback: function(r) {
				if (r.message) {
					let msg = `${__('Success')}: ${r.message.success_count}<br>`;
					msg += `${__('Failed')}: ${r.message.failed_count}`;
					
					if (r.message.warnings && r.message.warnings.length > 0) {
						msg += '<br><br><strong>' + __('Warnings:') + '</strong><br>';
						msg += r.message.warnings.slice(0, 5).join('<br>');
						if (r.message.warnings.length > 5) {
							msg += '<br>...' + __('and {0} more', [r.message.warnings.length - 5]);
						}
					}
					
					frappe.msgprint({
						title: __('Import Summary'),
						message: msg,
						indicator: r.message.status === 'success' ? 'green' : 'orange'
					});
					
					frm.reload_doc();
					dialog.hide();
				}
			}
		});
	}, __('Paste Import Data'));
}

function show_pdf_upload_dialog(frm) {
	let d = new frappe.ui.Dialog({
		title: __('Upload Tax Invoice PDFs'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `
					<div class="alert alert-info">
						<strong>${__('PDF Filename Pattern:')}</strong><br>
						${__('FP-{16 digit number}.pdf or Group-{Group ID}.pdf')}
					</div>
				`
			},
			{
				label: __('Upload PDFs'),
				fieldname: 'pdf_files',
				fieldtype: 'Attach',
				reqd: 1
			}
		],
		primary_action_label: __('Upload'),
		primary_action: function(values) {
			// Collect file URLs
			let file_urls = [values.pdf_files];
			
			frappe.call({
				method: 'imogi_finance.vat_out_batch_api.bulk_upload_pdfs',
				args: {
					batch_name: frm.doc.name,
					pdf_files: JSON.stringify(file_urls)
				},
				freeze: true,
				freeze_message: __('Uploading PDFs...'),
				callback: function(r) {
					if (r.message) {
						frappe.msgprint({
							title: __('Upload Summary'),
							message: `${__('Uploaded')}: ${r.message.success_count}<br>${__('Failed')}: ${r.message.failed_count}`,
							indicator: r.message.status === 'success' ? 'green' : 'orange'
						});
						
						frm.reload_doc();
						d.hide();
					}
				}
			});
		}
	});
	
	d.show();
}

function clone_batch(frm) {
	frappe.confirm(
		__('Clone this cancelled batch? This will create a new batch with the same groups and invoices.'),
		function() {
			frappe.call({
				method: 'imogi_finance.imogi_finance.doctype.vat_out_batch.vat_out_batch.clone_batch',
				args: {
					source_batch_name: frm.doc.name
				},
				freeze: true,
				freeze_message: __('Cloning batch...'),
				callback: function(r) {
					if (r.message && r.message.status === 'success') {
						frappe.show_alert({
							message: __('Batch cloned successfully'),
							indicator: 'green'
						}, 5);
						
						// Navigate to new batch
						frappe.set_route('Form', 'VAT OUT Batch', r.message.new_batch);
					}
				}
			});
		}
	);
}

function add_instructions_html(frm) {
	// Add instructions for CoreTax upload process
	if (frm.doc.exported_on && frm.doc.docstatus === 0) {
		let html = `
			<div class="alert alert-info">
				<h5>📋 ${__('CoreTax DJP Upload Instructions')}</h5>
				<ol>
					<li>${__('Download the Excel template from the export file above')}</li>
					<li>${__('Open DJP Converter application')}</li>
					<li>${__('Browse and select the Excel file')}</li>
					<li>${__('Choose type: "Faktur Pajak Keluaran" (Output Tax Invoice)')}</li>
					<li>${__('Click Save to generate XML file')}</li>
					<li>${__('Login to')} <a href="https://coretax.pajak.go.id" target="_blank">coretax.pajak.go.id</a></li>
					<li>${__('Go to: Faktur Keluaran → Impor Data')}</li>
					<li>${__('Upload the XML file')}</li>
					<li>${__('Monitor progress in: XML Monitoring menu')}</li>
					<li>${__('Wait for status: "Creating Invoice Finished"')}</li>
					<li>${__('Select invoices and click "Upload Faktur"')}</li>
					<li>${__('Complete digital signature process')}</li>
					<li>${__('Mark upload status as "Completed" above')}</li>
				</ol>
				
				<h5>📥 ${__('Download FP Numbers & PDFs')}</h5>
				<ol>
					<li>${__('Login to CoreTax → e-Faktur → Pajak Keluaran')}</li>
					<li>${__('Filter by tax period (masa pajak)')}</li>
					<li>${__('Click PDF icon to download each invoice')}</li>
					<li>${__('Use "Import FP Numbers" button above to bulk import')}</li>
					<li>${__('Upload PDFs using "Upload PDFs" button')}</li>
				</ol>
			</div>
		`;
		
		// Check if instructions already added
		if (!frm.fields_dict.section_export.$wrapper.find('.coretax-instructions').length) {
			frm.fields_dict.section_export.$wrapper.prepend(
				$('<div class="coretax-instructions"></div>').html(html)
			);
		}
	}
}

function setup_filters(frm) {
	// Filter for groups - unique customers only
	frm.set_query('customer', 'groups', function() {
		let existing_customers = [];
		if (frm.doc.groups) {
			existing_customers = frm.doc.groups.map(g => g.customer).filter(Boolean);
		}
		
		return {
			filters: {
				name: ['not in', existing_customers]
			}
		};
	});
	
	// Filter for invoices - only verified, not in other batches
	frm.set_query('sales_invoice', 'invoices', function() {
		return {
			filters: {
				docstatus: 1,
				company: frm.doc.company,
				out_fp_status: 'Verified',
				out_fp_batch: ['in', ['', null, frm.doc.name]]
			}
		};
	});
}
