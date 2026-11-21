// Writes docs/frontend/rw-review.md (the storefront) and docs/frontend/rw-review-admin.md (the
// admin): every Kinyarwanda string beside its English source, for approval by a native speaker.
// The Kinyarwanda in messages/rw.json and messages/admin.rw.json is a draft until approved.
// Run: npm run i18n:review (a test fails while either file is out of date).
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("..", import.meta.url);
const read = (name) => JSON.parse(readFileSync(new URL(`messages/${name}.json`, root), "utf8"));
export const OUTPUT = fileURLToPath(new URL("../docs/frontend/rw-review.md", root));
export const OUTPUT_ADMIN = fileURLToPath(new URL("../docs/frontend/rw-review-admin.md", root));

export function flatten(object, prefix = "") {
  return Object.entries(object).flatMap(([key, value]) =>
    value && typeof value === "object" ? flatten(value, `${prefix}${key}.`) : [[`${prefix}${key}`, String(value)]],
  );
}

const cell = (text) => text.replaceAll("|", String.raw`\|`).replaceAll("\n", " ");

export function render(en = read("en"), rw = read("rw")) {
  const english = new Map(flatten(en));
  const rows = flatten(rw).map(([key, value]) => `| \`${key}\` | ${cell(english.get(key) ?? "")} | ${cell(value)} | |`);
  return [
    "# Kinyarwanda review",
    "",
    "Generated from `frontend/messages/en.json` and `frontend/messages/rw.json` by `npm run i18n:review`; do not edit by hand.",
    "",
    "Every Kinyarwanda string on the storefront is a **draft** until a native speaker approves it. Reviewers: write corrections",
    "or \"OK\" in the last column (or in a review comment) and the developer updates `messages/rw.json`. Banner text comes from",
    "the API (`title`, `subtitle`, `cta_label` in `{en, rw}`) and is reviewed in the admin, not here.",
    "",
    `${rows.length} strings.`,
    "",
    "| Key | English | Kinyarwanda (draft) | Reviewer |",
    "| --- | --- | --- | --- |",
    ...rows,
    "",
  ].join("\n");
}

/** The admin's review table: messages/admin.json beside messages/admin.rw.json. */
export function renderAdmin(en = read("admin"), rw = read("admin.rw")) {
  const english = new Map(flatten(en));
  const rows = flatten(rw).map(([key, value]) => `| \`${key}\` | ${cell(english.get(key) ?? "")} | ${cell(value)} | |`);
  return [
    "# Kinyarwanda review: admin",
    "",
    "Generated from `frontend/messages/admin.json` and `frontend/messages/admin.rw.json` by `npm run i18n:review`; do not edit by",
    "hand.",
    "",
    "The admin can be switched to Kinyarwanda from its top bar. Every Kinyarwanda admin string is a **draft** until a native",
    "speaker approves it. Reviewers: write corrections or \"OK\" in the last column (or in a review comment) and the developer",
    "updates `messages/admin.rw.json`.",
    "",
    `${rows.length} strings.`,
    "",
    "| Key | English | Kinyarwanda (draft) | Reviewer |",
    "| --- | --- | --- | --- |",
    ...rows,
    "",
  ].join("\n");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  writeFileSync(OUTPUT, render());
  writeFileSync(OUTPUT_ADMIN, renderAdmin());
  console.log(`Wrote ${OUTPUT} and ${OUTPUT_ADMIN}`);
}
