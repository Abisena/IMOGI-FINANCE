# Native First Implementation - Deployment Checklist

**IMOGI Finance - Advance Payment Native Enhancement**  
**Target Environment**: Production / Test Site  
**Deployment Date**: __________

---

## Pre-Deployment Checklist

### System Requirements

- [ ] ERPNext version v15.0.0 or higher verified
- [ ] Frappe Framework v15.0.0 or higher verified
- [ ] Python 3.10+ confirmed
- [ ] Database backup created (timestamp: __________)
- [ ] Test site available for validation

### Code Review

- [ ] `imogi_finance/advance_payment_native/` directory reviewed
- [ ] `test_native_payment_ledger.py` script verified
- [ ] `hooks.py` expense claim integration reviewed
- [ ] All documentation reviewed by stakeholders
- [ ] Code approved by: __________

---

## Deployment Steps

### Step 1: Backup

```bash
# Database backup
bench --site [your-site] backup --with-files

# Verify backup exists
ls -lh sites/[your-site]/private/backups/
```

- [ ] Database backup completed
- [ ] Files backup completed
- [ ] Backup location recorded: __________

---

### Step 2: Pull Latest Code

```bash
cd frappe-bench/apps/imogi_finance
git fetch origin
git checkout main  # or your deployment branch
git pull origin main
```

- [ ] Code pulled successfully
- [ ] Commit hash recorded: __________
- [ ] No merge conflicts

---

### Step 3: Install/Migrate

```bash
# Migrate database
bench --site [your-site] migrate

# Expected output: All migrations completed successfully
```

- [ ] Migration completed without errors
- [ ] No deprecation warnings relevant to our code
- [ ] Migration log reviewed

---

### Step 4: Clear Cache

```bash
bench --site [your-site] clear-cache
bench --site [your-site] clear-website-cache
bench restart
```

- [ ] Cache cleared
- [ ] Bench restarted
- [ ] Site accessible after restart

---

## Verification Tests

### Test 1: Native Payment Ledger

```bash
bench --site [your-site] execute imogi_finance.test_native_payment_ledger.test_payment_ledger
```

**Expected Output**:
```
✓ Payment Ledger Entry DocType exists
✓ Total Payment Ledger Entries: XXX
✓ Advance Payment Ledger report exists
✓ Payment Ledger report exists
```

- [ ] Test passed
- [ ] Payment Ledger Entry table exists
- [ ] Native reports accessible
- [ ] Sample data shows correctly

**If Test Fails**: 
- Check ERPNext version (must be v15+)
- Verify `erpnext` app is active
- Review migration logs for errors

---

### Test 2: Custom Dashboard Report

**Manual Test**:
1. Login to ERPNext
2. Go to: Accounting → Reports
3. Find "Advance Payment Dashboard"
4. Open report

**Verify**:
- [ ] Report appears in list
- [ ] Report opens without errors
- [ ] If data exists, shows with status colors
- [ ] Filters work (Company, Party Type, Date Range)
- [ ] Export to Excel works

**If Report Missing**:
```bash
bench --site [your-site] console
```
```python
import frappe
frappe.reload_doctype("Report")
frappe.db.commit()
```

---

### Test 3: Expense Claim Integration

**Manual Test**:
1. Create test Employee (if not exists)
2. Create Payment Entry:
   - Payment Type: Pay
   - Party Type: Employee
   - Party: [Test Employee]
   - Amount: 1,000,000
   - Save & Submit
3. Check Payment Ledger Entry created
4. Create Expense Claim for same employee
5. Check for "Get Employee Advances" button

**Verify**:
- [ ] Payment Entry created successfully
- [ ] Payment Ledger Entry exists for PE
- [ ] Expense Claim form loads
- [ ] "Get Employee Advances" button visible
- [ ] Button shows dialog with available advances
- [ ] Auto-allocation on submit works

**If Button Missing**:
- Check client script installed
- Clear browser cache (Ctrl+Shift+R)
- Check console for JS errors

---

### Test 4: Hook Integration

```bash
bench --site [your-site] console
```

```python
import frappe

# Verify hooks loaded
hooks = frappe.get_hooks("doc_events")
ec_hooks = hooks.get("Expense Claim", {})
print("Expense Claim hooks:", ec_hooks)

# Should show:
# on_submit: ['imogi_finance.advance_payment_native.expense_claim_advances.link_employee_advances', ...]
```

- [ ] Hooks loaded correctly
- [ ] `link_employee_advances` in on_submit hooks
- [ ] No import errors

---

### Test 5: End-to-End Supplier Advance

