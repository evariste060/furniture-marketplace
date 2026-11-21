"use client";

import { inter } from "./fonts";
import "./globals.css";

/** The last resort, when a root layout itself fails (ServerError.dc.html without the store frame
 * or translations, since those are what failed). English and Kinyarwanda side by side. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="bg-page font-sans text-tx">
        <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col items-center justify-center gap-4 px-4 text-center">
          <h1 className="t-h1">Something went wrong on our side</h1>
          <p className="text-lg text-tx2">Please try again in a moment. If you were paying, check your SMS before retrying so you’re not charged twice.</p>
          <p lang="rw" className="text-tx2">
            Habaye ikibazo kuri twe. Ongera ugerageze mu kanya. Niba wariho wishyura, banza urebe SMS mbere yo kongera kugerageza kugira ngo utishyura kabiri.
          </p>
          <button type="button" onClick={reset} className="h-11 cursor-pointer rounded-lg border-0 bg-pri px-5 font-semibold text-white hover:bg-pri-h">
            Try again · Ongera ugerageze
          </button>
          {error.digest && <span className="text-cap text-tx2">Error reference: {error.digest}</span>}
        </main>
      </body>
    </html>
  );
}
