"use client";

import { useQuery } from "@tanstack/react-query";
import { History, Search, TrendingUp, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { usePathname, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import { addRecent, clearRecent, readRecent, removeRecent } from "@/lib/recent-searches";

/** How many popular product names the suggestions show. */
const POPULAR_MAX = 6;

type Variant = "desktop" | "mobile";

type Props = {
  /** The localised /search path the form submits to. */
  action: string;
  variant: Variant;
};

type Option = { kind: "recent" | "popular"; term: string };

/** The header's search (Header.dc.html; SC-07): the same GET form to /search as before, with a
 * suggestions list under it while the field has focus: the shopper's recent searches (kept in
 * this browser) and the best-selling product names (GET /catalog/products, bestselling, loaded the
 * first time the list opens). Typing narrows both lists to what contains the text. One click (or
 * Enter on the highlighted one) searches for it. A search is remembered whenever /search opens
 * with a term, however it was started. On /search the field shows the text searched for. */
export function SearchBox(props: Props) {
  return (
    <Suspense fallback={<SearchForm {...props} q="" recordOnSearchPage={false} />}>
      <LiveSearchBox {...props} />
    </Suspense>
  );
}

function LiveSearchBox(props: Props) {
  const pathname = usePathname();
  const params = useSearchParams();
  const q = pathname === "/search" ? (params.get("q") ?? "") : "";
  return <SearchForm key={q} {...props} q={q} recordOnSearchPage />;
}

function SearchForm({ action, variant, q, recordOnSearchPage }: Props & { q: string; recordOnSearchPage: boolean }) {
  const t = useTranslations("store.header");
  const router = useRouter();
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(q);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [active, setActive] = useState(-1);

  // Remember the search this results page shows (the desktop and phone boxes both run this; the
  // list ignores repeats).
  useEffect(() => {
    if (recordOnSearchPage && q.trim()) addRecent(q);
  }, [q, recordOnSearchPage]);

  const popular = useQuery({
    queryKey: ["search", "popular"],
    enabled: open,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await browserApi.GET("/api/v1/catalog/products", {
        params: { query: { sort_by: "bestselling", sort_direction: "desc", page: 1, size: POPULAR_MAX * 2 } },
      });
      const names = (data?.items ?? []).map((p) => p.name.trim()).filter(Boolean);
      return [...new Set(names)].slice(0, POPULAR_MAX);
    },
  });

  const typed = value.trim().toLocaleLowerCase();
  const matches = (term: string) => !typed || term.toLocaleLowerCase().includes(typed);
  const recentShown = recent.filter(matches);
  const taken = new Set(recentShown.map((r) => r.toLocaleLowerCase()));
  const popularShown = (popular.data ?? []).filter((p) => matches(p) && !taken.has(p.toLocaleLowerCase()));
  const options: Option[] = [...recentShown.map((term) => ({ kind: "recent" as const, term })), ...popularShown.map((term) => ({ kind: "popular" as const, term }))];
  const shown = open && options.length > 0;
  const optionId = (i: number) => `${listId}-${i}`;

  const show = () => {
    setRecent(readRecent());
    setOpen(true);
    setActive(-1);
  };
  const close = () => {
    setOpen(false);
    setActive(-1);
  };
  const choose = (term: string) => {
    setValue(term);
    setRecent(addRecent(term));
    close();
    input.current?.blur();
    router.push(`/search?${new URLSearchParams({ q: term })}`);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (shown) {
        event.preventDefault();
        close();
      }
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!open) {
        show();
        return;
      }
      if (!options.length) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      // -1 is the field itself, between the last option and the first.
      setActive((a) => {
        const next = a + step;
        if (next >= options.length) return -1;
        if (next < -1) return options.length - 1;
        return next;
      });
      return;
    }
    if (event.key === "Enter" && shown && active >= 0 && active < options.length) {
      event.preventDefault();
      choose(options[active].term);
    }
  };

  const field = (
    <input
      ref={input}
      type="search"
      name="q"
      required
      maxLength={160}
      autoComplete="off"
      role="combobox"
      aria-expanded={shown}
      aria-controls={listId}
      aria-autocomplete="list"
      aria-activedescendant={shown && active >= 0 && active < options.length ? optionId(active) : undefined}
      aria-label={variant === "mobile" ? t("searchLabel") : undefined}
      placeholder={t(variant === "mobile" ? "searchPlaceholderShort" : "searchPlaceholder")}
      value={value}
      onChange={(e) => {
        setValue(e.target.value);
        setActive(-1);
        if (!open) show();
      }}
      onFocus={show}
      onClick={() => !open && show()}
      onKeyDown={onKeyDown}
      // The suggestions never take focus (pressing them keeps it here), so leaving the field
      // closes the list.
      onBlur={close}
      className={cx(
        "min-w-0 flex-1 border-0 bg-transparent text-tx outline-none placeholder:text-mut [&::-webkit-search-cancel-button]:cursor-pointer",
        variant === "mobile" ? "text-base" : "text-sm",
      )}
    />
  );

  const panel = (
    <div
      id={listId}
      role="listbox"
      aria-label={t("suggestions")}
      hidden={!shown}
      className="absolute inset-x-0 top-full z-50 mt-1.5 max-h-[min(420px,70dvh)] overflow-y-auto rounded-lg border border-bd bg-card p-1.5 text-left shadow-sh2"
    >
      {recentShown.length > 0 && (
        <div role="group" aria-labelledby={`${listId}-recent`}>
          <div className="flex items-center justify-between px-2.5 pt-1.5 pb-1">
            <span id={`${listId}-recent`} className="t-over text-mut">
              {t("recentSearches")}
            </span>
            <button
              type="button"
              tabIndex={-1}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                setRecent(clearRecent());
                setActive(-1);
                input.current?.focus();
              }}
              className="cursor-pointer border-0 bg-transparent p-0 text-cap font-semibold text-pri-h hover:text-pri-fg"
            >
              {t("clearRecent")}
            </button>
          </div>
          {recentShown.map((term, i) => (
            <SuggestionRow
              key={`r-${term}`}
              id={optionId(i)}
              term={term}
              kind="recent"
              active={active === i}
              onChoose={choose}
              onHover={() => setActive(i)}
              removeLabel={t("removeRecent", { term })}
              onRemove={() => {
                setRecent(removeRecent(term));
                setActive(-1);
                input.current?.focus();
              }}
            />
          ))}
        </div>
      )}
      {popularShown.length > 0 && (
        <div role="group" aria-labelledby={`${listId}-popular`} className={cx(recentShown.length > 0 && "mt-1 border-t border-bd pt-1")}>
          <span id={`${listId}-popular`} className="t-over block px-2.5 pt-1.5 pb-1 text-mut">
            {t("popularSearches")}
          </span>
          {popularShown.map((term, j) => {
            const i = recentShown.length + j;
            return <SuggestionRow key={`p-${term}`} id={optionId(i)} term={term} kind="popular" active={active === i} onChoose={choose} onHover={() => setActive(i)} />;
          })}
        </div>
      )}
    </div>
  );

  if (variant === "mobile") {
    return (
      <form role="search" action={action} className="relative">
        <label className="flex h-[42px] items-center gap-2 rounded-lg bg-subtle px-3 text-mut">
          <Search size={18} aria-hidden="true" />
          {field}
        </label>
        {panel}
      </form>
    );
  }
  return (
    <form role="search" action={action} className="relative flex h-11 min-w-[200px] flex-1 rounded-lg border border-bd focus-within:border-pri">
      <label className="flex flex-1 items-center gap-2.5 px-3.5 text-mut">
        <Search size={18} aria-hidden="true" />
        <span className="sr-only">{t("searchLabel")}</span>
        {field}
      </label>
      <button type="submit" aria-label={t("search")} className="flex w-13 cursor-pointer items-center justify-center rounded-r-[7px] border-0 bg-pri text-white hover:bg-pri-h">
        <Search size={18} aria-hidden="true" />
      </button>
      {panel}
    </form>
  );
}

