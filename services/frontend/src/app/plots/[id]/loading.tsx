function Block({ className }: { className: string }) {
  return <div aria-hidden className={`animate-pulse rounded-lg bg-muted ${className}`} />;
}

export default function Loading() {
  return (
    <div className="space-y-5" aria-busy="true">
      <p role="status" className="text-lg font-medium">
        Calculating the plan…
      </p>
      <Block className="h-44" />
      {Array.from({ length: 4 }, (_, i) => (
        <Block key={i} className="h-32" />
      ))}
    </div>
  );
}
