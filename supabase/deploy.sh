#!/bin/bash
# Deploy Supabase Edge Functions after code changes
# Run from project root: bash supabase/deploy.sh

cd "$(dirname "$0")/.." || exit 1

echo "Deploying Supabase Edge Functions..."
echo ""

# NOTE: --no-verify-jwt is required for all functions invoked by pg_cron.
# The cron uses a legacy HS256 service-role JWT that the function gateway
# rejects under verify_jwt (2026-09-13 incident: fetch-agile-prices silently
# 401'd for days while cron logged "succeeded"). Keep the flag on all crons.

# Deploy Solcast function
echo "1. Deploying fetch-solcast..."
supabase functions deploy fetch-solcast --no-verify-jwt
if [ $? -eq 0 ]; then
  echo "✓ fetch-solcast deployed"
else
  echo "✗ fetch-solcast deployment failed"
  exit 1
fi

echo ""

# Deploy Agile Prices function
echo "2. Deploying fetch-agile-prices..."
supabase functions deploy fetch-agile-prices --no-verify-jwt
if [ $? -eq 0 ]; then
  echo "✓ fetch-agile-prices deployed"
else
  echo "✗ fetch-agile-prices deployment failed"
  exit 1
fi

echo ""

# Deploy Demand function
echo "3. Deploying fetch-demand..."
supabase functions deploy fetch-demand --no-verify-jwt
if [ $? -eq 0 ]; then
  echo "✓ fetch-demand deployed"
else
  echo "✗ fetch-demand deployment failed"
  exit 1
fi

echo ""

# Deploy Optimise-and-push function
echo "4. Deploying optimise-and-push..."
supabase functions deploy optimise-and-push --no-verify-jwt
if [ $? -eq 0 ]; then
  echo "✓ optimise-and-push deployed"
else
  echo "✗ optimise-and-push deployment failed"
  exit 1
fi

# Deploy Fetch-heatpump function
echo "5. Deploying fetch-heatpump..."
supabase functions deploy fetch-heatpump --no-verify-jwt
if [ $? -eq 0 ]; then
  echo "✓ fetch-heatpump deployed"
else
  echo "✗ fetch-heatpump deployment failed"
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
echo "   (Octopus/FoxESS per-user keys live encrypted in provider_config, not here)"
echo ""
echo "3. Set up scheduling in Supabase Scheduler or external scheduler"
echo ""
