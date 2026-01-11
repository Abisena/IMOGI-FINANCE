// Copyright (c) 2026, PT. Inovasi Terbaik Bangsa and contributors
// For license information, please see license.txt

frappe.ui.form.on('Branch Expense Approval Setting', {
	refresh(frm) {
		if (frm.doc.__islocal) {
			frm.set_df_property('info_html', 'options', get_intro_html());
		}
	},
	branch(frm) {
		if (frm.doc.branch && !frm.doc.branch_expense_approval_lines?.length) {
			add_default_line(frm);
		}
	},
});

frappe.ui.form.on('Branch Expense Approval Line', {
	expense_account(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (row.expense_account && row.is_default) {
			frappe.model.set_value(cdt, cdn, 'is_default', 0);
			frappe.show_alert({
				message: __('Cleared "Apply to All" flag because you selected a specific account.'),
				indicator: 'blue',
			});
		}
	},
	is_default(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (row.is_default && row.expense_account) {
			frappe.model.set_value(cdt, cdn, 'expense_account', null);
			frappe.show_alert({
				message: __('Cleared Expense Account because "Apply to All" is checked.'),
				indicator: 'blue',
			});
		}
	},
});

function add_default_line(frm) {
	const row = frm.add_child('branch_expense_approval_lines', {
		is_default: 1,
		level_1_min_amount: 0,
		level_1_max_amount: 999999999,
	});
	frm.refresh_field('branch_expense_approval_lines');
	frappe.show_alert({
		message: __('Added default approval line. Please configure approvers.'),
		indicator: 'green',
	});
}

function get_intro_html() {
	return `
		<div class="alert alert-info" style="margin-bottom: 15px;">
			<h5>🚀 Quick Start</h5>
			<ol>
				<li>Select the <strong>Branch</strong></li>
				<li>Add at least one <strong>Approval Line</strong> with "Apply to All Accounts" checked</li>
				<li>Configure approver users and amount ranges for each level</li>
				<li>Save and activate the setting</li>
			</ol>
			<p class="text-muted" style="margin-bottom: 0;">
				💡 Tip: You can add multiple lines for different expense accounts with specific approval rules.
			</p>
		</div>
	`;
}
