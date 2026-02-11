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

		// Only skip if OCR is disabled (removed frm.is_new() check to support autoname behavior)
		if (!enabled) {
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

		// Only show buttons for saved documents (after autoname creates permanent name)
		if (!frm.is_new()) {
			frm.add_custom_button(__('Refresh OCR Status'), async () => {
				await refreshUploadStatus(frm);
			}, TAX_INVOICE_OCR_GROUP);
		}

		// Run OCR button: Show when OCR not yet run, failed, or pending (works even after autoname save)
		const ocrNotDone = !frm.doc.ocr_status || 
			frm.doc.ocr_status === 'Not Started' || 
			frm.doc.ocr_status === 'Failed' || 
			frm.doc.ocr_status === 'Pending';
		
		if (!frm.is_new() && frm.doc.tax_invoice_pdf && providerReady !== false && ocrNotDone) {
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

		// Add Manual Verify button if verification needed
		if (frm.doc.verification_status === 'Needs Review' && frm.doc.fp_no) {
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
	}
});
