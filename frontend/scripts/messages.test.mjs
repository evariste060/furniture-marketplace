// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { OUTPUT, OUTPUT_ADMIN, flatten, render, renderAdmin } from "./rw-review.mjs";

const read = (name) => JSON.parse(readFileSync(new URL(`../messages/${name}.json`, import.meta.url), "utf8"));
// "{name}" or "{name, plural, …}"; plural branches such as "{igicuruzwa #}" are wording, not names.
const placeholders = (text) => [...text.matchAll(/\{(\w+)\s*[,}]/g)].map((m) => m[1]).sort();

describe("messages", () => {
  const en = new Map(flatten(read("en")));
  const rw = new Map(flatten(read("rw")));

  it("has the same keys in English and Kinyarwanda", () => {
    expect([...rw.keys()].sort()).toEqual([...en.keys()].sort());
  });

  it("keeps the same placeholders in both languages", () => {
    for (const [key, text] of en) expect(placeholders(rw.get(key) ?? ""), key).toEqual(placeholders(text));
  });

  it("lists every Kinyarwanda string in docs/frontend/rw-review.md (run npm run i18n:review)", () => {
    expect(readFileSync(OUTPUT, "utf8").replaceAll("\r\n", "\n")).toBe(render());
  });
});

describe("admin messages", () => {
  const en = new Map(flatten(read("admin")));
  const rw = new Map(flatten(read("admin.rw")));
  // Rich-text tags such as <b>…</b> or <browse>…</browse> must survive translation.
  const tags = (text) => [...text.matchAll(/<\/?(\w+)>/g)].map((m) => m[0]).sort();

  it("has the same keys in English and Kinyarwanda", () => {
    expect([...rw.keys()].sort()).toEqual([...en.keys()].sort());
  });

  it("keeps the same placeholders and tags in both languages", () => {
    for (const [key, text] of en) {
      expect(placeholders(rw.get(key) ?? ""), key).toEqual(placeholders(text));
      expect(tags(rw.get(key) ?? ""), key).toEqual(tags(text));
    }
  });

  it("lists every Kinyarwanda admin string in docs/frontend/rw-review-admin.md (run npm run i18n:review)", () => {
    expect(readFileSync(OUTPUT_ADMIN, "utf8").replaceAll("\r\n", "\n")).toBe(renderAdmin());
  });
});