**Create Test Advance**:
1. Go to: Accounting → Payment Entry → New
2. Set:
   - Payment Type: Pay
   - Party Type: Supplier
   - Party: [Any Supplier]
   - Paid From: [Bank Account]
   - Paid To: Accounts Payable
   - Amount: 10,000,000
3. Save & Submit

**Allocate to Invoice**:
1. Go to: Accounting → Purchase Invoice → New
2. Set supplier, items
3. Click: Get Items From → Get Advances
4. Select advance, allocate amount
5. Save & Submit

**Verify**:
- [ ] Payment Entry created (PE-XXXX)
- [ ] Payment Ledger Entry created with `against_voucher_type = NULL`
- [ ] Get Advances shows the payment
- [ ] Allocation successful
- [ ] Payment Ledger Entry updated with `against_voucher_type = Purchase Invoice`
- [ ] Custom dashboard shows status change 🔴 → ✅

---

### Test 6: Performance Test

**If you have 100+ existing advances**:

```bash
bench --site [your-site] console
```

```python
import frappe
import time

# Test query performance
start = time.time()
result = frappe.db.sql("""
    SELECT voucher_no, party, SUM(amount) as total
    FROM `tabPayment Ledger Entry`
    WHERE delinked = 0
    GROUP BY voucher_no, party
    LIMIT 1000
""", as_dict=True)
end = time.time()

print(f"Query time: {(end-start)*1000:.0f}ms for {len(result)} records")
# Should be < 500ms
```

- [ ] Query time acceptable (< 500ms)
- [ ] No database errors
- [ ] Results accurate

**If Slow**:
- Check database indexes
- Run `ANALYZE TABLE` on Payment Ledger Entry
- Consider archiving old fully-allocated entries

---

## Configuration

### Setup Advance Accounts

```bash
bench --site [your-site] console
```

```python
import frappe

company = frappe.defaults.get_user_default("Company")
print(f"Configuring for company: {company}")

# Check if advance accounts exist
accounts = [
    "Advances Paid - Supplier",
    "Advances Received - Customer", 
    "Advances Paid - Employee"
]

for acc in accounts:
    exists = frappe.db.exists("Account", acc + " - " + frappe.get_cached_value("Company", company, "abbr"))
    print(f"{acc}: {'✓ Exists' if exists else '✗ Missing'}")

# If missing, create them (see installation guide)
```

- [ ] Advance accounts verified/created
- [ ] Accounts assigned to correct company
- [ ] Account types correct (Receivable/Payable)

---

### Add Report to Workspace

**Manual**:
1. Go to: Setup → Workspace → Accounting
2. Edit workspace
3. Add link:
   - Label: Advance Payment Dashboard
   - Type: Report
   - Link To: Advance Payment Dashboard
4. Save

- [ ] Report added to Accounting workspace
- [ ] Report accessible from workspace
- [ ] Icon and description set

---

### Setup Client Script (Optional Enhancement)

**Only if you want better UX on Expense Claim form**:

1. Go to: Setup → Customization → Client Script
2. Create new:
   - Name: Expense Claim - Get Employee Advances
   - DocType: Expense Claim
   - Script Type: Form Script
   - Script: Copy from `expense_claim_advances.py` CLIENT_SCRIPT constant
3. Save

- [ ] Client script created
- [ ] Script enabled
- [ ] No syntax errors

---

## User Training

### Documentation Distribution

- [ ] User guide sent to accounting team
- [ ] Installation guide shared with admins
- [ ] Decision guide shared with management
- [ ] Implementation summary reviewed

**Recipients**:
- Accounting team: __________
- System admins: __________
- Management: __________

---

### Training Session

**Schedule**:
- Date: __________
- Time: __________
- Duration: 2 hours
- Attendees: __________

**Agenda**:
1. Introduction to native Payment Ledger (15 min)
2. Demo: Supplier advance workflow (20 min)
3. Demo: Customer advance workflow (15 min)
4. Demo: Employee advance workflow (20 min)
5. Custom dashboard tour (15 min)
6. Q&A (30 min)
7. Hands-on practice (optional)

- [ ] Training scheduled
- [ ] Materials prepared
- [ ] Demo data created
- [ ] Training completed
- [ ] Feedback collected

---

## Rollout Plan

### Phase 1: Pilot Users (Week 1-2)

**Select 3-5 pilot users from accounting team**:

- [ ] Pilot users selected: __________
- [ ] Pilot users trained
- [ ] Pilot users testing workflows
- [ ] Daily check-ins scheduled
- [ ] Issues log created

**Success Criteria**:
- [ ] 90%+ satisfaction score
- [ ] Zero critical bugs
- [ ] All workflows tested
- [ ] Performance acceptable

---

### Phase 2: Full Rollout (Week 3-4)

**Deploy to all accounting users**:

