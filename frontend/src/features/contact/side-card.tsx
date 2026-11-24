import type { ReactNode } from "react";

/** A titled white card for the side column of the Contact and Business & bulk orders pages. */
export function SideCard({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4 rounded-xl border border-bd bg-card p-5 shadow-sh">
      <h2 id={id} className="t-h4">
        {title}
      </h2>
      {children}
    </section>
  );
}