/** One suggestion: a click (or Enter while it is highlighted) searches for it. A recent search
 * also has a button to forget it. Pressing the mouse keeps the focus in the field. */
function SuggestionRow({
  id,
  term,
  kind,
  active,
  onChoose,
  onHover,
  removeLabel,
  onRemove,
}: {
  id: string;
  term: string;
  kind: Option["kind"];
  active: boolean;
  onChoose: (term: string) => void;
  onHover: () => void;
  removeLabel?: string;
  onRemove?: () => void;
}) {
  const Icon = kind === "recent" ? History : TrendingUp;
  return (
    <div className="group/row relative flex items-center">
      <div
        id={id}
        role="option"
        aria-selected={active}
        // Combobox pattern: the field keeps focus and points here with aria-activedescendant.
        tabIndex={-1}
        onKeyDown={(e) => e.key === "Enter" && onChoose(term)}
        onMouseDown={(e) => e.preventDefault()}
        onMouseEnter={onHover}
        onClick={() => onChoose(term)}
        className={cx(
          "flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
          onRemove && "pr-9",
          active ? "bg-light text-pri-h" : "text-tx hover:bg-page",
        )}
      >
        <Icon size={15} aria-hidden="true" className={cx("flex-none", active ? "text-pri-h" : "text-mut")} />
        <span className="min-w-0 flex-1 truncate">{term}</span>
      </div>
      {onRemove && (
        <button
          type="button"
          tabIndex={-1}
          aria-label={removeLabel}
          title={removeLabel}
          onMouseDown={(e) => e.preventDefault()}
          onClick={onRemove}
          className="absolute right-1.5 flex size-6 cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 text-mut hover:bg-subtle hover:text-tx"
        >
          <X size={14} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
