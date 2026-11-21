"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileText } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { infoPageKey } from "@/lib/info-pages";
import { bodyFieldErrors, FilterTabs, LoadError, must, useListParams } from "./ui";

type StaffPage = components["schemas"]["StaffPage"];
type Version = components["schemas"]["StaffPageVersion"];
type Slug = StaffPage["slug"];
type Lang = "en" | "rw";

/** The backend's page limits (app/models/content.py). */
export const PAGE_LIMITS = { title: 120, body: 50_000 } as const;

const pagesQuery = { queryKey: ["admin", "pages"], queryFn: () => must(browserApi.GET("/api/v1/staff/pages")) };

/** The newest change to either language, for "Updated {date}". */
export function lastUpdated(page: Pick<StaffPage, "en" | "rw">): string | null {
  const dates = [page.en?.updated_at, page.rw?.updated_at].filter((d): d is string => Boolean(d));
  return dates.sort().at(-1) ?? null;
}

/** Whether a Kinyarwanda reader gets the page in Kinyarwanda: both languages written and published. */
export function hasBothLanguages(page: Pick<StaffPage, "en" | "rw">): boolean {
  return Boolean(page.en?.is_published && page.rw?.is_published);
}

function PageRow({ page, href, on }: { page: StaffPage; href: string; on?: boolean }) {
  const t = useTranslations("admin.pages");
  const updated = lastUpdated(page);
  const both = hasBothLanguages(page);
  return (
    <NextLink
      href={href}
      scroll={false}
      aria-current={on ? "page" : undefined}
      className={cx("flex items-center gap-2.5 border-b border-subtle py-2.5 text-tx no-underline last:border-b-0 hover:text-tx", on && "font-semibold")}
    >
      <FileText size={18} aria-hidden="true" className="flex-none text-tx2" />
      <span className="flex min-w-0 grow flex-col">
        <span className="text-sm font-medium">{t(`names.${infoPageKey(page.slug)!}`)}</span>
        <span className="text-cap text-tx2">{updated ? t("updated", { date: formatDate(updated, "date") }) : t("notWritten")}</span>
      </span>
      <Badge tone={both ? "soft-ok" : "soft-warn"}>{both ? t("both") : page.en?.is_published ? t("rwMissing") : t("notLive")}</Badge>
    </NextLink>
  );
}

/** Settings.dc.html's "Policy pages" card on the Store tab; each row opens the page's editor. */
export function PagesSummary() {
  const t = useTranslations("admin.pages");
  const pages = useQuery(pagesQuery);
  return (
    <Card padding={24} className="flex min-w-0 flex-[1_1_300px] flex-col gap-3">
      <h2 className="t-h4">{t("title")}</h2>
      {pages.isError ? (
        <LoadError onRetry={() => pages.refetch()} />
      ) : !pages.data ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : (
        <div className="flex flex-col">
          {pages.data.items.map((page) => (
            <PageRow key={page.slug} page={page} href={`/admin/settings?tab=pages&page=${page.slug}`} />
          ))}
        </div>
      )}
      <span className="text-cap text-tx2">{t("note")}</span>
    </Card>
  );
}

/** The Policy pages tab: the six pages on the left, the chosen one's editor on the right. Settings.dc.html
 * shows the tab but not its contents, so the layout follows the Homepage banners tab. */
export function PagesTab() {
  const t = useTranslations("admin.pages");
  const { get, hrefWith } = useListParams();
  const pages = useQuery(pagesQuery);
  const items = pages.data?.items ?? [];
  const selected = items.find((p) => p.slug === get("page")) ?? items[0];
  return (
    <div className="flex flex-wrap items-start gap-5">
      <Card padding={24} className="flex min-w-0 flex-[1_1_300px] flex-col gap-3 lg:max-w-[380px]">
        {pages.isError ? (
          <LoadError onRetry={() => pages.refetch()} />
        ) : !pages.data ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : (
          <nav aria-label={t("title")} className="flex flex-col">
            {items.map((page) => (
              <PageRow key={page.slug} page={page} href={hrefWith({ tab: "pages", page: page.slug })} on={page.slug === selected?.slug} />
            ))}
          </nav>
        )}
        <span className="text-cap text-tx2">{t("note")}</span>
      </Card>
      {selected && <PageEditor key={selected.slug} page={selected} />}
    </div>
  );
}

function PageEditor({ page }: { page: StaffPage }) {
  const t = useTranslations("admin.pages");
  const [lang, setLang] = useState<Lang>("en");
  const name = t(`names.${infoPageKey(page.slug)!}`);
  return (
    <Card  className="flex min-w-0 flex-[999_1_520px] flex-col">
      <div className="flex flex-col gap-1 px-6 pt-6 pb-2">
        <h2 className="t-h3">{name}</h2>
        <span className="font-mono text-cap text-tx2">/pages/{page.slug}</span>
      </div>
      <FilterTabs
        label={t("langLabel")}
        value={lang}
        onChange={(id) => setLang(id === "rw" ? "rw" : "en")}
        items={(["en", "rw"] as const).map((id) => ({ id, label: page[id] ? t(`lang.${id}`) : t("langMissing", { lang: t(`lang.${id}`) }) }))}
      />
      <VersionForm key={`${page.slug}-${lang}`} slug={page.slug} lang={lang} version={page[lang]} />
    </Card>
  );
}

function VersionForm({ slug, lang, version }: { slug: Slug; lang: Lang; version: Version | null }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [title, setTitle] = useState(version?.title ?? "");
  const [body, setBody] = useState(version?.body ?? "");
  const [published, setPublished] = useState(version?.is_published ?? false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () =>
      must(browserApi.PUT("/api/v1/staff/pages/{slug}", { params: { path: { slug }, query: { lang } }, body: { title: title.trim(), body: body.trim(), is_published: published } })),
    onSuccess: () => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["admin", "pages"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
    },
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (!title.trim()) found.title = t("common.required");
    if (!body.trim()) found.body = t("common.required");
    else if (body.trim().length > PAGE_LIMITS.body) found.body = t("pages.tooLong");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };
  const storePath = `${lang === "rw" ? "/rw" : ""}/pages/${slug}`;

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-4 p-6"
    >
      {!version && <p className="rounded-lg bg-light px-3.5 py-2.5 text-sm text-pri-h">{t(lang === "rw" ? "pages.rwFallback" : "pages.enMissing")}</p>}
      <Field label={t("pages.pageTitle")} error={errors.title}>
        {(c) => <Input {...c} lang={lang} maxLength={PAGE_LIMITS.title} value={title} onChange={(e) => setTitle(e.target.value)} />}
      </Field>
      <Field label={t("pages.body")} error={errors.body} help={t("pages.bodyHelp")}>
        {(c) => <Textarea {...c} lang={lang} rows={18} maxLength={PAGE_LIMITS.body} value={body} onChange={(e) => setBody(e.target.value)} className="font-mono text-sm" />}
      </Field>
      <Toggle checked={published} onChange={setPublished} label={t("pages.published")} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {t("common.saveChanges")}
        </Button>
        {version?.is_published && (
          <a href={storePath} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-medium">
            {t("pages.viewOnStore")}
            <ExternalLink size={14} aria-hidden="true" />
            <span className="sr-only"> {t("pages.newTab")}</span>
          </a>
        )}
        {version && <span className="text-cap text-tx2">{t("pages.updated", { date: formatDate(version.updated_at, "dateTime") })}</span>}
      </div>
    </form>
  );
}