- [ ] All users trained
- [ ] Access permissions set
- [ ] Support channel established
- [ ] Monitoring dashboard setup

**Communication**:
- [ ] Announcement sent
- [ ] FAQ distributed
- [ ] Support contact shared
- [ ] Change log published

---

### Phase 3: Migration (Week 4-8) - If Applicable

**Only if old APE module exists**:

- [ ] Data consistency verified (run verification script)
- [ ] APE module marked as deprecated
- [ ] Users notified of deprecation
- [ ] APE disabled in navigation
- [ ] 2-week parallel run completed
- [ ] APE code removed from active hooks
- [ ] Archive completed

---

## Post-Deployment Monitoring

### Week 1 Monitoring

**Daily checks**:
- [ ] Day 1: Check for errors in logs
- [ ] Day 2: Verify advance entries created
- [ ] Day 3: Check allocation workflows
- [ ] Day 4: Review custom report usage
- [ ] Day 5: Performance metrics

**Metrics to Track**:
- Number of advances created: __________
- Number of allocations: __________
- Average allocation time: __________
- User satisfaction: __________
- Issues reported: __________

---

### Week 2-4 Monitoring

**Weekly checks**:
- [ ] Week 2: User feedback survey
- [ ] Week 3: Performance review
- [ ] Week 4: Final assessment

---

## Issue Tracking

### Critical Issues (P0)

| Issue | Reported By | Date | Status | Resolution |
|-------|------------|------|--------|------------|
|       |            |      |        |            |

---

### High Priority (P1)

| Issue | Reported By | Date | Status | Resolution |
|-------|------------|------|--------|------------|
|       |            |      |        |            |

---

### Medium/Low Priority (P2/P3)

| Issue | Reported By | Date | Status | Resolution |
|-------|------------|------|--------|------------|
|       |            |      |        |            |

---

## Rollback Plan (Emergency)

**If critical issues found**:

### Step 1: Disable Enhancement

```bash
# Remove hooks temporarily
bench --site [your-site] console
```

```python
import frappe

# Comment out expense claim hook in hooks.py
# Or disable via site config
```

---

### Step 2: Restore Backup

```bash
# If database corruption
bench --site [your-site] --force restore [backup-file]
```

- [ ] Backup file identified: __________
- [ ] Restore tested on staging
- [ ] Stakeholders notified

---

### Step 3: Communication

- [ ] Users notified of rollback
- [ ] Issue explanation sent
- [ ] Fix timeline communicated
- [ ] Alternative workflow provided

---

## Sign-Off

### Deployment Completion

- [ ] All verification tests passed
- [ ] Configuration completed
- [ ] Documentation distributed
- [ ] Training completed
- [ ] Pilot successful
- [ ] Rollout completed

**Deployed By**: __________ (Name & Signature)  
**Date**: __________  
**Time**: __________

---

### Stakeholder Approvals

**Technical Lead**:
- Name: __________
- Signature: __________
- Date: __________
- Comments: __________

**Finance Manager**:
- Name: __________
- Signature: __________
- Date: __________
- Comments: __________

**System Administrator**:
- Name: __________
- Signature: __________
- Date: __________
- Comments: __________

---

## Final Notes

### Deployment Summary

**What Worked Well**:
- 
- 
- 

**Challenges Faced**:
- 
- 
- 

**Lessons Learned**:
- 
- 
- 

**Recommendations for Future**:
- 
- 
- 

---

## Contact Information

**Technical Support**:
- Email: imogi.indonesia@gmail.com
- Phone: __________
- Hours: __________

**Escalation**:
- Primary: __________
- Secondary: __________
- Emergency: __________

---

**Document Version**: 1.0  
**Last Updated**: 2026-01-23  
**Next Review**: After deployment completion

---

## Appendix A: Quick Commands

```bash
# Backup
bench --site [site] backup --with-files

# Deploy
cd apps/imogi_finance && git pull
bench --site [site] migrate
bench --site [site] clear-cache
bench restart

# Verify
bench --site [site] execute imogi_finance.test_native_payment_ledger.test_payment_ledger

# Rollback
bench --site [site] --force restore [backup-file]
```

---

## Appendix B: Common Issues & Solutions

**Issue**: Report not showing  
**Solution**: `bench --site [site] clear-cache && bench restart`

**Issue**: Button missing on Expense Claim  
**Solution**: Check client script, clear browser cache (Ctrl+Shift+R)

**Issue**: Hooks not firing  
**Solution**: Verify in console: `frappe.get_hooks("doc_events")`

**Issue**: Performance slow  
**Solution**: Add database indexes, archive old entries

**Issue**: Permission denied  
**Solution**: Check user roles, add "Accounts User" role

---

**END OF DEPLOYMENT CHECKLIST**
