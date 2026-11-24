"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { cx } from "@/lib/cx";
import { IconButton } from "./button";

/** Modals on the native <dialog> element: focus moves in and is trapped (the page behind is
 * inert), Escape or the close button closes it, and focus returns to the control that opened it.
 * Drawers also close on a click outside the panel (ADR-011, decided 2026-10-27); dialogs do not,
 * so a stray click never loses a form. The backdrop is the design's navy overlay. */
export function useModal(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
    }
    if (!open && dialog.open) {
      dialog.close();
      if (opener.current?.isConnected) opener.current.focus();
      opener.current = null;
    }
  }, [open]);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const handleCancel = (event: Event) => {
      event.preventDefault();
      onClose();
    };
    dialog.addEventListener("cancel", handleCancel);
    return () => dialog.removeEventListener("cancel", handleCancel);
  }, [onClose]);
  return ref;
}

type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  closeLabel: string;
  /** Shown before the title (e.g. the success tick of the mini cart). */
  icon?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
};

/** Inventory.dc.html "Adjust stock": a centred card, 480px wide. */
export function Dialog({ open, onClose, title, closeLabel, children, footer, className }: ModalProps) {
  const ref = useModal(open, onClose);
  const titleId = useId();
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={cx(
        "m-auto w-[calc(100%-32px)] max-w-[480px] rounded-xl border border-bd bg-card p-0 text-tx shadow-sh2 backdrop:bg-overlay",
        className,
      )}
    >
      {open && (
        <div className="flex flex-col gap-4 p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 id={titleId} className="t-h3">
              {title}
            </h2>
            <IconButton aria-label={closeLabel} bordered={false} onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </IconButton>
          </div>
          {children}
          {footer && <div className="flex justify-end gap-2.5">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}

const SIDES = {
  // MiniCart.dc.html: a 420px panel from the right edge, full height.
  right: "inset-y-0 right-0 left-auto h-full max-h-none w-full max-w-[420px]",
  // MobileMenu.dc.html: a 320px panel from the left edge.
  left: "inset-y-0 left-0 right-auto h-full max-h-none w-[320px] max-w-[calc(100%-48px)]",
  // MobileCategory.dc.html filters: a sheet from the bottom with rounded top corners.
  bottom: "inset-x-0 bottom-0 top-auto h-auto max-h-[85dvh] w-full max-w-none rounded-t-2xl",
} as const;

/** A side or bottom panel. A click on the backdrop (outside the panel) closes it. `header`
 * replaces the title row (the mobile menu shows the logo there); the title is then visually
 * hidden but still names the panel. */
export function Drawer({
  open,
  onClose,
  title,
  closeLabel,
  icon,
  children,
  footer,
  className,
  side = "right",
  header,
}: ModalProps & { side?: keyof typeof SIDES; header?: ReactNode }) {
  const ref = useModal(open, onClose);
  const titleId = useId();
  return (
    // The keyboard equivalent of the backdrop click is Escape (the dialog's cancel event).
    // eslint-disable-next-line jsx-a11y-x/click-events-have-key-events, jsx-a11y-x/no-noninteractive-element-interactions
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className={cx(
        "fixed m-0 border-0 bg-card p-0 text-tx shadow-sh2 backdrop:bg-overlay",
        SIDES[side],
        className,
      )}
    >
      {open && (
        <div className={cx("flex flex-col", side === "bottom" ? "max-h-[85dvh]" : "h-full")}>
          {side === "bottom" && <span aria-hidden="true" className="mx-auto mt-2.5 h-1 w-10 flex-none rounded-sm bg-bd2" />}
          {header ? (
            <>
              <h2 id={titleId} className="sr-only">
                {title}
              </h2>
              <div className="flex h-16 flex-none items-center justify-between gap-2.5 border-b border-bd px-4">
                {header}
                <IconButton aria-label={closeLabel} bordered={false} onClick={onClose}>
                  <X size={22} aria-hidden="true" />
                </IconButton>
              </div>
            </>
          ) : (
            <div className={cx("flex flex-none items-center gap-2.5 border-b border-bd", side === "bottom" ? "px-4 py-3" : "px-6 py-5")}>
              {icon}
              <h2 id={titleId} className={cx("min-w-0 flex-1", side === "bottom" ? "t-h3" : "t-h4")}>
                {title}
              </h2>
              <IconButton aria-label={closeLabel} bordered={false} onClick={onClose}>
                <X size={18} aria-hidden="true" />
              </IconButton>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          {footer && <div className="flex-none border-t border-bd px-4 pt-3 pb-5">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
