# frontend

The AgroPilot web app: the farms and their plots, and each plot's 7-day irrigation plan. Next.js (App Router, TypeScript, Tailwind CSS, shadcn/ui).

| Page | Shows |
|---|---|
| `/` | every farm with its plots, each plot links to its page |
| `/plots/{id}` | today's recommendation, warnings, the 7-day plan, the Open-Meteo credit |

Every page has a status line with the state of registry, weather and planner (`GET /health`).

The browser never calls a service. Pages fetch on the server, and all calls live in `src/lib/`.

## Run

Start registry (8000), weather (8001) and planner (8002), then:

```
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000.

## Settings

| Variable | Rule |
|---|---|
| `REGISTRY_URL` | required, `http://` or `https://` URL |
| `WEATHER_URL` | required, used only for the status line |
| `PLANNER_URL` | required, used for the plan |

A missing or invalid variable gives an error that names the variable, never its value. `.env.local` is not committed.

Timeouts are fixed in `src/lib/config.ts`: plan 25 s (the planner can take 16.3 s), registry 5 s, health 1.5 s.

## The credit

The forecast comes from Open-Meteo, whose licence requires the credit "Weather data by Open-Meteo.com" with a link. It is shown, linked, directly under the plan. Do not remove it.

## Demo tip: the planting date

Every seed plot is past its crop cycle, so every plan shows the `planting_date_past_cycle` warning. To see a plan without it, change a planting date in the registry:

```
curl -X PATCH http://127.0.0.1:8000/v1/plots/<plot-id> \
  -H 'content-type: application/json' \
  -d '{"planting_date": "2026-09-01"}'
```

Use a date within the crop's cycle before today.

## Tests

```
npm test
npm run lint
npm run build
```

The tests cover the pure helpers: date formatting (the day never shifts with the machine time zone), forecast age, warning texts, error mapping and config. They need no running service.
