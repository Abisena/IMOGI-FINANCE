const TAX_INVOICE_OCR_GROUP = __('Tax Invoice OCR');

async function refreshUploadStatus(frm) {
	if (frm.is_new()) return;

	const callMonitor = () =>
		frappe.call({
			method: 'imogi_finance.api.tax_invoice.monitor_tax_invoice_ocr',
			args: { docname: frm.doc.name, doctype: 'Tax Invoice OCR Upload' },
		});

	const isTimestampMismatch = (error) => {
		const excType = error?.exc_type || error?.exc?.exc_type;
		const exceptionText = error?.exception || error?.exc;
		return (
			excType === 'TimestampMismatchError' ||
			(typeof exceptionText === 'string' && exceptionText.includes('TimestampMismatchError'))
		);
	};

	try {
		await callMonitor();
	} catch (error) {
		if (!isTimestampMismatch(error)) throw error;
		await frm.reload_doc();
		await callMonitor();
	}
	await frm.reload_doc();
}

frappe.ui.form.on('Tax Invoice OCR Upload', {
	async refresh(frm) {
		// Hide debug columns in child table
		if (frm.fields_dict.items && frm.fields_dict.items.grid) {
			const debugColumns = [
				'raw_harga_jual', 'raw_dpp', 'raw_ppn',
				'col_x_harga_jual', 'col_x_dpp', 'col_x_ppn', 'row_y'
			];
			debugColumns.forEach(field => {
				frm.fields_dict.items.grid.update_docfield_property(field, 'hidden', 1);
			});
		}
		
		let providerReady = true;
		let providerError = null;
		let enabled = false;

		try {
			const { message } = await frappe.call({
				method: 'imogi_finance.api.tax_invoice.get_tax_invoice_upload_context_api',
				args: { target_doctype: 'Tax Invoice OCR Upload', target_name: frm.doc.name },
			});
			enabled = Boolean(message?.enable_tax_invoice_ocr);
			providerReady = Boolean(message?.provider_ready ?? true);
			providerError = message?.provider_error || null;
		} catch (error) {
			enabled = await frappe.db.get_single_value('Tax Invoice OCR Settings', 'enable_tax_invoice_ocr');
		}

		if (!enabled || frm.is_new()) {
			return;
		}

		if (providerReady === false) {
			const message = providerError
				? __('OCR cannot run: {0}', [providerError])
				: __('OCR provider is not configured.');
			frm.dashboard.set_headline(`<span class="indicator red">${message}</span>`);
		}

		// 🔥 Show OCR failure error prominently
		if (frm.doc.ocr_status === 'Failed' && frm.doc.notes) {
			frm.dashboard.set_headline_alert(
				__('❌ OCR Failed: {0}', [frm.doc.notes]),
				'red'
			);
		}

		frm.add_custom_button(__('Refresh OCR Status'), async () => {
			await refreshUploadStatus(frm);
		}, TAX_INVOICE_OCR_GROUP);

		if (frm.doc.tax_invoice_pdf && providerReady !== false) {
			frm.add_custom_button(__('Run OCR'), async () => {
				await frappe.call({
					method: 'imogi_finance.api.tax_invoice.run_ocr_for_upload',
					args: { upload_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Queueing OCR...'),
				});
				frappe.show_alert({ message: __('OCR queued.'), indicator: 'green' });
				await refreshUploadStatus(frm);
			}, TAX_INVOICE_OCR_GROUP);
		}
		
		// Show info: Auto-parsing is triggered automatically after OCR completes
		if (frm.doc.ocr_status === 'Done' && frm.doc.parse_status === 'Draft' && !frm.doc.items.length) {
			frm.dashboard.set_headline_alert(
				__('⏳ Parsing line items automatically... Refresh halaman dalam beberapa detik untuk melihat hasil.'),
				'blue'
			);
		}
		
		// Add Re-Parse button ONLY when items already exist (for manual re-parse)
		if (frm.doc.tax_invoice_pdf && frm.doc.items && frm.doc.items.length > 0) {
			frm.add_custom_button(__('🔄 Re-Parse Line Items'), async () => {
				frappe.confirm(
					__('Re-parse akan menghapus semua line items yang ada dan parse ulang dari PDF. Lanjutkan?'),
					async () => {
						await frappe.call({
							doc: frm.doc,
							method: 'parse_line_items',
							args: { auto_triggered: false },
							freeze: true,
							freeze_message: __('Re-parsing line items dari PDF...'),
						});
						frappe.show_alert({ 
							message: __('Re-parsing selesai. Status: {0}', [frm.doc.parse_status]), 
							indicator: frm.doc.parse_status === 'Approved' ? 'green' : 'orange' 
						});
						await frm.reload_doc();
					}
				);
			}, TAX_INVOICE_OCR_GROUP);
		}
		
		// Show Review & Approve button when parse_status is Needs Review
		if (frm.doc.parse_status === 'Needs Review' && !frm.is_new()) {
			frm.dashboard.set_headline_alert(
				__('⚠️ Parse Status: Needs Review - Ada items dengan confidence rendah atau total tidak cocok. Periksa validation summary di bawah.'),
				'orange'
			);
			
			// Add Review & Approve button for manual approval after user fixes data
			frm.add_custom_button(__('Review & Approve'), () => {
				frappe.call({
					method: 'imogi_finance.imogi_finance.doctype.tax_invoice_ocr_upload.tax_invoice_ocr_upload.approve_parse',
					args: { docname: frm.doc.name },
					freeze: true,
					freeze_message: __('Approving parsed line items...'),
					callback: (r) => {
						if (r.message && r.message.ok) {
							frappe.show_alert({
								message: __('Parse status approved successfully'),
								indicator: 'green'
							});
							frm.reload_doc();
						} else {
							frappe.msgprint({
								message: r.message?.message || __('Failed to approve parse status'),
								indicator: 'red'
							});
						}
					}
				});
			}, TAX_INVOICE_OCR_GROUP);
		}
		
		// Show success for Approved status
		if (frm.doc.parse_status === 'Approved' && !frm.is_new()) {
			// Check if verification also passed
			const verificationPassed = frm.doc.verification_status === 'Verified';
			const verificationIssues = !frm.doc.npwp_match || frm.doc.duplicate_flag;
			
			if (verificationPassed) {
				frm.dashboard.set_headline_alert(
					__('✅ Parse Status: Approved - Semua line items valid dan siap digunakan.'),
					'green'
				);
			} else if (verificationIssues) {
				// Show warning if there are verification issues
				let issues = [];
				if (!frm.doc.npwp_match) issues.push('NPWP tidak match');
				if (frm.doc.duplicate_flag) issues.push('Faktur duplikat terdeteksi');
				
				frm.dashboard.set_headline_alert(
					__('⚠️ Parse OK, tapi ada masalah verifikasi: {0}', [issues.join(', ')]),
					'orange'
				);
			}
			
			// Add Generate Purchase Invoice button when approved AND verified
			if (frm.doc.items && frm.doc.items.length > 0 && verificationPassed) {
				frm.add_custom_button(__('Generate Purchase Invoice'), () => {
					frappe.msgprint(__('Purchase Invoice generation akan diimplementasi di fase integrasi.'));
				}, TAX_INVOICE_OCR_GROUP);
			}
		}

		// Add Manual Verify button only if auto-verify failed or not yet run
		// (normally auto-verify runs after parse succeeds)
		if (frm.doc.parse_status === 'Approved' && 
		    frm.doc.verification_status === 'Needs Review' &&
		    frm.doc.fp_no) {
			frm.add_custom_button(__('🔍 Re-Run Verification'), async () => {
				await frappe.call({
					method: 'imogi_finance.api.tax_invoice.verify_tax_invoice_upload',
					args: { upload_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Verifying Tax Invoice...'),
				});
				frappe.show_alert({ message: __('Verification complete.'), indicator: 'green' });
				await frm.reload_doc();
			}, TAX_INVOICE_OCR_GROUP);
		}
	},
	
	items_on_form_rendered(frm) {
		// Apply row color coding when grid is rendered
		apply_row_color_coding(frm);
	}
});

// Helper function to apply row-level color coding
function apply_row_color_coding(frm) {
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) {
		return;
	}
	
	// Wait for grid to render
	setTimeout(() => {
		frm.fields_dict.items.grid.grid_rows.forEach((grid_row, idx) => {
			if (!grid_row.doc) return;
			
			const confidence = grid_row.doc.row_confidence || 0;
			const $row = grid_row.wrapper;
			
			// Remove existing color classes
			$row.removeClass('confidence-high confidence-medium confidence-low');
			
			// Apply color coding based on confidence (0.0 - 1.0)
			if (confidence >= 0.95) {
				$row.addClass('confidence-high');
				$row.css('background-color', '#e8f5e9'); // Light green
			} else if (confidence >= 0.85) {
				$row.addClass('confidence-medium');
				$row.css('background-color', '#fff9c4'); // Light yellow
			} else if (confidence > 0) {
				$row.addClass('confidence-low');
				$row.css('background-color', '#ffebee'); // Light red
			}
		});
	}, 100);
}

// Event handler for child table
frappe.ui.form.on('Tax Invoice OCR Upload Item', {
	items_add(frm, cdt, cdn) {
		// Re-apply color coding when rows added
		apply_row_color_coding(frm);
	},
	
	form_render(frm, cdt, cdn) {
		// Re-apply color coding when grid refreshes
		apply_row_color_coding(frm);
	}
});
