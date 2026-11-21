"use client";

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { ImageUp, RotateCcw } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { useStaffAccess } from "./access";
import { must, PageHeader, postFiles, Step, Tile } from "./ui";

type Job = components["schemas"]["JobResponse"];
type JobItem = components["schemas"]["JobItemResponse"];

/** The backend's limits (app/services/bulk_images.py). */
export const BATCH_SIZE = 20;
const FILE_MAX_BYTES = 5 * 1024 * 1024;
const EXTENSIONS = /\.(jpe?g|png|webp)$/i;

/** Splits files into upload batches of at most BATCH_SIZE. */
export function batches<T>(files: readonly T[], size = BATCH_SIZE): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < files.length; i += size) out.push(files.slice(i, i + size));
  return out;
}

/** "unknown_slug: No product has …" → { code, message }. */
export function splitItemError(error: string | null): { code: string | null; message: string | null } {
  if (!error) return { code: null, message: null };
  const match = /^([a-z_]+): ([\s\S]*)$/.exec(error);
  return match ? { code: match[1], message: match[2] } : { code: null, message: error };
}

/** A file the browser can already tell will be refused. */
function localProblem(file: File): "too_large" | "not_image" | null {
  if (!EXTENSIONS.test(file.name)) return "not_image";
  if (file.size > FILE_MAX_BYTES) return "too_large";
  return null;
}

type Batch = { key: number; names: string[]; jobId?: string; error?: string };
type Rejected = { name: string; reason: "too_large" | "not_image" };

function sendBatch(files: File[]): Promise<Job> {
  return postFiles<Job>("staff/products/bulk-images", "files", files);
}

