#!/bin/bash
# Deploy Supabase Edge Functions after code changes
# Run from project root: bash supabase/deploy.sh

cd "$(dirname "$0")/.." || exit 1

echo "Deploying Supabase Edge Functions..."
echo ""

# Deploy Solcast function
echo "1. Deploying fetch-solcast..."
supabase functions deploy fetch-solcast
if [ $? -eq 0 ]; then
  echo "✓ fetch-solcast deployed"
else
  echo "✗ fetch-solcast deployment failed"
  exit 1
fi

echo ""

# Deploy Agile Prices function
echo "2. Deploying fetch-agile-prices..."
supabase functions deploy fetch-agile-prices
if [ $? -eq 0 ]; then
  echo "✓ fetch-agile-prices deployed"
else
  echo "✗ fetch-agile-prices deployment failed"
  exit 1
fi

echo ""

# Deploy Demand function
echo "3. Deploying fetch-demand..."
supabase functions deploy fetch-demand
if [ $? -eq 0 ]; then
  echo "✓ fetch-demand deployed"
else
  echo "✗ fetch-demand deployment failed"
  exit 1
fi

echo ""
echo "=========================================="
echo "All functions deployed successfully!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Go to Supabase Dashboard → Project Settings → Secrets"
echo "2. Add the following secrets from supabase/.env.example:"
echo "   - SOLCAST_API_KEY"
echo "   - SOLCAST_PV_SYSTEM_ID"
echo "   - FOXESS_API_KEY"
echo "   - SUPABASE_SERVICE_ROLE_KEY (from Dashboard → Settings → API)"
echo ""
echo "3. Set up scheduling in Supabase Scheduler or external scheduler"
echo ""
