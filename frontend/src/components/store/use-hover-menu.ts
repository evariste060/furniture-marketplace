"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent as ReactFocusEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

/** Waits before opening, so a cursor crossing the nav on its way down the page opens nothing. */
const OPEN_DELAY = 90;
/** Waits before closing, so a cursor slipping off the trigger or panel edge for a moment (or
 * moving diagonally from the trigger into the panel) does not close the menu. */
const CLOSE_DELAY = 200;
/** Keeps a fixed panel this far from the window edges. */
const EDGE = 16;

export type PanelPosition = { top: number; left: number; width: number };

/** A disclosure menu that opens on hover with a mouse and on click or tap otherwise (touch,
 * pen, keyboard). Escape closes it and returns focus to the trigger; so does a press outside.
 * The panel is position: fixed below the trigger, so a scrolling nav row never clips it. */
export function useHoverMenu({ width }: { width: number }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<PanelPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const timer = useRef<number | undefined>(undefined);

  const cancel = useCallback(() => window.clearTimeout(timer.current), []);
  const later = useCallback(
    (next: boolean, delay: number) => {
      cancel();
      timer.current = window.setTimeout(() => setOpen(next), delay);
    },
    [cancel],
  );
  const close = useCallback(() => {
    cancel();
    setOpen(false);
  }, [cancel]);
  useEffect(() => cancel, [cancel]);

  const onPointerEnter = useCallback(
    (event: ReactPointerEvent) => {
      if (event.pointerType !== "mouse") return;
      if (open) return cancel();
      later(true, OPEN_DELAY);
    },
    [open, cancel, later],
  );
  const onPointerLeave = useCallback(
    (event: ReactPointerEvent) => {
      if (event.pointerType !== "mouse") return;
      later(false, CLOSE_DELAY);
    },
    [later],
  );
  /** A mouse click opens (hover may already have); touch, pen and keyboard toggle. */
  const lastPointer = useRef<string>("");
  const onTriggerPointerDown = useCallback((event: ReactPointerEvent) => {
    lastPointer.current = event.pointerType;
  }, []);
  const onTriggerClick = useCallback(() => {
    const mouse = lastPointer.current === "mouse";
    lastPointer.current = "";
    cancel();
    if (mouse) setOpen(true);
    else setOpen((o) => !o);
  }, [cancel]);

  // Escape and presses outside close the menu.
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  // Below the trigger, as wide as asked but inside the window; follows scrolling and resizing
  // while open (the header is sticky, but the announcement bar above it scrolls away).
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      // The item's left edge (a category's dropdown opens from its name, not from its caret).
      const trigger = (rootRef.current ?? triggerRef.current)?.getBoundingClientRect();
      if (!trigger) return;
      const room = document.documentElement.clientWidth;
      const w = Math.min(width, room - EDGE * 2);
      const left = Math.max(EDGE, Math.min(trigger.left, room - EDGE - w));
      // Below the nav bar (the All Categories box is shorter than the bar).
      const bar = triggerRef.current?.closest("nav")?.getBoundingClientRect();
      setPosition({ top: bar?.bottom ?? trigger.bottom, left, width: w });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { passive: true });
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place);
    };
  }, [open, width]);

  // Focus leaving the whole menu (Tab past the last link) closes it.
  const onBlur = useCallback(
    (event: ReactFocusEvent) => {
      const next = event.relatedTarget as Node | null;
      if (next && !rootRef.current?.contains(next)) close();
    },
    [close],
  );

  return {
    open,
    close,
    position,
    rootRef,
    triggerRef,
    rootProps: { ref: rootRef, onPointerEnter, onPointerLeave, onBlur },
    triggerProps: { ref: triggerRef, onPointerDown: onTriggerPointerDown, onClick: onTriggerClick },
  };
}
