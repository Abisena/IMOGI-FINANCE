#!/bin/bash
# Budget Control Workflow State Fix - Deployment Script
# Run this script from the frappe-bench directory

set -e  # Exit on error

SITE_NAME="${1:-itb-dev.j.frappe.cloud}"  # Default site or pass as argument
APP_PATH="apps/imogi_finance"

echo "=================================================="
echo "Budget Control Workflow State Fix - Deployment"
echo "=================================================="
echo ""
echo "Site: $SITE_NAME"
echo ""

# Confirm deployment
read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 1
fi

echo ""
echo "Step 1: Backing up current version..."
cd "$APP_PATH"
git stash push -m "Pre-deployment backup $(date +%Y%m%d_%H%M%S)"

echo ""
echo "Step 2: Pulling latest changes..."
git pull

cd ../..

echo ""
echo "Step 3: Running migration..."
bench --site "$SITE_NAME" migrate

echo ""
echo "Step 4: Clearing cache..."
bench --site "$SITE_NAME" clear-cache

echo ""
echo "Step 5: Restarting..."
bench restart || echo "⚠️  Note: bench restart might not work in cloud environments"

echo ""
echo "=================================================="
echo "✅ Deployment completed successfully!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "1. Login to $SITE_NAME"
echo "2. Go to Budget Control Settings"
echo "3. Verify 'Enable Budget Lock' is checked"
echo "4. Create a test Expense Request"
echo "5. Approve it and verify Budget Control Entry is created"
echo ""
echo "Rollback command (if needed):"
echo "  cd $APP_PATH && git stash pop"
echo "  cd ../.. && bench --site $SITE_NAME migrate"
echo ""
