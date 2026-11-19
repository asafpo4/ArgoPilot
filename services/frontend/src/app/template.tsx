import { Suspense } from "react";
import { StatusLine } from "@/components/status-line";

// A template is rendered again on every navigation, a layout is not.
// The status line lives here so it shows the current state of the services after each click.
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <>
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-6">{children}</main>
      <Suspense fallback={<footer className="h-12 border-t border-border bg-muted" />}>
        <StatusLine />
      </Suspense>
    </>
  );
}
