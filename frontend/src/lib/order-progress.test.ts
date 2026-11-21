import { describe, expect, it } from "vitest";
import { orderProgress, statusTime } from "./order-progress";

const base = {
  created_at: "2026-10-24T08:24:00Z",
  status_history: [
    { status: "received" as const, reason: null, created_at: "2026-10-24T08:24:00Z" },
    { status: "confirmed" as const, reason: null, created_at: "2026-10-24T08:26:00Z" },
    { status: "processing" as const, reason: null, created_at: "2026-10-26T07:10:00Z" },
    { status: "dispatched" as const, reason: null, created_at: "2026-10-26T09:45:00Z" },
  ],
};
const momo = { method: "mtn_momo" as const, status: "succeeded" as const, amount: 1, created_at: base.created_at };
const cash = { method: "cash_on_delivery" as const, status: "pending" as const, amount: 1, created_at: base.created_at };

describe("orderProgress", () => {
  it("marks the steps up to the status done and the next one current", () => {
    const steps = orderProgress({ ...base, status: "dispatched", payment: momo });
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "done", "done", "now"]);
    expect(steps[3]!.at).toBe("2026-10-26T09:45:00Z");
    expect(steps[4]!.at).toBeNull();
  });

  it("waits for mobile money before the paid step", () => {
    const steps = orderProgress({ ...base, status_history: base.status_history.slice(0, 1), status: "received", payment: { ...momo, status: "pending" } });
    expect(steps.map((s) => s.state)).toEqual(["done", "now", "todo", "todo", "todo"]);
  });

  it("counts a confirmed cash order as confirmed, not paid", () => {
    const steps = orderProgress({ ...base, status_history: base.status_history.slice(0, 2), status: "confirmed", payment: cash });
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "now", "todo", "todo"]);
  });

  it("is all done once delivered", () => {
    const history = [...base.status_history, { status: "delivered" as const, reason: null, created_at: "2026-10-26T15:00:00Z" }];
    const steps = orderProgress({ ...base, status_history: history, status: "delivered", payment: cash });
    expect(steps.every((s) => s.state === "done")).toBe(true);
    expect(statusTime({ status_history: history }, "delivered")).toBe("2026-10-26T15:00:00Z");
  });
});
