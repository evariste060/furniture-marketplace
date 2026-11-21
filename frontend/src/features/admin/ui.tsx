"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import NextLink from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { pageWindow } from "@/components/ui/pagination";
import { Card } from "@/components/ui/card";
import { ProductImage } from "@/components/ui/product-image";
import { ApiError } from "@/lib/api/errors";
import { cx } from "@/lib/cx";
import { IMAGE_SIZES, type ApiImage } from "@/lib/images";

/** Pieces every admin page shares (the .adm-body patterns of the admin designs). */

type ApiResult<T> = { data?: T; error?: unknown; response: Response };

/** The data of an API call, or an ApiError with the backend's code. */
export async function must<T>(call: Promise<ApiResult<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw ApiError.from(response.status, error);
  return data as T;
}

export function PageHeader({
  title,
  back,
  description,
  actions,
  badges,
}: {
  title: ReactNode;
  /** A detail page's way back to its list. */
  back?: { label: string; href: string };
  description?: ReactNode;
  actions?: ReactNode;
  badges?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        {back && (
          <NextLink href={back.href} className="group flex w-fit items-center gap-1 text-sm font-medium text-tx2 no-underline hover:text-pri-h">
            <ChevronLeft size={16} aria-hidden="true" className="transition-transform duration-150 group-hover:-translate-x-0.5 motion-reduce:transition-none" />
            {back.label}
          </NextLink>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="t-h1 break-words">{title}</h1>
          {badges}
        </div>
        {description && <div className="text-tx2">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
    </div>
  );
}

export function LoadError({ onRetry, className }: { onRetry?: () => void; className?: string }) {
  const t = useTranslations("admin.common");
  return (
    <div role="alert" className={cx("flex flex-wrap items-center justify-between gap-3 rounded-xl border border-err-bd bg-err-bg px-5 py-4 text-err-tx", className)}>
      <span>{t("loadError")}</span>
      {onRetry && (
        <Button variant="neutral" size="sm" onClick={onRetry}>
          {t("retry")}
        </Button>
      )}
    </div>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-10 text-center text-tx2">
        {children}
      </td>
    </tr>
  );
}

/** The URL's query as the page's filter state, so lists can be shared and Back works. */
export function useListParams() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const get = useCallback((key: string) => params.get(key) ?? "", [params]);
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const hrefWith = useCallback(
    (changes: Record<string, string | number | null | undefined>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      if (!("page" in changes)) next.delete("page"); // a new filter starts at page 1
      const query = next.toString();
      return query ? `${pathname}?${query}` : pathname;
    },
    [params, pathname],
  );
  const set = useCallback((changes: Record<string, string | number | null | undefined>) => router.replace(hrefWith(changes), { scroll: false }), [router, hrefWith]);
  return { get, page, set, hrefWith };
}

/** "Showing 1–10 of 142" and the page links (Orders.dc.html footer). */
export function ListFooter({ page, size, total, hrefFor }: { page: number; size: number; total: number; hrefFor: (page: number) => string }) {
  const t = useTranslations("admin.common");
  if (total === 0) return null;
  const pages = Math.max(1, Math.ceil(total / size));
  const from = (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  const square = "w-9 px-0";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd px-5 py-3.5 text-sm text-tx2">
      <span>{t("showing", { from, to, total })}</span>
      {pages > 1 && (
        <nav aria-label={t("pagination.nav")} className="flex items-center gap-1.5">
          <PageLink
            href={page > 1 ? hrefFor(page - 1) : undefined}
            label={t("pagination.previous")}
            className={buttonClasses({
              variant: "neutral",
              size: "sm",
              className: square,
            })}
          >
            <ChevronLeft size={14} aria-hidden="true" />
          </PageLink>
          {pageWindow(page, pages).map((n, i) =>
            n === null ? (
              <span key={`gap-${i}`} aria-hidden="true">
                …
              </span>
            ) : (
              <NextLink
                key={n}
                href={hrefFor(n)}
                scroll={false}
                aria-label={t("pagination.page", { page: n })}
                aria-current={n === page ? "page" : undefined}
                className={buttonClasses({
                  variant: n === page ? "primary" : "neutral",
                  size: "sm",
                  className: square,
                })}
              >
                {n}
              </NextLink>
            ),
          )}
          <PageLink
            href={page < pages ? hrefFor(page + 1) : undefined}
            label={t("pagination.next")}
            className={buttonClasses({
              variant: "neutral",
              size: "sm",
              className: square,
            })}
          >
            <ChevronRight size={14} aria-hidden="true" />
          </PageLink>
        </nav>
      )}
    </div>
  );
}

function PageLink({ href, label, className, children }: { href?: string; label: string; className: string; children: ReactNode }) {
  if (!href)
    return (
      <span aria-disabled="true" aria-label={label} role="link" className={cx(className, "pointer-events-none opacity-45")}>
        {children}
      </span>
    );
  return (
    <NextLink href={href} scroll={false} aria-label={label} className={className}>
      {children}
    </NextLink>
  );
}

/** A product photo in its .imgbox, or the neutral placeholder when there is none. */
export function Thumb({ image, size = 40, alt = "" }: { image?: ApiImage | null; size?: number; alt?: string }) {
  return (
    <span className="inline-flex flex-none items-center justify-center rounded-lg border border-bd bg-white" style={{ width: size, height: size }}>
      <ProductImage image={image ?? null} sizes={IMAGE_SIZES.thumb} alt={alt} iconSize={Math.round(size / 2.4)} className="size-[calc(100%-8px)] rounded-md bg-white" />
    </span>
  );
}

/** The list search box (.inp with a search icon): applies after a short pause or on Enter. */
export function SearchBox({
  label,
  placeholder,
  value,
  onSearch,
  className,
}: {
  label: string;
  placeholder: string;
  value: string;
  onSearch: (q: string) => void;
  className?: string;
}) {
  const [text, setText] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    // The URL changed (Back, a link): show its query.
    setSynced(value);
    setText(value);
  }
  const latest = useRef(onSearch);
  useEffect(() => {
    latest.current = onSearch;
  });
  useEffect(() => {
    if (text.trim() === value) return;
    const timer = setTimeout(() => latest.current(text.trim()), 400);
    return () => clearTimeout(timer);
  }, [text, value]);
  return (
    <label
      className={cx(
        "flex h-[38px] max-w-[360px] min-w-0 flex-[1_1_260px] items-center gap-2 rounded-lg border border-bd bg-white px-3 text-tx2 transition-[border-color,box-shadow] duration-150 hover:not-focus-within:border-bd2 focus-within:border-pri focus-within:shadow-focus motion-reduce:transition-none",
        className,
      )}
    >
      <Search size={16} aria-hidden="true" />
      <input
        type="search"
        aria-label={label}
        placeholder={placeholder}
        value={text}
        maxLength={160}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSearch(text.trim());
        }}
        className="min-w-0 flex-1 border-0 bg-transparent text-sm text-tx outline-none"
      />
    </label>
  );
}

