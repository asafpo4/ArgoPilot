import Link from "next/link";

export function ErrorCard({
  title,
  hint,
  actionHref,
  actionLabel,
}: {
  title: string;
  hint?: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <section
      role="alert"
      className="rounded-lg border-2 border-down bg-card p-5"
    >
      <h2 className="text-xl font-semibold text-down">{title}</h2>
      {hint && <p className="mt-1 text-muted-foreground">{hint}</p>}
      {actionHref && (
        <Link
          href={actionHref}
          className="mt-4 inline-flex min-h-12 items-center rounded-md bg-field px-5 font-medium text-primary-foreground"
        >
          {actionLabel ?? "Try again"}
        </Link>
      )}
    </section>
  );
}
