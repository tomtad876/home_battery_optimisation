#!/bin/bash
# Deploy Supabase Edge Functions after code changes
# Run from project root: bash supabase/deploy.sh

cd "$(dirname "$0")/.." || exit 1

# --- Guard: make sure the active Supabase credential can actually see THIS project ---
# This machine has two Supabase accounts. The shared ~/.supabase/access-token
# belongs to the chef-romaine account (thomas.davis@hotmail.co.uk), which has no
# access to the battery project, so deploys silently 403 unless the battery
# account's token is supplied. SUPABASE_ACCESS_TOKEN overrides the stored file.
PROJECT_REF="$(cat supabase/.temp/project-ref 2>/dev/null || true)"
if [ -z "$PROJECT_REF" ]; then
  echo "ERROR: no linked project (supabase/.temp/project-ref missing). Run 'supabase link' first."
  exit 1
fi
if ! supabase projects list 2>/dev/null | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' | grep -q "$PROJECT_REF"; then
  cat <<EOF
ERROR: the active Supabase CLI credential cannot see project '$PROJECT_REF'.

This machine has two Supabase accounts. The shared ~/.supabase/access-token
belongs to the chef-romaine account (thomas.davis@hotmail.co.uk), which has no
access to the battery project. Supply the battery account's token instead
(tom.a.davis@bath.edu) — the env var overrides the stored file:

    SUPABASE_ACCESS_TOKEN=sbp_... bash supabase/deploy.sh

Generate a token at: Supabase dashboard (signed in as tom.a.davis@bath.edu)
                      -> Account -> Access Tokens.
EOF
  exit 1
fi

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
