# AgroPilot frontend: plan

Spec: `services/frontend/docs/superpowers/specs/2026-11-19-frontend-design.md`. Model for all tasks: Sonnet. One test run at the end of each task.
Commits: one per task, only after a green full test run done on its own. No push.

## Task 1: scaffold, `src/lib`, main page, status line
- Create the Next.js app in `services/frontend` (App Router, TypeScript, Tailwind, shadcn/ui, ESLint). Add Vitest for pure helpers.
- `.gitignore` covers `.env.local`, `node_modules`, `.next`. Add `.env.example` with the three URLs. Create a local `.env.local` for 8000, 8001, 8002.
- `src/lib/config.ts`: reads the three URLs, fails naming the missing variable.
- `src/lib/registry.ts`: farms and plots, a fetch helper with timeout and `no-store`. `src/lib/health.ts`: parallel `/health`, 1.5 s timeout, never throws.
- `src/lib/types.ts`: registry and plan types from the planner README.
- Root layout with the frontend-design look (fonts, colours, tokens) and the status-line footer.
- `/`: farms with their plots as links, empty states, registry-down error card.
- Done when: `/` shows both seed farms with plots, the status line shows three dots, helper tests pass.

## Task 2: plot page
- `src/lib/planner.ts`: plan call with a 25 s timeout, error mapping from the problem+json `code` and the two fixed detail texts (generic message otherwise), `Retry-After` hint.
- Pure helpers with tests: date formatting from the string in a fixed UTC zone (include a shift case), forecast age from `fetched_at`, warning text, error mapping.
- `/plots/[id]/page.tsx` and `loading.tsx`: header, recommendation card, warnings banner, day cards (need, rain and not-counted, depth, litres, capped, stage), stale badge and age, credit link under the plan, error cards per the spec table, plot name kept when the registry answered.
- Done when: a real plan renders for a seed plot, and an error card shows with the planner or weather stopped.

## Task 3: check and docs
- The 375 px check is done by the user, not by the agent (see below). Fixed `days=7` on the plot page.
- `npm run build` and `npm run lint` pass. `git status` shows no `.env.local`, `node_modules`, `.next`.
- `.env.example` is final. Short `services/frontend/README.md`: what it is, env vars, run, the credit rule, demo tip (PATCH a planting date), tests.
- Add `docs/judgment-log.md` (Suggested / Decided / Why, about 6 entries: day cards instead of a table, warnings above the numbers, error mapping from the code and the two fixed details, dates formatted from the string, timeouts with plan 25 s because the planner can take 16.3 s, credit under the plan).
- No visual check is claimed. The report lists only automated checks (build, lint, tests, git status) and what the user must check by eye at 375 px, with URLs.
- Done when: build, lint and tests pass and the report lists the checks above.
