frappe.listview_settings["Branch Expense Approval Setting"] = {
	add_fields: ["branch", "is_active"],
	get_indicator(doc) {
		if (doc.is_active) {
			return [__("Active"), "green", "is_active,=,1"];
		}
		return [__("Inactive"), "gray", "is_active,=,0"];
	},
	onload(listview) {
		listview.page.add_inner_button(__("New Approval Setting"), () => {
			frappe.new_doc("Branch Expense Approval Setting");
		});
	},
};
