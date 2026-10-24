# AGENTS.md

Home battery optimisation — FastAPI + LP optimiser backend, Next.js frontend, Supabase (auth/DB/Edge Functions). Deployed: Vercel (frontend), Render (backend).

## Running locally

See `RUN_LOCALLY.md` for full instructions. Summary:

- Backend: `./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` (always `--reload` — a stale server silently tests old code)
- Frontend: `cd frontend && npm run dev` (needs `NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local` — beware `vercel env pull` overwriting it with the prod URL)
- Local test user: `test@test.com` / `testing123` (local-only test account, no real data)

## Verifying a change (learned the hard way)

- "Run locally" means **two** processes: backend on 8000 *and* `npm run dev` on 3000. With the backend down, every API call fails and the app looks broken — check `curl -s localhost:8000/health` first.
- The browser tools drive a **visible** Edge window. If it is minimised/backgrounded — or the Windows session is locked — pages report `document.visibilityState === 'hidden'`, layout collapses to 0×0 and every click times out (screenshots still look fine, which is what makes it confusing). Check `visibilityState` before blaming the app; bring the tab to the front, or fall back to headless Chromium over CDP (`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --headless=new --remote-debugging-port=9333`), which has no such dependency.
- A **Vercel preview deployment is a different environment**: `NEXT_PUBLIC_API_URL` is per-scope, so a preview can be pointed at `http://localhost:8000` (the viewer's machine) even when Production is correct. Verify the deployed bundle, not just localhost — `curl -s <deploy-url> | grep -o 'onrender.com\|localhost:8000'` on the JS chunks tells you which API it will call.
- **The pre-push hook runs `next build`, which shares `.next` with a running `next dev`.** Pushing while the dev server is up breaks it (500s, `MODULE_NOT_FOUND … pages-manifest.json`). Stop the dev server before pushing, or `rm -rf .next` and restart it after.

## Rules

- **Never push to prod without running locally and checking the change in the browser.** Full deployment workflow + project log live in the brain vault: `projects/business/battery-optimisation.md`.
- Tests: `venv/bin/pytest` + `tsc --noEmit` on changed TypeScript.
- Model routing: this repo defaults to deepseek-v4-pro; `/design` plans on glm-5.3, `/verify` drives the browser check, `/review` reviews the diff, `/test` runs the suite. Policy: brain vault `projects/personal/software-factory.md`.
