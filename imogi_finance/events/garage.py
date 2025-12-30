import frappe


INSPECTION_DOCTYPE = "Inspection & Diagnosis"
REGISTRATION_DOCTYPE = "Customer Registration"


def _get_first_field(meta, candidates):
    for fieldname in candidates:
        if meta.has_field(fieldname):
            return fieldname
    return None


def _set_if_present(doc, fieldname, value):
    if fieldname and value is not None and doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _find_inspection_for_registration(registration_name):
    if not frappe.db.exists("DocType", INSPECTION_DOCTYPE):
        return None
    inspection_meta = frappe.get_meta(INSPECTION_DOCTYPE)
    registration_field = _get_first_field(
        inspection_meta,
        [
            "customer_registration",
            "registration",
            "customer_registration_id",
            "customer_registration_no",
        ],
    )
    if not registration_field:
        return None
    return frappe.db.get_value(
        INSPECTION_DOCTYPE,
        {registration_field: registration_name},
        "name",
        order_by="modified desc",
    )


def _populate_inspection_from_registration(inspection_doc, registration_doc):
    inspection_meta = inspection_doc.meta
    registration_meta = registration_doc.meta

    registration_field = _get_first_field(
        inspection_meta,
        [
            "customer_registration",
            "registration",
            "customer_registration_id",
            "customer_registration_no",
        ],
    )
    _set_if_present(inspection_doc, registration_field, registration_doc.name)

    for fieldname in [
        "customer",
        "customer_name",
        "contact_person",
        "contact_phone",
        "phone",
        "mobile_no",
        "email_id",
        "vehicle",
        "vehicle_details",
        "vehicle_model",
        "vehicle_brand",
        "license_plate",
        "vehicle_plate_no",
        "vehicle_no",
    ]:
        if registration_meta.has_field(fieldname) and inspection_meta.has_field(fieldname):
            _set_if_present(inspection_doc, fieldname, registration_doc.get(fieldname))


def create_inspection_on_registration_submit(doc, method=None):
    if doc.doctype != REGISTRATION_DOCTYPE:
        return
    if not frappe.db.exists("DocType", INSPECTION_DOCTYPE):
        return

    existing = _find_inspection_for_registration(doc.name)
    if existing:
        if doc.meta.has_field("inspection_document"):
            doc.db_set("inspection_document", existing, update_modified=False)
        return

    inspection_doc = frappe.new_doc(INSPECTION_DOCTYPE)
    _populate_inspection_from_registration(inspection_doc, doc)
    inspection_doc.insert(ignore_permissions=True, ignore_mandatory=True)

    if doc.meta.has_field("inspection_document"):
        doc.db_set("inspection_document", inspection_doc.name, update_modified=False)


def link_inspection_to_repair_order(doc, method=None):
    if not frappe.db.exists("DocType", INSPECTION_DOCTYPE):
        return
    if not doc.meta.has_field("inspection_document"):
        return
    if doc.get("inspection_document"):
        return

    inspection_name = None
    registration_field = _get_first_field(
        doc.meta,
        [
            "customer_registration",
            "registration",
            "customer_registration_id",
            "customer_registration_no",
        ],
    )
    if registration_field:
        registration_name = doc.get(registration_field)
        if registration_name:
            inspection_name = _find_inspection_for_registration(registration_name)

    if not inspection_name:
        inspection_meta = frappe.get_meta(INSPECTION_DOCTYPE)
        filters = {}
        for fieldname in [
            "customer",
            "customer_name",
            "vehicle",
            "vehicle_details",
            "vehicle_model",
            "vehicle_brand",
            "license_plate",
            "vehicle_plate_no",
            "vehicle_no",
        ]:
            if doc.meta.has_field(fieldname) and inspection_meta.has_field(fieldname):
                value = doc.get(fieldname)
                if value:
                    filters[fieldname] = value
        if filters:
            inspection_name = frappe.db.get_value(
                INSPECTION_DOCTYPE,
                filters,
                "name",
                order_by="modified desc",
            )

    if inspection_name:
        doc.set("inspection_document", inspection_name)


@frappe.whitelist()
def get_inspection_for_registration(registration_name):
    if not registration_name or not frappe.db.exists("DocType", INSPECTION_DOCTYPE):
        return None
    inspection_name = _find_inspection_for_registration(registration_name)
    if inspection_name:
        return inspection_name

    if frappe.db.exists("DocType", REGISTRATION_DOCTYPE):
        registration_doc = frappe.get_doc(REGISTRATION_DOCTYPE, registration_name)
        create_inspection_on_registration_submit(registration_doc)
        inspection_name = _find_inspection_for_registration(registration_name)

    return inspection_name
