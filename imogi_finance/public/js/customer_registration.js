frappe.ui.form.on("Customer Registration", {
    on_submit(frm) {
        frappe.call({
            method: "imogi_finance.events.garage.get_inspection_for_registration",
            args: { registration_name: frm.doc.name },
            callback: (response) => {
                const inspectionName = response.message;
                if (inspectionName) {
                    frappe.set_route("Form", "Inspection & Diagnosis", inspectionName);
                }
            },
        });
    },
});
