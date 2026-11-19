import Link from "next/link";
import { ErrorCard } from "@/components/error-card";
import { Credit, PlanDays, Recommendation, WarningsBanner } from "@/components/plan-view";
import { describeFailure } from "@/lib/plan-errors";
import { fetchPlan } from "@/lib/planner";
import { cropLabel } from "@/lib/group";
import { getPlot } from "@/lib/registry";
import type { Plot } from "@/lib/types";

export const dynamic = "force-dynamic";

const PLAN_DAYS = 7;

async function loadPlot(id: string): Promise<Plot | null> {
  try {
    return await getPlot(id);
  } catch {
    return null; // the plan call reports the problem, the header just falls back
  }
}

export default async function PlotPage(props: PageProps<"/plots/[id]">) {
  const { id } = await props.params;
  const [plot, result] = await Promise.all([loadPlot(id), fetchPlan(id, PLAN_DAYS)]);

  return (
    <div className="space-y-5">
      <header>
        <Link href="/" className="inline-flex min-h-8 items-center text-sm text-muted-foreground underline underline-offset-2">
          All plots
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{plot ? plot.name : "Plot"}</h1>
        {plot && (
          <p className="text-sm text-muted-foreground">
            {cropLabel(plot.crop_id)}, {plot.area_m2.toLocaleString("en-US")} m²
          </p>
        )}
      </header>

      {result.ok ? (
        result.plan.days.length === 0 ? (
          <p className="text-lg text-muted-foreground">No plan available.</p>
        ) : (
          <>
            <Recommendation today={result.plan.days[0]} fetchedAt={result.plan.forecast.fetched_at} />
            <WarningsBanner warnings={result.plan.warnings} />
            <PlanDays days={result.plan.days} />
            <Credit />
          </>
        )
      ) : (
        (() => {
          const view = describeFailure(result.failure);
          return view.backToHome ? (
            <ErrorCard title={view.title} hint={view.hint} actionHref="/" actionLabel="Back to all plots" />
          ) : (
            <ErrorCard title={view.title} hint={view.hint} actionHref={`/plots/${encodeURIComponent(id)}`} />
          );
        })()
      )}
    </div>
  );
}
