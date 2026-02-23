# Payment Letter Testing Rules - Sales Invoice

## Overview
Dokumentasi ini berisi testing rules untuk fitur Payment Letter di Sales Invoice. Payment Letter adalah surat permintaan pembayaran yang di-generate otomatis dari Sales Invoice atau Payment Request.

## Test Coverage

### 1. **Basic Rendering Tests**
Testing dasar untuk memastikan payment letter ter-render dengan baik.

**Test Cases:**
- ✅ Render dengan default template
- ✅ Error handling saat payment letter disabled
- ✅ Fallback rendering saat tidak ada template

**Expected Behavior:**
```python
# Should return HTML string
html = render_payment_letter_html(sales_invoice)
assert html is not None
assert "Payment Letter" in html
assert sales_invoice.customer in html
```

### 2. **Context Building Tests**
Testing pembentukan context data untuk template Jinja.

**Test Cases:**
- ✅ Context dengan data lengkap
- ✅ Context dengan data minimal
- ✅ Format amount (currency formatting)
- ✅ Format date (DD-MM-YYYY)

**Expected Context Fields:**
```python
required_fields = [
    "company",
    "customer_name",
    "invoice_number",
    "amount",
    "amount_in_words",
    "due_date",
    "letter_date",
    "letter_number",
    "bank_name",
    "account_number"
]
```

### 3. **Template Selection Tests**
Testing logic pemilihan template berdasarkan branch dan letter type.

**Priority Order:**
1. Branch-specific template (highest priority)
2. Default template from settings
3. Fallback template (built-in)

**Test Cases:**
- ✅ Branch-specific template dipilih jika ada
- ✅ Fallback ke default template
- ✅ Template selection by letter type (Payment Letter vs Payment Request Letter)

### 4. **API Integration Tests**
Testing API endpoints yang di-whitelist untuk frontend.

**Endpoints to Test:**
```python
# For Sales Invoice
@frappe.whitelist()
def get_sales_invoice_payment_letter(name: str)

# For Payment Request
@frappe.whitelist()
def get_payment_request_payment_letter(name: str)
```

**Test Cases:**
- ✅ Valid Sales Invoice name returns HTML
- ✅ Invalid name throws DoesNotExistError
- ✅ Permission checks

### 5. **Edge Cases & Error Handling**
Testing skenario edge cases dan error handling.

**Test Cases:**
- ✅ Sales Invoice dengan amount = 0
- ✅ Missing customer data
- ✅ Invalid Jinja template syntax
- ✅ Missing required fields
- ✅ Multi-currency handling

## Running Tests

### Run All Payment Letter Tests
```bash
# Via bench
bench --site [site-name] run-tests --module imogi_finance.tests.test_payment_letter

# Specific test class
bench --site [site-name] run-tests --module imogi_finance.tests.test_payment_letter.TestPaymentLetterBasicRendering

# Specific test method
bench --site [site-name] run-tests --module imogi_finance.tests.test_payment_letter.TestPaymentLetterBasicRendering.test_render_payment_letter_with_default_template
```

### Run with Coverage
```bash
bench --site [site-name] run-tests --module imogi_finance.tests.test_payment_letter --coverage
```

## Test Data Requirements

### Required Master Data
```python
# Company
{
    "doctype": "Company",
    "company_name": "_Test Company",
    "abbr": "TC",
    "default_currency": "IDR"
}

# Customer
{
    "doctype": "Customer",
    "customer_name": "_Test Customer",
    "customer_type": "Company"
}

# Letter Template
{
    "doctype": "Letter Template",
    "template_name": "_Test Payment Letter Template",
    "letter_type": "Payment Letter",
    "is_active": 1,
    "body_html": "<div>...</div>"
}

# Letter Template Settings
{
    "doctype": "Letter Template Settings",
    "enable_payment_letter": 1,
    "default_template": "_Test Payment Letter Template"
}
```

### Sample Sales Invoice
```python
{
    "doctype": "Sales Invoice",
    "company": "_Test Company",
    "customer": "_Test Customer",
    "posting_date": "2026-02-23",
    "due_date": "2026-03-23",
    "items": [{
        "item_code": "_Test Item",
        "qty": 1,
        "rate": 1000000,
        "income_account": "Sales - TC",
        "cost_center": "Main - TC"
    }]
}
```

## Validation Rules

### 1. HTML Output Validation
```python
def validate_html_output(html: str):
    """Validate payment letter HTML output"""
    assert html is not None, "HTML should not be None"
    assert len(html) > 0, "HTML should not be empty"
    assert "<div" in html or "<html" in html, "Should contain HTML tags"
```

### 2. Context Data Validation
```python
def validate_context(context: dict):
    """Validate payment letter context"""
    required = ["company", "customer_name", "amount", "letter_date"]
    for field in required:
        assert field in context, f"Missing required field: {field}"
        assert context[field] is not None, f"Field {field} should not be None"
```

