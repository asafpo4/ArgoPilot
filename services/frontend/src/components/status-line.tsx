import { checkHealth } from "@/lib/health";

const LABELS = [
  ["registry", "Registry"],
  ["weather", "Weather"],
  ["planner", "Planner"],
] as const;

export async function StatusLine() {
  const health = await checkHealth();
  return (
    <footer className="border-t border-border bg-muted">
      <ul
        aria-label="Service status"
        className="mx-auto flex w-full max-w-2xl flex-wrap gap-x-5 gap-y-1 px-4 py-3 text-sm text-muted-foreground"
      >
        {LABELS.map(([key, label]) => (
          <li key={key} className="flex items-center gap-2">
            <span
              aria-hidden
              className={`size-2.5 rounded-full ${health[key] ? "bg-ok" : "bg-down"}`}
            />
            {label} {health[key] ? "up" : "down"}
          </li>
        ))}
      </ul>
    </footer>
  );
}