/** Bulk photo upload (no design; built from the Import.dc.html pattern, awaiting approval). */
export function BulkImagesView() {
  const t = useTranslations("admin.bulk");
  const { can } = useStaffAccess();
  const manage = can("catalog:manage");
  const client = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [batchList, setBatchList] = useState<Batch[]>([]);
  const [rejected, setRejected] = useState<Rejected[]>([]);
  const [sending, setSending] = useState(false);
  // A clock for the "worker seems stopped" note, ticking only while something is sent.
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (batchList.length === 0) return;
    const tick = () => setNow(Date.now());
    const timer = setInterval(tick, 10_000);
    return () => clearInterval(timer);
  }, [batchList.length]);

  const jobs = useQueries({
    queries: batchList
      .filter((b) => b.jobId)
      .map((b) => ({
        queryKey: ["admin", "job", b.jobId],
        queryFn: () => must(browserApi.GET("/api/v1/staff/jobs/{job_id}", { params: { path: { job_id: b.jobId! } } })),
        refetchInterval: (query: { state: { data?: Job } }) => (query.state.data?.state === "finished" ? false : 2000),
      })),
  });
  const jobData = jobs.map((j) => j.data).filter((j): j is Job => Boolean(j));

  const start = async (files: File[]) => {
    const good: File[] = [];
    const bad: Rejected[] = [];
    for (const file of files) {
      const problem = localProblem(file);
      if (problem) bad.push({ name: file.name, reason: problem });
      else good.push(file);
    }
    setRejected(bad);
    setBatchList([]);
    if (good.length === 0) return;
    setSending(true);
    const groups = batches(good);
    for (const [i, group] of groups.entries()) {
      const names = group.map((f) => f.name);
      try {
        const job = await sendBatch(group);
        client.setQueryData(["admin", "job", job.id], job);
        setBatchList((prev) => [...prev, { key: i, names, jobId: job.id }]);
      } catch (error) {
        const message =
          error instanceof ApiError && error.status === 507 ? t("errors.storage") : error instanceof ApiError && error.status === 413 ? t("errors.tooLarge") : t("errors.batch");
        setBatchList((prev) => [...prev, { key: i, names, error: message }]);
      }
    }
    setSending(false);
    void client.invalidateQueries({ queryKey: ["admin", "products"] });
  };

  const retry = useMutation({
    mutationFn: async () => {
      for (const job of jobData) {
        if (!job.items.some(retryable)) continue;
        const fresh = await must(browserApi.POST("/api/v1/staff/jobs/{job_id}/retry-failed", { params: { path: { job_id: job.id } } }));
        client.setQueryData(["admin", "job", job.id], fresh);
      }
    },
    onSuccess: () => {
      toast.show(t("retried"));
      void client.invalidateQueries({ queryKey: ["admin", "job"] });
    },
    onError: () => toast.show(t("errors.retry"), "error"),
  });

  const items = jobData.flatMap((j) => j.items);
  const total = batchList.reduce((n, b) => n + b.names.length, 0) + rejected.length;
  const done = items.filter((i) => i.state === "done").length;
  const failed = items.filter((i) => i.state === "failed").length + rejected.length + batchList.filter((b) => b.error).reduce((n, b) => n + b.names.length, 0);
  const waiting = Math.max(0, total - done - failed);
  const finished = total > 0 && waiting === 0 && !sending;
  const percent = total ? Math.round(((done + failed) / total) * 100) : 0;
  const stalled = now > 0 && jobData.some((j) => j.state === "queued" && now - Date.parse(j.created_at) > 60_000);

  return (
    <>
      <PageHeader title={t("title")} back={{ label: t("backToProducts"), href: "/admin/products" }} description={t("description")} />
      <div className="grid gap-4 md:grid-cols-3">
        <Step n={1} title={t("steps.name")} body={t("steps.nameBody")} state="done">
          <NextLink href="/admin/products?view=missing-images" className="text-sm font-medium">
            {t("steps.missing")}
          </NextLink>
        </Step>
        <Step n={2} title={t("steps.upload")} body={t("steps.uploadBody")} state={total ? "done" : "now"} />
        <Step n={3} title={t("steps.check")} body={t("steps.checkBody")} state={total ? "now" : "todo"} />
      </div>

      <Card padding={24} className="flex flex-col gap-4">
        {manage && (
          // Dropping files is a pointer shortcut; the "browse" button is the keyboard way in.
          // eslint-disable-next-line jsx-a11y-x/no-static-element-interactions
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              if (!sending) void start([...e.dataTransfer.files]);
            }}
            className={cx("flex flex-col items-center justify-center gap-2 rounded-xl border-[1.5px] border-dashed p-7 text-center", over ? "border-pri bg-light" : "border-bd2 bg-page")}
          >
            <ImageUp size={24} className="text-tx2" aria-hidden="true" />
            <b className="font-semibold">
              {t.rich("drop", {
                browse: (chunks) => (
                  <button type="button" disabled={sending} onClick={() => input.current?.click()} className="cursor-pointer border-0 bg-transparent p-0 font-semibold text-pri-h">
                    {chunks}
                  </button>
                ),
              })}
            </b>
            <span className="text-cap text-tx2">{t("dropHint")}</span>
            <input
              ref={input}
              type="file"
              multiple
              accept=".jpg,.jpeg,.png,.webp"
              hidden
              onChange={(e) => {
                const files = [...(e.target.files ?? [])];
                e.target.value = "";
                if (files.length) void start(files);
              }}
            />
          </div>
        )}
        {total > 0 && (
          <>
            <div className="flex flex-col gap-1.5">
              <div className="flex justify-between text-sm">
                <b className="font-medium">{t("progress", { batches: batchList.length, total: Math.ceil((total - rejected.length) / BATCH_SIZE) })}</b>
                <span className="text-tx2">{finished ? t("finished") : t("percent", { percent })}</span>
              </div>
              <div role="progressbar" aria-label={t("progressLabel")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-2 overflow-hidden rounded-full bg-subtle">
                <span className={cx("block h-full rounded-full", failed && finished ? "bg-warn" : "bg-ok")} style={{ width: `${percent}%` }} />
              </div>
              {stalled && <span className="text-cap text-warn-tx">{t("stalled")}</span>}
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Tile label={t("tiles.files")} value={total} className="bg-page" />
              <Tile label={t("tiles.done")} value={done} className="bg-ok-bg text-ok-tx" />
              <Tile label={t("tiles.waiting")} value={waiting} className="bg-light text-pri-h" />
              <Tile label={t("tiles.failed")} value={failed} className="bg-err-bg text-err-tx" />
            </div>
          </>
        )}
      </Card>

      {total > 0 && (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bd px-5 py-4">
            <h2 className="t-h3">{t("report")}</h2>
            {manage && items.some(retryable) && (
              <Button size="sm" className="gap-2" disabled={retry.isPending} onClick={() => retry.mutate()}>
                <RotateCcw size={16} aria-hidden="true" />
                {t("retry")}
              </Button>
            )}
          </div>
          <Table>
            <thead>
              <tr>
                <Th>{t("columns.file")}</Th>
                <Th>{t("columns.product")}</Th>
                <Th>{t("columns.position")}</Th>
                <Th>{t("columns.result")}</Th>
              </tr>
            </thead>
            <tbody>
              {rejected.map((r) => (
                <tr key={`local-${r.name}`}>
                  <Td className="font-medium break-all">{r.name}</Td>
                  <Td className="text-tx2">—</Td>
                  <Td className="text-tx2">—</Td>
                  <Td>
                    <Result tone="soft-err" label={t("outcome.failed")} note={t(`local.${r.reason}`)} />
                  </Td>
                </tr>
              ))}
              {batchList.map((b) =>
                b.error ? (
                  b.names.map((name) => (
                    <tr key={`${b.key}-${name}`}>
                      <Td className="font-medium break-all">{name}</Td>
                      <Td className="text-tx2">—</Td>
                      <Td className="text-tx2">—</Td>
                      <Td>
                        <Result tone="soft-err" label={t("outcome.failed")} note={b.error} />
                      </Td>
                    </tr>
                  ))
                ) : (
                  <JobRows key={b.key} job={jobData.find((j) => j.id === b.jobId)} names={b.names} />
                ),
              )}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}

/** A failed item the worker can try again (its file was stored). */
function retryable(item: JobItem): boolean {
  return item.state === "failed" && !(item.result as { final?: boolean } | null)?.final;
}

function JobRows({ job, names }: { job?: Job; names: string[] }) {
  const t = useTranslations("admin.bulk");
  if (!job)
    return names.map((name) => (
      <tr key={name}>
        <Td className="font-medium break-all">{name}</Td>
        <Td className="text-tx2">—</Td>
        <Td className="text-tx2">—</Td>
        <Td>
          <Result tone="soft-neutral" label={t("outcome.sending")} />
        </Td>
      </tr>
    ));
  return [...job.items]
    .sort((a, b) => a.item_index - b.item_index)
    .map((item) => {
      const input = item.input as { filename?: string; product_name?: string; position?: number };
      const outcome = (item.result as { outcome?: string } | null)?.outcome;
      const { code, message } = splitItemError(item.error);
      const known = ["added", "replaced", "unchanged"].includes(outcome ?? "");
      const label =
        item.state === "done"
          ? known
            ? t(`outcome.${outcome as "added" | "replaced" | "unchanged"}`)
            : t("outcome.done")
          : item.state === "failed"
            ? t("outcome.failed")
            : item.state === "processing"
              ? t("outcome.processing")
              : t("outcome.queued");
      const tone: BadgeTone = item.state === "done" ? (outcome === "unchanged" ? "soft-neutral" : "soft-ok") : item.state === "failed" ? "soft-err" : "soft-info";
      return (
        <tr key={item.item_index}>
          <Td className="font-medium break-all">{input.filename ?? names[item.item_index] ?? "—"}</Td>
          <Td className="text-tx2">{input.product_name ?? "—"}</Td>
          <Td className="text-tx2">{input.position ?? "—"}</Td>
          <Td>
            <Result tone={tone} label={label} note={message ?? undefined} code={code ?? undefined} />
          </Td>
        </tr>
      );
    });
}

function Result({ tone, label, note, code }: { tone: BadgeTone; label: string; note?: string; code?: string }) {
  return (
    <span className="flex flex-col gap-0.5">
      <span>
        <Badge tone={tone}>{label}</Badge>
      </span>
      {note && (
        <span className="text-cap text-err-tx" title={code}>
          {note}
        </span>
      )}
    </span>
  );
}
