"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { PageHeader, postFiles, Step, Tile } from "./ui";

type ImportJob = components["schemas"]["ImportJobResponse"];
type Entry = components["schemas"]["ImportErrorEntry"];

const MAX_BYTES = 10 * 1024 * 1024;
const TEMPLATE = "/api/backend/api/v1/staff/imports/template";

/** A CSV of the report rows ("Download errors"), quoted so commas and quotes survive. Cells that
 * a spreadsheet would run as a formula get a leading apostrophe. */
export function reportCsv(rows: readonly (Entry & { kind: string })[], header: readonly string[]): string {
  const cell = (value: string | number | null) => {
    let text = value === null ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  return [header.map(cell).join(","), ...rows.map((r) => [r.kind, r.row, r.field, r.message].map(cell).join(","))].join("\r\n");
}

/** Import.dc.html */
export function ImportView() {
  const t = useTranslations("admin.import");
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [file, setFile] = useState<{ name: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (f: File) => postFiles<ImportJob>("staff/imports", "file", [f]),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "products"] }),
    onError: (error) =>
      setProblem(
        error instanceof ApiError && error.status === 413 ? t("errors.tooLarge") : error instanceof ApiError && error.status === 422 ? t("errors.invalid") : t("errors.failed"),
      ),
  });
  const start = (f: File | undefined) => {
    if (!f || upload.isPending) return;
    setFile({ name: f.name });
    setProblem(null);
    upload.reset();
    if (!/\.(csv|xlsx)$/i.test(f.name)) return setProblem(t("errors.invalid"));
    if (f.size > MAX_BYTES) return setProblem(t("errors.tooLarge"));
    upload.mutate(f);
  };

  const job = upload.data;
  const rows = job ? [...job.errors.map((e) => ({ ...e, kind: t("kinds.error") })), ...job.warnings.map((w) => ({ ...w, kind: t("kinds.warning") }))] : [];
  const step3 = job ? "done" : file ? "now" : "todo";

  const download = () => {
    const csv = reportCsv(rows, [t("columns.kind"), t("columns.row"), t("columns.field"), t("columns.problem")]);
    const url = URL.createObjectURL(new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${job?.filename.replace(/\.(csv|xlsx)$/i, "") ?? "import"}-report.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="grid gap-4 md:grid-cols-3">
        <Step n={1} state="done" title={t("steps.template")} body={t("steps.templateBody")}>
          <span className="mt-1 flex flex-wrap gap-2">
            <a href={`${TEMPLATE}?format=xlsx`} className={buttonClasses({ variant: "outline", size: "sm" })}>
              {t("templateXlsx")}
            </a>
            <a href={`${TEMPLATE}?format=csv`} className={buttonClasses({ variant: "ghost", size: "sm", className: "px-1" })}>
              {t("templateCsv")}
            </a>
          </span>
        </Step>
        <Step n={2} state={file ? "done" : "now"} title={t("steps.upload")} body={t("steps.uploadBody")} />
        <Step n={3} state={step3} title={t("steps.check")} body={t("steps.checkBody")} />
      </div>

      <Card padding={24} className="flex flex-col gap-4">
        {/* Dropping a file is a pointer shortcut; the "browse" button is the keyboard way in. */}
        {/* eslint-disable-next-line jsx-a11y-x/no-static-element-interactions */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            start(e.dataTransfer.files[0]);
          }}
          className={cx("flex flex-col items-center justify-center gap-2 rounded-xl border-[1.5px] border-dashed p-7 text-center", over ? "border-pri bg-light" : "border-bd2 bg-page")}
        >
          <b className="font-semibold">
            {t.rich("drop", {
              browse: (chunks) => (
                <button type="button" disabled={upload.isPending} onClick={() => input.current?.click()} className="cursor-pointer border-0 bg-transparent p-0 font-semibold text-pri-h">
                  {chunks}
                </button>
              ),
            })}
          </b>
          <span className="text-cap text-tx2">{t("dropHint")}</span>
          <input
            ref={input}
            type="file"
            accept=".csv,.xlsx"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              start(f);
            }}
          />
        </div>
        {file && (
          <div className="flex flex-wrap items-center gap-3.5">
            <span
              aria-hidden="true"
              className={cx(
                "flex size-11 items-center justify-center rounded-[10px]",
                problem || job?.status === "failed" ? "bg-err-bg text-err-tx" : "bg-ok-bg text-ok-tx",
              )}
            >
              <FileSpreadsheet size={20} />
            </span>
            <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
              <div className="flex justify-between gap-3 text-sm">
                <b className="font-medium break-all">{file.name}</b>
                <span className="text-tx2">
                  {upload.isPending ? t("processing") : job ? t(job.status === "failed" ? "statusFailed" : "statusDone", { count: job.total_rows }) : problem ? t("statusRejected") : ""}
                </span>
              </div>
              <div role="progressbar" aria-label={t("progressLabel")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={job || problem ? 100 : 30} className="h-2 overflow-hidden rounded-full bg-subtle">
                <span
                  className={cx("block h-full rounded-full", problem || job?.status === "failed" ? "bg-err" : "bg-ok", upload.isPending && "animate-pulse")}
                  style={{ width: job || problem ? "100%" : "30%" }}
                />
              </div>
            </div>
          </div>
        )}
        {problem && (
          <p role="alert" className="text-sm text-err-tx">
            {problem}
          </p>
        )}
        {job && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label={t("tiles.read")} value={job.total_rows} className="bg-page text-tx" />
            <Tile label={t("tiles.imported")} value={job.imported_rows} className="bg-ok-bg text-ok-tx" />
            <Tile label={t("tiles.errors")} value={job.error_rows} className="bg-err-bg text-err-tx" />
            <Tile label={t("tiles.warnings")} value={job.warnings.length} className="bg-warn-bg text-warn-tx" />
          </div>
        )}
      </Card>

      {job && (job.status === "failed" || rows.length > 0) && (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bd px-5 py-4">
            <h2 className="t-h3">{t("report")}</h2>
            {rows.length > 0 && (
              <Button variant="neutral" size="sm" className="gap-2" onClick={download}>
                <Download size={16} aria-hidden="true" />
                {t("download")}
              </Button>
            )}
          </div>
          {job.status === "failed" && <p className="border-b border-bd px-5 py-3 text-sm text-err-tx">{t("failedNote")}</p>}
          <Table>
            <thead>
              <tr>
                <Th>{t("columns.row")}</Th>
                <Th>{t("columns.field")}</Th>
                <Th>{t("columns.problem")}</Th>
              </tr>
            </thead>
            <tbody>
              {job.errors.map((e, i) => (
                <tr key={`e-${i}`}>
                  <Td>{e.row ?? t("fileLevel")}</Td>
                  <Td className="text-tx2">{e.field ?? "—"}</Td>
                  <Td className="text-err-tx">{e.message}</Td>
                </tr>
              ))}
              {job.warnings.map((w, i) => (
                <tr key={`w-${i}`}>
                  <Td>{w.row ?? t("fileLevel")}</Td>
                  <Td className="text-tx2">{w.field ?? "—"}</Td>
                  <Td className="text-warn-tx">
                    <span className="sr-only">{t("kinds.warning")}: </span>
                    {w.message}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {job.errors_truncated && <p className="border-t border-bd px-5 py-3 text-sm text-tx2">{t("truncated", { count: job.error_rows })}</p>}
        </Card>
      )}
    </>
  );
}
