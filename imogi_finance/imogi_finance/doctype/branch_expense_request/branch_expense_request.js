const BER_TAX_INVOICE_FIELDS = {
	fp_no: "ti_fp_no",
	fp_date: "ti_fp_date",
	npwp: "ti_fp_npwp",
	dpp: "ti_fp_dpp",
	ppn: "ti_fp_ppn",
	ppn_type: "ti_fp_ppn_type",
	verification_status: "ti_verification_status",
	verification_notes: "ti_verification_notes",
	duplicate_flag: "ti_duplicate_flag",
	npwp_match: "ti_npwp_match",
};

async function syncBerUpload(frm) {
	if (!frm.doc.ti_tax_invoice_upload) {
		return;
	}
	const upload = await frappe.db.get_doc("Tax Invoice OCR Upload", frm.doc.ti_tax_invoice_upload);
	const updates = {};
	Object.entries(BER_TAX_INVOICE_FIELDS).forEach(([source, target]) => {
		updates[target] = upload[source] || null;
	});
	await frm.set_value(updates);
}

function lockBerTaxInvoiceFields(frm) {
	Object.values(BER_TAX_INVOICE_FIELDS).forEach((field) => {
		frm.set_df_property(field, "read_only", true);
	});
}

function setBerTaxInvoiceReadOnly(frm, isManualOnly) {
	Object.values(BER_TAX_INVOICE_FIELDS).forEach((field) => {
		frm.set_df_property(field, "read_only", !isManualOnly);
	});
}

async function setBerUploadQuery(frm) {
	let usedUploads = [];
	let provider = "Manual Only";

	try {
		const { message } = await frappe.call({
			method: "imogi_finance.api.tax_invoice.get_tax_invoice_upload_context_api",
			args: { target_doctype: "Branch Expense Request", target_name: frm.doc.name },
		});
		usedUploads = message?.used_uploads || [];
		provider = message?.ocr_provider || provider;
	} catch (error) {
		console.error("Unable to load available Tax Invoice uploads", error);
	}

	setBerTaxInvoiceReadOnly(frm, provider === "Manual Only");

	frm.set_query("ti_tax_invoice_upload", () => ({
		filters: {
			verification_status: "Verified",
			...(usedUploads.length ? { name: ["not in", usedUploads] } : {}),
		},
	}));
}

frappe.ui.form.on("Branch Expense Request", {
	onload(frm) {
		update_totals(frm);
	},
	async refresh(frm) {
		update_totals(frm);
		await setBerUploadQuery(frm);
		await syncBerUpload(frm);
		maybeAddOcrButton(frm);
		maybeAddUploadActions(frm);
	},
	items_add(frm) {
		update_totals(frm);
	},
	items_remove(frm) {
		update_totals(frm);
	},
	ti_tax_invoice_upload: async function (frm) {
		await syncBerUpload(frm);
	},
});

frappe.ui.form.on("Branch Expense Request Item", {
	qty(frm, cdt, cdn) {
		update_item_amount(frm, cdt, cdn);
	},
	rate(frm, cdt, cdn) {
		update_item_amount(frm, cdt, cdn);
	},
	amount(frm) {
		update_totals(frm);
	},
});

function update_item_amount(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const qty = flt(row.qty) || 0;
	const rate = flt(row.rate) || 0;
	const amount = qty * rate;
	frappe.model.set_value(cdt, cdn, "amount", amount);
	update_totals(frm);
}

function update_totals(frm) {
	const accounts = new Set();
	const total = (frm.doc.items || []).reduce((acc, row) => {
		if (row.expense_account) {
			accounts.add(row.expense_account);
		}
		return acc + flt(row.amount || 0);
	}, 0);

	frm.set_value("total_amount", total);
	frm.set_value("amount", total);
	frm.set_value("expense_account", accounts.size === 1 ? [...accounts][0] : null);
}

async function maybeAddOcrButton(frm) {
	if (!frm.doc.name) {
		return;
	}

	const enabled = await frappe.db.get_single_value("Tax Invoice OCR Settings", "enable_tax_invoice_ocr");
	if (!enabled || !frm.doc.ti_tax_invoice_upload) {
		return;
	}

	frm.add_custom_button(__("Run OCR"), async () => {
		await frappe.call({
			method: "imogi_finance.api.tax_invoice.run_ocr_for_upload",
			args: { upload_name: frm.doc.ti_tax_invoice_upload },
			freeze: true,
			freeze_message: __("Queueing OCR..."),
		});
		frappe.show_alert({ message: __("OCR queued."), indicator: "green" });
		await syncBerUpload(frm);
	}, __("Tax Invoice"));
}

function maybeAddUploadActions(frm) {
	if (!frm.doc.name || !frm.doc.ti_tax_invoice_upload) {
		return;
	}

	frm.add_custom_button(__("Open Tax Invoice Upload"), () => {
		frappe.set_route("Form", "Tax Invoice OCR Upload", frm.doc.ti_tax_invoice_upload);
	}, __("Tax Invoice"));

	frm.add_custom_button(__("Refresh Tax Invoice Data"), async () => {
		await frappe.call({
			method: "imogi_finance.api.tax_invoice.apply_tax_invoice_upload",
			args: { target_doctype: "Branch Expense Request", target_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Refreshing..."),
		});
		await frm.reload_doc();
	}, __("Tax Invoice"));
}
