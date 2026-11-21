import { useId } from "react";
import type { Locale } from "@/i18n/routing";

/** The language's flag on the language button and in its list: Rwanda for Kinyarwanda, the
 * United Kingdom for English (decorative; the flags' own colours). */
export function Flag({ locale }: { locale: Locale }) {
  return locale === "en" ? <UkFlag /> : <RwandaFlag />;
}

function RwandaFlag() {
  return (
    <span aria-hidden="true" className="flex h-3.5 w-5 flex-none flex-col overflow-hidden rounded-[2px]">
      <span className="flex-[2] bg-[#00A1DE]" />
      <span className="flex-1 bg-[#FAD201]" />
      <span className="flex-1 bg-[#20603D]" />
    </span>
  );
}

/** The Union Jack, cropped to the same 20×14 box as the Rwandan flag. */
function UkFlag() {
  // Unique per copy (the header can show the flag more than once), and safe inside url(#…).
  const id = `uk-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg aria-hidden="true" viewBox="0 0 60 30" preserveAspectRatio="xMidYMid slice" className="h-3.5 w-5 flex-none rounded-[2px]">
      <clipPath id={`${id}-cross`}>
        <path d="M30,15 h30 v15 z v15 h-30 z h-30 v-15 z v-15 h30 z" />
      </clipPath>
      <rect width="60" height="30" fill="#012169" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#FFFFFF" strokeWidth="6" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" strokeWidth="4" clipPath={`url(#${id}-cross)`} />
      <path d="M30,0 v30 M0,15 h60" stroke="#FFFFFF" strokeWidth="10" />
      <path d="M30,0 v30 M0,15 h60" stroke="#C8102E" strokeWidth="6" />
    </svg>
  );
}
