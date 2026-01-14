# Copyright (c) 2026, IMOGI and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ExpenseRequestAssetLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset: DF.Link
		asset_category: DF.Link | None
		asset_location: DF.Link | None
		asset_name: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		status: DF.Data | None
	# end: auto-generated types

	pass
