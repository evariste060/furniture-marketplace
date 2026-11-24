"use client";

import { Check, ChevronRight, Copy, Mail, Phone, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";
import { telHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";

/** Shared pieces of the admin "inbox" pages (Orders, Quote requests, Service requests; layout owner
 * 2026-11-18): status cards that filter a table of records, rows with quick contact actions, and a
 * side drawer holding the record's details and actions. */

const AVATAR_TONES = ["bg-light text-pri-h", "bg-pur-bg text-pur", "bg-ok-bg text-ok-tx", "bg-warn-bg text-warn-tx", "bg-err-bg text-err-tx"];

/** "AU" for Aline Uwase. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase() || "?";
}

/** The same colour for the same person on every visit. */
export function avatarTone(seed: string): string {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return AVATAR_TONES[hash % AVATAR_TONES.length]!;
}

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "flex flex-none items-center justify-center rounded-full font-semibold",
        avatarTone(name),
        size === "sm" && "size-7 text-[11px]",
        size === "md" && "size-10 text-sm",
        size === "lg" && "size-14 text-lg",
      )}
    >
      {initials(name)}
    </span>
  );
}

export type StatusCard = { key: string; Icon: LucideIcon; chip: string; ring: string; label: string; hint: string; count?: number; pulse?: boolean };

