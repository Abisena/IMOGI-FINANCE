#!/usr/bin/env python3
"""Final validation check for PB1 Multi-Account implementation."""

import json
import ast
import sys

def check_json_files():
    """Validate JSON syntax for all modified DocType definitions."""
    files = [
        'imogi_finance/imogi_finance/doctype/tax_profile_pb1_account/tax_profile_pb1_account.json',
        'imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.json',
        'imogi_finance/imogi_finance/doctype/tax_payment_batch/tax_payment_batch.json',
        'imogi_finance/imogi_finance/report/pb1_register/pb1_register.json'
    ]
    
    print("📋 JSON Validation:")
    all_valid = True
    for filepath in files:
        try:
            with open(filepath) as f:
                json.load(f)
            filename = filepath.split('/')[-1]
            print(f"  ✓ {filename}")
        except Exception as e:
            print(f"  ✗ {filepath}: {e}")
            all_valid = False
    
    return all_valid

def check_python_syntax():
    """Validate Python syntax for all modified files."""
    files = [
        'imogi_finance/imogi_finance/doctype/tax_profile_pb1_account/tax_profile_pb1_account.py',
        'imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.py',
        'imogi_finance/imogi_finance/doctype/tax_payment_batch/tax_payment_batch.py',
        'imogi_finance/tax_operations.py',
        'imogi_finance/imogi_finance/report/pb1_register/pb1_register.py'
    ]
    
    print("\n🐍 Python Syntax:")
    all_valid = True
    for filepath in files:
        try:
            with open(filepath) as f:
                ast.parse(f.read())
            filename = filepath.split('/')[-1]
            print(f"  ✓ {filename}")
        except Exception as e:
            print(f"  ✗ {filepath}: {e}")
            all_valid = False
    
    return all_valid

def check_key_implementations():
    """Verify key implementations exist."""
    print("\n🔍 Key Implementation Check:")
    
    checks = [
        ('tax_profile.py', 'get_pb1_account', 'imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.py'),
        ('tax_profile.py', '_validate_pb1_mappings', 'imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.py'),
        ('tax_profile.py', 'enable_pb1_multi_branch', 'imogi_finance/imogi_finance/doctype/tax_profile/tax_profile.py'),
        ('tax_operations.py', 'pb1_breakdown', 'imogi_finance/tax_operations.py'),
        ('tax_payment_batch.py', 'branch', 'imogi_finance/imogi_finance/doctype/tax_payment_batch/tax_payment_batch.py'),
        ('pb1_register.py', 'branch', 'imogi_finance/imogi_finance/report/pb1_register/pb1_register.py'),
    ]
    
    all_valid = True
    for filename, keyword, filepath in checks:
        try:
            with open(filepath) as f:
                content = f.read()
                if keyword in content:
                    print(f"  ✓ {filename}: '{keyword}' found")
                else:
                    print(f"  ✗ {filename}: '{keyword}' NOT found")
                    all_valid = False
        except Exception as e:
            print(f"  ✗ {filepath}: {e}")
            all_valid = False
    
    return all_valid

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("🔎 PB1 Multi-Account Implementation - Final Check")
    print("=" * 60)
    
    json_valid = check_json_files()
    python_valid = check_python_syntax()
    impl_valid = check_key_implementations()
    
    print("\n" + "=" * 60)
    if json_valid and python_valid and impl_valid:
        print("✅ ALL CHECKS PASSED - Implementation is ready!")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME CHECKS FAILED - Please review errors above")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
