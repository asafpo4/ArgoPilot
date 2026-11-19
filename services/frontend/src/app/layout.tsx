import type { Metadata } from "next";
import { Bricolage_Grotesque } from "next/font/google";
import "./globals.css";
import { StatusLine } from "@/components/status-line";

const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
});

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AgroPilot",
  description: "Irrigation plans for your plots",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${bricolage.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <header className="border-b border-border bg-field-deep text-primary-foreground">
          <div className="mx-auto w-full max-w-2xl px-4 py-3 text-lg font-semibold tracking-tight">
            AgroPilot
          </div>
        </header>
        <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-6">
          {children}
        </main>
        <StatusLine />
      </body>
    </html>
  );
}
