import {
  formatLitres,
  formatMinutes,
  formatMm,
  formatPlanDate,
  forecastAgeNow,
  stageLabel,
} from "@/lib/format";
import type { Plan, PlanDay } from "@/lib/types";
import { warningText } from "@/lib/warnings";

function StaleBadge() {
  return (
    <span className="inline-flex items-center rounded-full border border-amber-line bg-amber-soft px-2.5 py-0.5 text-sm font-medium text-amber-ink">
      Stale forecast
    </span>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-0.5 text-sm text-muted-foreground">
      {children}
    </span>
  );
}

export function Recommendation({ today, fetchedAt }: { today: PlanDay; fetchedAt: string }) {
  const water = today.run_minutes > 0;
  const age = today.stale ? forecastAgeNow(fetchedAt) : null;
  return (
    <section
      aria-labelledby="recommendation"
      className={
        water
          ? "rounded-lg bg-field-deep p-5 text-primary-foreground"
          : "rounded-lg border-2 border-field bg-card p-5"
      }
    >
      <h2 id="recommendation" className="font-semibold leading-none tracking-tight">
        {water ? (
          <>
            <span className="block text-xl">Water for</span>
            <span className="mt-1 block text-5xl">{formatMinutes(today.run_minutes)}</span>
          </>
        ) : (
          <span className="block text-4xl leading-tight">No irrigation today</span>
        )}
      </h2>
      <p className={`mt-3 text-lg ${water ? "" : "text-muted-foreground"}`}>
        {water
          ? `${formatLitres(today.litres)}, ${formatMm(today.irrigation_mm)} of water`
          : `The crop needs ${formatMm(today.etc_mm)} today and the soil holds enough.`}
      </p>
      {(today.stale || today.capped) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {today.stale && <StaleBadge />}
          {today.capped && <Tag>Capped at 24 h</Tag>}
        </div>
      )}
      {age && (
        <p className={`mt-2 text-sm ${water ? "opacity-90" : "text-muted-foreground"}`}>
          {age.charAt(0).toUpperCase() + age.slice(1)}.
        </p>
      )}
    </section>
  );
}

export function WarningsBanner({ warnings }: { warnings: Plan["warnings"] }) {
  const texts = warnings
    .map((w) => warningText(w as { code: string } & Record<string, unknown>))
    .filter((t): t is string => t !== null);
  if (texts.length === 0) return null;
  return (
    <section
      aria-label="Warnings"
      className="rounded-lg border border-amber-line bg-amber-soft p-4 text-amber-ink"
    >
      <ul className="space-y-2">
        {texts.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function rainText(day: PlanDay): string {
  if (day.rain_mm > 0 && day.rain_counted_mm === 0) return `${formatMm(day.rain_mm)} (not counted)`;
  return formatMm(day.rain_mm);
}

function DayCard({ day, isToday }: { day: PlanDay; isToday: boolean }) {
  const water = day.run_minutes > 0;
  return (
    <li className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-lg font-semibold">
          {isToday ? "Today, " : ""}
          {formatPlanDate(day.date)}
        </h3>
        <span className="text-sm text-muted-foreground">{stageLabel(day.stage)}</span>
      </div>
      <p className={`mt-1 text-3xl font-semibold tracking-tight ${water ? "text-field" : "text-muted-foreground"}`}>
        {water ? formatMinutes(day.run_minutes) : "No irrigation"}
      </p>
      {(day.stale || day.capped) && (
        <div className="mt-2 flex flex-wrap gap-2">
          {day.stale && <StaleBadge />}
          {day.capped && <Tag>Capped at 24 h</Tag>}
        </div>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
        <Fact label="Crop needs" value={formatMm(day.etc_mm)} />
        <Fact label="Rain" value={rainText(day)} />
        <Fact label="Water depth" value={formatMm(day.irrigation_mm)} />
        <Fact label="Water volume" value={formatLitres(day.litres)} />
      </dl>
    </li>
  );
}

export function PlanDays({ days }: { days: PlanDay[] }) {
  return (
    <section aria-labelledby="plan-heading">
      <h2 id="plan-heading" className="mb-3 text-2xl font-semibold tracking-tight">
        {days.length}-day plan
      </h2>
      <ol className="space-y-3">
        {days.map((day, i) => (
          <DayCard key={day.date} day={day} isToday={i === 0} />
        ))}
      </ol>
    </section>
  );
}

export function Credit() {
  return (
    <p className="text-sm text-muted-foreground">
      <a
        href="https://open-meteo.com/"
        target="_blank"
        rel="noopener noreferrer"
        className="underline underline-offset-2 hover:text-foreground"
      >
        Weather data by Open-Meteo.com
      </a>
    </p>
  );
}
