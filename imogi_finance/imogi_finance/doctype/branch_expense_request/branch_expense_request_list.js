frappe.listview_settings["Branch Expense Request"] = {
	add_fields: ["branch", "employee", "requester", "total_amount", "status", "budget_check_status"],
	
	get_indicator(doc) {
		// Status-based indicators
		if (doc.status === "Approved") {
			return [__("✅ Approved"), "green", "status,=,Approved"];
		}
		if (doc.status === "Pending Review") {
			return [__("⏳ Pending Review"), "orange", "status,=,Pending Review"];
		}
		if (doc.status === "Rejected") {
			return [__("❌ Rejected"), "red", "status,=,Rejected"];
		}
		if (doc.status === "Cancelled") {
			return [__("🚫 Cancelled"), "darkgrey", "status,=,Cancelled"];
		}
		
		// Budget status indicators for draft
		if (doc.budget_check_status === "Over Budget") {
			return [__("⚠️ Over Budget"), "red", "budget_check_status,=,Over Budget"];
		}
		if (doc.budget_check_status === "Warning") {
			return [__("⚠️ Budget Warning"), "yellow", "budget_check_status,=,Warning"];
		}
		
		return [__(doc.status || "📝 Draft"), "blue", "status,=," + (doc.status || "Draft")];
	},
	
	formatters: {
		total_amount(value) {
			return value ? format_currency(value) : "";
		}
	},
	
	onload(listview) {
		// Add custom action for bulk approval check
		listview.page.add_inner_button(__("🔍 Check Budget"), function() {
			frappe.msgprint(__("Budget check feature - coming soon"));
		});
	}
};