### 3. Amount Validation
```python
def validate_amount_formatting(context: dict):
    """Validate amount is properly formatted"""
    assert "amount" in context
    assert isinstance(context["amount"], str)

    # Should contain currency or number
    assert any(char.isdigit() for char in context["amount"])

    # Amount in words should exist
    assert "amount_in_words" in context
    assert len(context["amount_in_words"]) > 0
```

### 4. Date Validation
```python
def validate_date_formatting(context: dict):
    """Validate dates are properly formatted"""
    date_fields = ["letter_date", "invoice_date", "due_date"]
    for field in date_fields:
        if field in context and context[field]:
            assert isinstance(context[field], str)
            # Should be in readable format (not ISO)
            assert "/" in context[field] or "-" in context[field]
```

## Common Issues & Solutions

### Issue 1: Template Not Found
**Symptom:** Error "No template found for payment letter"

**Solution:**
```python
# Check if default template is set
settings = frappe.get_doc("Letter Template Settings")
if not settings.default_template:
    settings.default_template = "Default Payment Letter"
    settings.save()
```

### Issue 2: Missing Context Fields
**Symptom:** Jinja error "undefined variable"

**Solution:**
```python
# Always provide default values in context
context = {
    "customer_name": doc.customer_name or "",
    "amount": fmt_money(doc.grand_total) or "0",
    "due_date": formatdate(doc.due_date) if doc.due_date else ""
}
```

### Issue 3: Amount Formatting Error
**Symptom:** Amount shows as "None IDR"

**Solution:**
```python
# Check if amount exists before formatting
amount = doc.grand_total or doc.outstanding_amount or 0
formatted = fmt_money(amount, currency=doc.currency)
```

## Performance Considerations

### 1. Template Caching
Templates should be cached to avoid repeated database queries:
```python
# Use get_cached_doc for templates
template = frappe.get_cached_doc("Letter Template", template_name)
```

### 2. Batch Generation
For bulk payment letter generation:
```python
# Use bulk operations
invoices = frappe.get_all("Sales Invoice", filters={...})
for invoice in invoices:
    # Generate without committing until all done
    html = render_payment_letter_html(invoice)
    # Store or send...
frappe.db.commit()
```

### 3. Large Template Handling
For templates with images/large HTML:
```python
# Stream response instead of loading all in memory
return frappe.response.setContentType("text/html")
return render_payment_letter_html(doc)  # Stream directly
```

## Integration with Frontend

### JavaScript Hook
```javascript
// In sales_invoice.js
frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Print Payment Letter'), () => {
                frappe.call({
                    method: 'imogi_finance.overrides.sales_invoice.get_sales_invoice_payment_letter',
                    args: { name: frm.doc.name },
                    callback: function(r) {
                        if (r.message) {
                            // Open in print window
                            frappe.ui.get_print_settings(false, (print_settings) => {
                                var w = window.open(
                                    frappe.urllib.get_full_url("/printview?"
                                        + "doctype=" + encodeURIComponent("Sales Invoice")
                                        + "&name=" + encodeURIComponent(frm.doc.name)
                                        + "&format=Payment Letter"
                                    )
                                );
                            });
                        }
                    }
                });
            });
        }
    }
});
```

## Test Checklist

Before deployment, ensure all tests pass:

- [ ] All basic rendering tests pass
- [ ] Context building handles edge cases
- [ ] Template selection logic works correctly
- [ ] API endpoints respond correctly
- [ ] Error handling is robust
- [ ] Performance is acceptable (< 1s per letter)
- [ ] Frontend integration works
- [ ] Print preview displays correctly
- [ ] Multi-branch scenarios work
- [ ] Multi-currency scenarios work

## Continuous Testing

### Pre-commit Hook
Add to `.git/hooks/pre-commit`:
```bash
#!/bin/bash
bench --site [site] run-tests --module imogi_finance.tests.test_payment_letter --failfast
if [ $? -ne 0 ]; then
    echo "Payment letter tests failed! Commit aborted."
    exit 1
fi
```

### CI/CD Integration
Add to your CI pipeline:
```yaml
# .github/workflows/test.yml
test-payment-letter:
  runs-on: ubuntu-latest
  steps:
    - name: Run Payment Letter Tests
      run: |
        bench --site test_site run-tests \
          --module imogi_finance.tests.test_payment_letter \
          --coverage
```

---

**Last Updated:** 2026-02-23
**Maintained By:** IMOGI Finance Team
**Related Docs:**
- [Letter Template Settings](../imogi_finance/doctype/letter_template_settings/)
- [Letter Template Service](../services/letter_template_service.py)
- [Sales Invoice Override](../overrides/sales_invoice.py)
