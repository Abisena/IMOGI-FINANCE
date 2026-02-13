"""
Integration Tests for Tax Registers - ERPNext v15+ Native-First

Tests covering:
- GL Entry validation (only show transactions with proper journal entries)
- Configuration validation and error handling
- Filter functionality
- Query performance
- Data integrity
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, flt

from imogi_finance.imogi_finance.utils.tax_report_utils import (
	validate_vat_input_configuration,
	validate_vat_output_configuration,
	validate_withholding_configuration,
	has_valid_gl_entries,
	get_tax_amount_from_gl,
	get_tax_profile,
	get_tax_invoice_ocr_settings
)


class TestTaxRegistersV15(FrappeTestCase):
	"""Test suite for modernized tax registers."""
	
	@classmethod
	def setUpClass(cls):
		"""Set up test data once for all tests."""
		super().setUpClass()
		cls.company = "_Test Company"
		cls.setup_test_configuration()
	
	@classmethod
	def setup_test_configuration(cls):
		"""Create test Tax Profile and settings."""
		# Create test Tax Invoice OCR Settings
		if not frappe.db.exists("Tax Invoice OCR Settings"):
			settings = frappe.get_doc({
				"doctype": "Tax Invoice OCR Settings",
				"enable_ocr": 0,
				"ppn_input_account": "_Test PPN Input - _TC",
				"ppn_output_account": "_Test PPN Output - _TC"
			})
			settings.insert(ignore_if_duplicate=True)
		else:
			settings = frappe.get_single("Tax Invoice OCR Settings")
			settings.ppn_input_account = "_Test PPN Input - _TC"
			settings.ppn_output_account = "_Test PPN Output - _TC"
			settings.save()
		
		# Create test Tax Profile
		if not frappe.db.exists("Tax Profile", {"company": cls.company}):
			profile = frappe.get_doc({
				"doctype": "Tax Profile",
				"company": cls.company,
				"ppn_input_account": "_Test PPN Input - _TC",
				"ppn_output_account": "_Test PPN Output - _TC",
				"pph_accounts": [
					{
						"pph_type": "PPh 23",
						"payable_account": "_Test Payable - _TC"
					}
				]
			})
			profile.insert(ignore_if_duplicate=True)
	
	def test_vat_input_configuration_validation(self):
		"""Test VAT Input Register configuration validation."""
		result = validate_vat_input_configuration(self.company)
		
		self.assertTrue(result.get("valid"), "Configuration should be valid")
		self.assertIn("account", result)
		self.assertEqual(result.get("indicator"), "green")
	
	def test_vat_output_configuration_validation(self):
		"""Test VAT Output Register configuration validation."""
		result = validate_vat_output_configuration(self.company)
		
		self.assertTrue(result.get("valid"), "Configuration should be valid")
		self.assertIn("account", result)
		self.assertEqual(result.get("indicator"), "green")
	
	def test_withholding_configuration_validation(self):
		"""Test Withholding Register configuration validation."""
		result = validate_withholding_configuration(self.company)
		
		self.assertTrue(result.get("valid"), "Configuration should be valid")
		self.assertIn("accounts", result)
		self.assertGreater(len(result.get("accounts", [])), 0)
		self.assertEqual(result.get("indicator"), "green")
	
	def test_configuration_validation_missing_company(self):
		"""Test configuration validation fails without company."""
		result = validate_withholding_configuration("")
		
		self.assertFalse(result.get("valid"))
		self.assertEqual(result.get("indicator"), "red")
	
	def test_has_valid_gl_entries(self):
		"""Test GL Entry validation for invoices."""
		# Create test Purchase Invoice with GL entries
		pi = self.create_test_purchase_invoice()
		pi.submit()
		
		# Verify GL entries exist
		has_gl = has_valid_gl_entries(
			voucher_type="Purchase Invoice",
			voucher_no=pi.name,
			company=self.company
		)
		
		self.assertTrue(has_gl, "Submitted invoice should have GL entries")
		
		# Clean up
		pi.cancel()
		pi.delete()
	
	def test_get_tax_amount_from_gl(self):
		"""Test retrieving tax amount from GL Entry."""
		pi = self.create_test_purchase_invoice()
		pi.submit()
		
		# Get tax amount from GL
		tax_amount = get_tax_amount_from_gl(
			voucher_type="Purchase Invoice",
			voucher_no=pi.name,
			tax_account="_Test PPN Input - _TC",
			company=self.company
		)
		
		# Tax should be 11% of base amount (assuming standard PPN)
		self.assertGreater(tax_amount, 0, "Tax amount should be positive")
		
		# Clean up
		pi.cancel()
		pi.delete()
	
	def test_vat_input_register_execution(self):
		"""Test VAT Input Register report execution."""
		from imogi_finance.imogi_finance.report.vat_input_register_verified.vat_input_register_verified import execute
		
		# Create test data
		pi = self.create_test_purchase_invoice()
		pi.ti_verification_status = "Verified"
		pi.save()
		pi.submit()
		
		# Execute report
		filters = {
			"company": self.company,
			"from_date": add_days(today(), -30),
			"to_date": today(),
			"verification_status": "Verified"
		}
		
		columns, data = execute(filters)
		
		# Verify results
		self.assertGreater(len(columns), 0, "Should have columns")
		self.assertGreater(len(data), 0, "Should have data rows")
		
		# Verify our test invoice is in results
		invoice_found = any(row.get("name") == pi.name for row in data)
		self.assertTrue(invoice_found, "Test invoice should appear in report")
		
		# Clean up
		pi.cancel()
		pi.delete()
	
	def test_vat_output_register_execution(self):
		"""Test VAT Output Register report execution."""
		from imogi_finance.imogi_finance.report.vat_output_register_verified.vat_output_register_verified import execute
		
		# Create test data
		si = self.create_test_sales_invoice()
		si.out_fp_status = "Verified"
		si.save()
		si.submit()
		
		# Execute report
		filters = {
			"company": self.company,
			"from_date": add_days(today(), -30),
			"to_date": today(),
			"verification_status": "Verified"
		}
		
		columns, data = execute(filters)
		
		# Verify results
		self.assertGreater(len(columns), 0, "Should have columns")
		self.assertGreater(len(data), 0, "Should have data rows")
		
		# Verify our test invoice is in results
		invoice_found = any(row.get("name") == si.name for row in data)
		self.assertTrue(invoice_found, "Test invoice should appear in report")
		
		# Clean up
		si.cancel()
		si.delete()
	
	def test_withholding_register_execution(self):
		"""Test Withholding Register report execution."""
		from imogi_finance.imogi_finance.report.withholding_register.withholding_register import execute
		
		# Create test purchase invoice with withholding
		pi = self.create_test_purchase_invoice_with_withholding()
		pi.submit()
		
		# Execute report
		filters = {
			"company": self.company,
			"from_date": add_days(today(), -30),
			"to_date": today()
		}
		
		columns, data = execute(filters)
		
		# Verify results
		self.assertGreater(len(columns), 0, "Should have columns")
		self.assertGreater(len(data), 0, "Should have GL entries")
		
		# Clean up
		pi.cancel()
		pi.delete()
	
	def test_report_filters_supplier(self):
		"""Test VAT Input Register with supplier filter."""
		from imogi_finance.imogi_finance.report.vat_input_register_verified.vat_input_register_verified import execute
		
		# Create test invoices for different suppliers
		pi1 = self.create_test_purchase_invoice(supplier="_Test Supplier")
		pi1.ti_verification_status = "Verified"
		pi1.save()
		pi1.submit()
		
		pi2 = self.create_test_purchase_invoice(supplier="_Test Supplier 1")
		pi2.ti_verification_status = "Verified"
		pi2.save()
		pi2.submit()
		
		# Filter by specific supplier
		filters = {
			"company": self.company,
			"supplier": "_Test Supplier",
			"verification_status": "Verified"
		}
		
		columns, data = execute(filters)
		
		# Should only show invoices for filtered supplier
		suppliers = [row.get("supplier") for row in data]
		self.assertTrue(all(s == "_Test Supplier" for s in suppliers if s))
		
		# Clean up
		pi1.cancel()
		pi1.delete()
		pi2.cancel()
		pi2.delete()
	
	def test_cache_functionality(self):
		"""Test caching of Tax Profile and settings."""
		# First call should hit database
		profile1 = get_tax_profile(self.company)
		
		# Second call should use cache
		profile2 = get_tax_profile(self.company)
		
		self.assertEqual(profile1.name, profile2.name)
		
		# Test settings cache
		settings1 = get_tax_invoice_ocr_settings()
		settings2 = get_tax_invoice_ocr_settings()
		
		self.assertEqual(settings1.name, settings2.name)
	
	# Helper methods
	
	def create_test_purchase_invoice(self, supplier="_Test Supplier"):
		"""Create a test Purchase Invoice."""
		pi = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": self.company,
			"supplier": supplier,
			"posting_date": today(),
			"currency": "IDR",
			"items": [{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 1000000,
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"cost_center": "_Test Cost Center - _TC"
			}],
			"taxes": [{
				"charge_type": "On Net Total",
				"account_head": "_Test PPN Input - _TC",
				"description": "PPN 11%",
				"rate": 11
			}]
		})
		pi.insert()
		return pi
	
	def create_test_sales_invoice(self, customer="_Test Customer"):
		"""Create a test Sales Invoice."""
		si = frappe.get_doc({
			"doctype": "Sales Invoice",
			"company": self.company,
			"customer": customer,
			"posting_date": today(),
			"currency": "IDR",
			"items": [{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 1000000,
				"income_account": "_Test Account Sales - _TC",
				"cost_center": "_Test Cost Center - _TC"
			}],
			"taxes": [{
				"charge_type": "On Net Total",
				"account_head": "_Test PPN Output - _TC",
				"description": "PPN 11%",
				"rate": 11
			}]
		})
		si.insert()
		return si
	
	def create_test_purchase_invoice_with_withholding(self):
		"""Create a Purchase Invoice with withholding tax."""
		pi = frappe.get_doc({
			"doctype": "Purchase Invoice",
			"company": self.company,
			"supplier": "_Test Supplier",
			"posting_date": today(),
			"currency": "IDR",
			"apply_tds": 1,
			"items": [{
				"item_code": "_Test Item",
				"qty": 1,
				"rate": 1000000,
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"cost_center": "_Test Cost Center - _TC"
			}],
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": "_Test PPN Input - _TC",
					"description": "PPN 11%",
					"rate": 11
				},
				{
					"charge_type": "On Net Total",
					"account_head": "_Test Payable - _TC",
					"description": "PPh 23 - 2%",
					"rate": -2,
					"add_deduct_tax": "Deduct"
				}
			]
		})
		pi.insert()
		return pi


def run_performance_benchmark():
	"""
	Run performance benchmarks for tax registers.
	Not a unit test - run separately for performance analysis.
	"""
	import time
	from imogi_finance.imogi_finance.report.vat_input_register_verified.vat_input_register_verified import execute as vat_input_execute
	from imogi_finance.imogi_finance.report.vat_output_register_verified.vat_output_register_verified import execute as vat_output_execute
	from imogi_finance.imogi_finance.report.withholding_register.withholding_register import execute as withholding_execute
	
	company = frappe.defaults.get_user_default("Company")
	filters = {
		"company": company,
		"from_date": add_days(today(), -365),  # 1 year of data
		"to_date": today()
	}
	
	results = {}
	
	# Benchmark VAT Input Register
	start = time.time()
	columns, data = vat_input_execute(filters)
	elapsed = time.time() - start
	results["vat_input"] = {
		"rows": len(data),
		"time_seconds": elapsed,
		"rows_per_second": len(data) / elapsed if elapsed > 0 else 0
	}
	
	# Benchmark VAT Output Register
	start = time.time()
	columns, data = vat_output_execute(filters)
	elapsed = time.time() - start
	results["vat_output"] = {
		"rows": len(data),
		"time_seconds": elapsed,
		"rows_per_second": len(data) / elapsed if elapsed > 0 else 0
	}
	
	# Benchmark Withholding Register
	start = time.time()
	columns, data = withholding_execute(filters)
	elapsed = time.time() - start
	results["withholding"] = {
		"rows": len(data),
		"time_seconds": elapsed,
		"rows_per_second": len(data) / elapsed if elapsed > 0 else 0
	}
	
	return results