/** The filter row above admin tables. */
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3 border-b border-bd px-5 py-4 max-sm:px-4">{children}</div>;
}

/** Status tabs that set a URL filter (Orders.dc.html .tabs): toggle buttons, as each one
 * filters the same table. */
export function FilterTabs<T extends string>({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { id: T | ""; label: ReactNode }[];
  value: T | "";
  onChange: (id: T | "") => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-7 overflow-x-auto overflow-y-hidden border-b border-bd px-5 max-sm:gap-5 max-sm:px-4">
      {items.map((item) => {
        const on = item.id === value;
        return (
          <button
            key={item.id || "all"}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(item.id)}
            className={cx(
              "-mb-px cursor-pointer border-0 border-b-2 bg-transparent px-0.5 py-3 text-base font-semibold whitespace-nowrap transition-colors duration-150 motion-reduce:transition-none",
              on ? "border-pri text-pri-h" : "border-transparent text-tx2 hover:border-bd2 hover:text-tx",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

/** A 422's field messages by field name (the last part of each `loc` under "body"). The admin is
 * English-only, so the backend's English messages are shown as they are. */
export function bodyFieldErrors(error: unknown): Record<string, string> {
  const found: Record<string, string> = {};
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.details)) return found;
  for (const detail of error.details as { loc?: unknown; msg?: unknown }[]) {
    const loc = Array.isArray(detail?.loc) ? detail.loc : [];
    if (loc[0] !== "body" || typeof detail.msg !== "string") continue;
    const key = String(loc[loc.length - 1] ?? "");
    if (key && !(key in found)) found[key] = detail.msg.replace(/^Value error, /, "");
  }
  return found;
}

/** Posts files as multipart/form-data through the backend proxy (uploads are not JSON, so they
 * don't go through the typed client). Field name and path follow the backend route. */
export async function postFiles<T>(path: string, field: string, files: File[]): Promise<T> {
  const body = new FormData();
  for (const file of files) body.append(field, file, file.name);
  const response = await fetch(`/api/backend/api/v1/${path}`, { method: "POST", body });
  const json: unknown = await response.json().catch(() => null);
  if (!response.ok) throw ApiError.from(response.status, json);
  return json as T;
}

/** A numbered step card (Import.dc.html). */
export function Step({ n, title, body, state, children }: { n: number; title: string; body: string; state: "done" | "now" | "todo"; children?: ReactNode }) {
  return (
    <Card padding={20} className="flex items-start gap-3">
      <span
        aria-hidden="true"
        className={cx(
          "inline-flex size-8 flex-none items-center justify-center rounded-full text-[13px] font-semibold",
          state === "done" && "bg-ok-tx text-white",
          state === "now" && "bg-pri text-white",
          state === "todo" && "border border-bd2 bg-white text-tx2",
        )}
      >
        {n}
      </span>
      <span className="flex flex-col gap-1">
        <b className="font-semibold">{title}</b>
        <span className="text-sm text-tx2">{body}</span>
        {children}
      </span>
    </Card>
  );
}

/** A coloured count tile (Import.dc.html results). */
export function Tile({ label, value, className }: { label: string; value: number; className: string }) {
  return (
    <div className={cx("flex flex-col gap-0.5 rounded-xl p-3.5", className)}>
      <span className="text-cap">{label}</span>
      <b className="t-h3">{value}</b>
    </div>
  );
}
