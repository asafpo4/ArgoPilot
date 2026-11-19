import Link from "next/link";
import { ErrorCard } from "@/components/error-card";
import { cropLabel, groupPlotsByFarm, type FarmWithPlots } from "@/lib/group";
import { listFarms, listPlots } from "@/lib/registry";

export const dynamic = "force-dynamic";

async function load(): Promise<FarmWithPlots[] | null> {
  try {
    const [farms, plots] = await Promise.all([listFarms(), listPlots()]);
    return groupPlotsByFarm(farms, plots);
  } catch {
    return null;
  }
}

export default async function Home() {
  const groups = await load();

  if (groups === null) {
    return (
      <ErrorCard
        title="Registry service is unavailable"
        hint="The farms and plots cannot be loaded right now."
        actionHref="/"
      />
    );
  }
  if (groups.length === 0) {
    return <p className="text-lg text-muted-foreground">No farms yet.</p>;
  }

  return (
    <div className="space-y-8">
      {groups.map(({ farm, plots }) => (
        <section key={farm.id} aria-labelledby={`farm-${farm.id}`}>
          <h2 id={`farm-${farm.id}`} className="mb-3 text-2xl font-semibold tracking-tight">
            {farm.name}
          </h2>
          {plots.length === 0 ? (
            <p className="text-muted-foreground">No plots yet.</p>
          ) : (
            <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
              {plots.map((plot) => (
                <li key={plot.id}>
                  <Link
                    href={`/plots/${plot.id}`}
                    className="flex min-h-16 flex-col justify-center px-4 py-3 hover:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-field"
                  >
                    <span className="text-lg font-medium">{plot.name}</span>
                    <span className="text-sm text-muted-foreground">
                      {cropLabel(plot.crop_id)}, {plot.area_m2.toLocaleString("en-US")} m²
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
