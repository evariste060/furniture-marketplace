import localFont from "next/font/local";

/** Inter, the design's only typeface, self-hosted (no request to Google Fonts at build or run
 * time). One variable font covers weights 400–800. Source: rsms/inter v4.1
 * (web/InterVariable.woff2), SIL Open Font License 1.1, see fonts/LICENSE.txt. */
export const inter = localFont({
  src: "./fonts/InterVariable.woff2",
  weight: "100 900",
  style: "normal",
  display: "swap",
  variable: "--font-inter",
});