/** One card per status with its count: the pipeline at a glance, and the table's status filter. */
export function StatusCards({
  label,
  cards,
  value,
  onChange,
  className,
}: {
  label: string;
  cards: StatusCard[];
  value: string;
  onChange: (key: string) => void;
  className: string;
}) {
  return (
    <div role="group" aria-label={label} className={cx("grid gap-3", className)}>
      {cards.map(({ key, Icon, chip, ring, label: name, hint, count, pulse }) => {
        const on = key === value;
        return (
          <button
            key={key || "all"}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(key)}
            className={cx(
              "group flex min-w-0 cursor-pointer flex-col gap-3 rounded-xl border bg-card p-4 text-left shadow-sh transition-[box-shadow,border-color,translate] duration-200 hover:-translate-y-0.5 hover:shadow-lift motion-reduce:hover:translate-y-0",
              on ? cx("border-transparent ring-2", ring) : "border-bd hover:border-bd2",
            )}
          >
            <span className="flex items-center justify-between gap-2">
              <span aria-hidden="true" className={cx("flex size-9 items-center justify-center rounded-lg", chip)}>
                <Icon size={18} />
              </span>
              {pulse && <span aria-hidden="true" className="size-2.5 animate-pulse rounded-full bg-warn motion-reduce:animate-none" />}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              {count === undefined ? <Skeleton className="h-8 w-12" /> : <b className="t-h2 m-0 leading-8 tabular-nums">{count.toLocaleString("en-US")}</b>}
              <span className="truncate text-sm font-semibold text-tx">{name}</span>
              <span className="text-cap leading-4 text-tx2">{hint}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** The table card's title row: the chosen status's icon, its name, the total, and a slot on the right. */
export function ListHeading({ Icon, chip, title, total, children }: { Icon: LucideIcon; chip: string; title: string; total?: number; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bd px-5 py-4 max-sm:px-4">
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className={cx("flex size-8 items-center justify-center rounded-lg", chip)}>
          <Icon size={16} />
        </span>
        <h2 className="m-0 text-base font-semibold">{title}</h2>
        {total !== undefined && <span className="rounded-full bg-subtle px-2 py-0.5 text-cap font-semibold text-tx2 tabular-nums">{total}</span>}
      </div>
      {children}
    </div>
  );
}

/** A table row: highlighted (with a bar on the left) while its record is open in the drawer. */
export function rowClass(selected: boolean, fresh = false): string {
  return cx("transition-colors", selected ? "bg-light shadow-[inset_4px_0_0_var(--color-pri)]" : fresh ? "bg-warn-bg/25 hover:bg-page" : "hover:bg-page");
}

const ICON_BUTTON = buttonClasses({ variant: "neutral", size: "sm", square: true, className: "px-0!" });

/** A row's quick actions: WhatsApp (new tab, when there is a number) and open the drawer.
 * Calling is in the drawer (owner, 2026-11-18). */
export function RowActions({ whatsapp, whatsappLabel, openLabel, onOpen }: { whatsapp?: string | null; whatsappLabel?: string; openLabel: string; onOpen: () => void }) {
  const t = useTranslations("admin.inbox");
  return (
    <div className="flex items-center justify-end gap-1">
      {whatsapp && (
        <a href={whatsapp} target="_blank" rel="noopener noreferrer" aria-label={`${whatsappLabel} ${t("newTab")}`} title={t("whatsapp")} className={ICON_BUTTON}>
          <WhatsAppIcon size={16} aria-hidden="true" className="text-ok-tx" />
        </a>
      )}
      <Button variant="neutral" size="sm" square className="px-0!" onClick={onOpen} aria-label={openLabel} title={t("open")}>
        <ChevronRight size={16} aria-hidden="true" />
      </Button>
    </div>
  );
}

/** The drawer's top card: who, badges, when, and the big Call / WhatsApp / Email buttons (each
 * one only when the person gave that way to reach them). */
export function DrawerHeader({
  name,
  badges,
  meta,
  phone,
  phoneText,
  whatsapp,
  email,
}: {
  name: string;
  badges: ReactNode;
  meta: ReactNode;
  phone?: string | null;
  phoneText?: string;
  whatsapp?: string | null;
  email?: string | null;
}) {
  const t = useTranslations("admin.inbox");
  const ways = (phone ? 2 : 0) + (email ? 1 : 0);
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-bd bg-linear-to-br from-light to-card p-4">
      <div className="flex items-center gap-3">
        <Avatar name={name} size="lg" />
        <div className="flex min-w-0 flex-col gap-1">
          <b className="truncate text-lg font-bold text-head">{name}</b>
          <span className="flex flex-wrap items-center gap-2">{badges}</span>
          <span className="text-cap text-tx2">{meta}</span>
        </div>
      </div>
      {ways > 0 && (
        <div className={cx("grid gap-2", ways === 3 ? "sm:grid-cols-3" : ways === 2 ? "grid-cols-2" : "grid-cols-1")}>
          {phone && (
            <a href={telHref(phone)} className={buttonClasses({ size: "sm", className: "min-w-0" })}>
              <Phone size={16} aria-hidden="true" />
              {t("call")}
            </a>
          )}
          {phone && whatsapp && (
            <a href={whatsapp} target="_blank" rel="noopener noreferrer" className={buttonClasses({ variant: "whatsapp", size: "sm", className: "min-w-0" })}>
              <WhatsAppIcon size={16} aria-hidden="true" />
              {t("whatsapp")}
              <span className="sr-only"> {t("newTab")}</span>
            </a>
          )}
          {email && (
            <a href={`mailto:${email}`} className={buttonClasses({ variant: "neutral", size: "sm", className: "min-w-0" })}>
              <Mail size={16} aria-hidden="true" className="text-pur" />
              {t("email")}
            </a>
          )}
        </div>
      )}
      {ways > 0 && <span className="text-cap break-words text-tx2">{[phone && phoneText, email].filter(Boolean).join(" · ")}</span>}
    </div>
  );
}

/** A reference or number that copies itself on click. */
export function CopyChip({ value, label }: { value: string; label: string }) {
  const t = useTranslations("admin.inbox");
  const toast = useToast();
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.show(t("copied"));
    } catch {
      toast.show(t("copyFailed"), "error");
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      className="inline-flex cursor-pointer items-center gap-1 rounded-md border-0 bg-card/80 px-1.5 py-0.5 font-mono text-cap text-tx2 ring-1 ring-bd hover:text-tx"
    >
      {value}
      <Copy size={12} aria-hidden="true" />
    </button>
  );
}

/** A titled block in the drawer. */
export function DrawerSection({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-cap font-semibold tracking-wide text-tx2 uppercase">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A grey box of facts (use inside a <dl>). */
export const FACTS = "m-0 grid gap-3 rounded-xl border border-bd bg-page p-4 sm:grid-cols-2";

export function Fact({ Icon, label, wide = false, children }: { Icon: LucideIcon; label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={cx("flex items-start gap-2.5", wide && "sm:col-span-2")}>
      <span aria-hidden="true" className="flex size-8 flex-none items-center justify-center rounded-lg bg-card text-pri-h ring-1 ring-bd">
        <Icon size={15} />
      </span>
      <div className="flex min-w-0 flex-col">
        <dt className="text-cap font-semibold text-tx2">{label}</dt>
        <dd className="m-0 text-sm font-medium break-words">{children}</dd>
      </div>
    </div>
  );
}

/** A path of steps: done ones ticked, the current one ringed. `at` is the current step's index
 * (-1 when the record is off the path); `finished` ticks the current step too. */
export function Stepper({ label, steps, at, finished = false }: { label: string; steps: { key: string; label: string }[]; at: number; finished?: boolean }) {
  return (
    <ol className="m-0 flex list-none items-center gap-1 p-0" aria-label={label}>
      {steps.map((s, i) => {
        const done = i < at || (i === at && finished);
        const current = i === at && !finished;
        return (
          <li key={s.key} aria-current={i === at ? "step" : undefined} className="flex min-w-0 flex-1 flex-col items-center gap-1.5 text-center">
            <span className="flex w-full items-center">
              <span className={cx("h-0.5 flex-1", i === 0 ? "bg-transparent" : i <= at ? "bg-ok-tx" : "bg-bd")} />
              <span
                aria-hidden="true"
                className={cx(
                  "flex size-8 flex-none items-center justify-center rounded-full text-cap font-semibold",
                  done && "bg-ok-tx text-white",
                  current && "bg-pri text-white ring-4 ring-light",
                  !done && !current && "border border-bd2 bg-card text-tx2",
                )}
              >
                {done ? <Check size={15} /> : i + 1}
              </span>
              <span className={cx("h-0.5 flex-1", i === steps.length - 1 ? "bg-transparent" : i < at ? "bg-ok-tx" : "bg-bd")} />
            </span>
            <span className={cx("max-w-full truncate text-cap", i === at ? "font-semibold text-head" : "text-tx2")}>{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** A dated line on the drawer's activity timeline. */
export function TimelineItem({ Icon, label, at, note }: { Icon: LucideIcon; label: string; at: string; note?: string | null }) {
  return (
    <li className="relative flex items-start gap-3 py-1.5 pl-5">
      <span aria-hidden="true" className="absolute top-2 -left-[9px] flex size-4 items-center justify-center rounded-full bg-card text-tx2 ring-2 ring-bd">
        <Icon size={9} />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-cap text-tx2">{formatDate(at, "dateTime")}</span>
        {note && <span className="text-sm break-words text-tx2">{note}</span>}
      </span>
    </li>
  );
}

export function Timeline({ children }: { children: ReactNode }) {
  return <ol className="m-0 flex list-none flex-col gap-0 border-l-2 border-bd pl-0">{children}</ol>;
}
