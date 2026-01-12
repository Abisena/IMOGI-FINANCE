#!/bin/bash
# Final Documentation Cleanup Verification Script
# Date: January 12, 2026

echo "🔍 DOCUMENTATION CLEANUP - FINAL VERIFICATION"
echo "=============================================="
echo ""

# Check 1: Archive folder exists
echo "✓ Check 1: Archive folder"
if [ -d "docs/archive" ]; then
    echo "  ✅ docs/archive/ exists"
    DEPRECATED_COUNT=$(ls -1 docs/archive/*.DEPRECATED 2>/dev/null | wc -l)
    echo "  ✅ $DEPRECATED_COUNT deprecated files archived"
else
    echo "  ❌ docs/archive/ NOT FOUND"
    exit 1
fi

echo ""

# Check 2: Key documentation files exist
echo "✓ Check 2: Core documentation files"
CORE_DOCS=(
    "DOCUMENTATION_INDEX.md"
    "00_START_HERE.md"
    "README.md"
    "IMPLEMENTATION_GUIDE.md"
    "REFACTORED_ARCHITECTURE.md"
    "INTERNAL_CHARGE_IMPLEMENTATION_SUMMARY.md"
    "DEPLOYMENT_CHECKLIST_MODULAR.md"
    "QUICK_FIX_WORKFLOW_CREATE_PI.md"
)

for doc in "${CORE_DOCS[@]}"; do
    if [ -f "$doc" ]; then
        echo "  ✅ $doc exists"
    else
        echo "  ❌ $doc MISSING"
    fi
done

echo ""

# Check 3: Old deprecated files still in root (should be moved or deleted)
echo "✓ Check 3: Old files that should be archived"
OLD_FILES=(
    "QUICK_REFERENCE.md"
    "REFACTORING_INDEX.md"
    "REFACTORING_SUMMARY.md"
    "REFACTORING_COMPLETE.md"
    "INTERNAL_CHARGE_APPROVAL_ANALYSIS.md"
    "INTERNAL_CHARGE_BEFORE_AFTER.md"
    "INTERNAL_CHARGE_WORKFLOW_IMPLEMENTATION.md"
    "WORKFLOW_FIX_SUMMARY.md"
    "FINAL_FIX_SUMMARY.md"
)

REMAINING=0
for file in "${OLD_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ⚠️  $file still in root (should archive or delete)"
        REMAINING=$((REMAINING + 1))
    fi
done

if [ $REMAINING -eq 0 ]; then
    echo "  ✅ All deprecated files moved/archived"
else
    echo "  ⚠️  $REMAINING old files still in root"
fi

echo ""

# Check 4: Check for broken links in key docs
echo "✓ Check 4: Link validation"
echo "  Checking DOCUMENTATION_INDEX.md..."
if grep -q "QUICK_REFERENCE\.md\|REFACTORING_INDEX\.md" DOCUMENTATION_INDEX.md 2>/dev/null; then
    echo "  ⚠️  DOCUMENTATION_INDEX.md has links to deprecated files"
else
    echo "  ✅ DOCUMENTATION_INDEX.md links clean"
fi

echo "  Checking 00_START_HERE.md..."
if grep -q "QUICK_REFERENCE\.md\|REFACTORING_INDEX\.md\|REFACTORING_SUMMARY\.md" 00_START_HERE.md 2>/dev/null; then
    echo "  ⚠️  00_START_HERE.md has links to deprecated files"
else
    echo "  ✅ 00_START_HERE.md links clean"
fi

echo ""

# Summary
echo "=============================================="
echo "📊 SUMMARY"
echo "=============================================="
echo "Core docs: ${#CORE_DOCS[@]} files"
echo "Archived: $DEPRECATED_COUNT files"
echo "Old files remaining: $REMAINING files"
echo ""

if [ $REMAINING -gt 0 ]; then
    echo "⚠️  ACTION NEEDED: Move/delete $REMAINING old files from root"
    echo ""
    echo "Recommended action:"
    echo "  mv QUICK_REFERENCE.md REFACTORING_*.md INTERNAL_CHARGE_*.md WORKFLOW_FIX_SUMMARY.md FINAL_FIX_SUMMARY.md docs/archive/"
    echo ""
fi

echo "✅ Verification complete!"
