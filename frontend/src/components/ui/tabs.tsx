"use client";

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "@/lib/cx";

export type TabItem = { id: string; label: ReactNode; content: ReactNode };

/** .tabs / .tab: a WAI-ARIA tab list. Arrow keys, Home and End move between tabs. Pass `value` and
 * `onChange` to control the open tab (e.g. to keep it in the URL). */
export function Tabs({
  items,
  label,
  initial,
  value,
  onChange,
  className,
}: {
  items: TabItem[];
  label: string;
  initial?: string;
  value?: string;
  onChange?: (id: string) => void;
  className?: string;
}) {
  const [own, setOwn] = useState(initial ?? items[0]?.id);
  const active = value ?? own;
  const setActive = (id: string) => {
    setOwn(id);
    onChange?.(id);
  };
  const base = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = items.findIndex((item) => item.id === active);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    if (next === null) return;
    event.preventDefault();
    setActive(items[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={label}
        className="flex gap-7 overflow-x-auto overflow-y-hidden border-b border-bd"
      >
        {items.map((item, index) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              ref={(el) => {
                refs.current[index] = el;
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(item.id)}
              onKeyDown={onKeyDown}
              className={cx(
                "-mb-px cursor-pointer border-0 border-b-2 bg-transparent px-0.5 py-3 font-semibold whitespace-nowrap",
                selected ? "border-pri text-pri-fg" : "border-transparent text-tx2",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${base}-panel-${item.id}`}
          aria-labelledby={`${base}-tab-${item.id}`}
          hidden={item.id !== active}
          className="pt-4"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
