#!/usr/bin/env python3
"""
Test script for Indonesian currency parser.

Run this to verify parse_indonesian_currency() handles all test cases correctly.
"""

# Mock frappe for standalone testing
class MockLogger:
    def warning(self, msg):
        print(f"⚠️  {msg}")

    def info(self, msg):
        print(f"ℹ️  {msg}")

class MockFrappe:
    def logger(self):
        return MockLogger()

import sys
sys.modules['frappe'] = MockFrappe()

# Now import the function
from imogi_finance.imogi_finance.parsers.normalization import parse_indonesian_currency


def test_parse_indonesian_currency():
    """Test all examples from the requirements."""

    test_cases = [
        # (input, expected_output, description)
        ("4.953.154,00", 4953154.00, "Standard format with dots and comma"),
        ("Rp 4.953.154,00", 4953154.00, "With Rp prefix and space"),
        ("517.605,00", 517605.00, "Smaller amount with dots"),
        ("Rp 247.658,00", 247658.00, "With Rp prefix"),
        ("0,00", 0.0, "Zero with comma"),
        ("4953154", 4953154.0, "Integer without separators"),
        ("Rp4.953.154,00", 4953154.0, "Rp without space"),
        ("  4.953.154,00  ", 4953154.0, "With whitespace"),
        ("1.234,56", 1234.56, "With decimal places"),
        ("", 0.0, "Empty string"),
        (None, 0.0, "None input"),
        ("Rp 0", 0.0, "Zero without comma"),
        ("100", 100.0, "Simple integer"),
        ("100,50", 100.50, "Integer with decimal"),
    ]

    print("Testing parse_indonesian_currency()\n")
    print("=" * 80)

    passed = 0
    failed = 0

    for input_val, expected, description in test_cases:
        result = parse_indonesian_currency(input_val)
        status = "✅ PASS" if result == expected else "❌ FAIL"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} | Input: {repr(input_val):25} → Expected: {expected:12.2f} | Got: {result:12.2f}")
        print(f"       | Description: {description}")
        print()

    print("=" * 80)
    print(f"\nResults: {passed} passed, {failed} failed out of {len(test_cases)} tests")

    if failed == 0:
        print("\n🎉 All tests passed!")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed!")
        return False


if __name__ == "__main__":
    success = test_parse_indonesian_currency()
    sys.exit(0 if success else 1)
