"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cx } from "@/lib/cx";

/** Short confirmations after an action ("Saved"). No toast is drawn in the design; this reuses
 * the success banner of Contact.dc.html (green tint, check icon) at the bottom of the screen. */

type Tone = "success" | "error" | "info";
type ToastItem = { id: number; tone: Tone; message: ReactNode };
type ToastApi = { show: (message: ReactNode, tone?: Tone) => void };

const ToastContext = createContext<ToastApi | null>(null);
const DURATION_MS = 5000;

const TONES: Record<Tone, { className: string; Icon: typeof Info }> = {
  success: { className: "bg-ok-bg text-ok-tx", Icon: CheckCircle2 },
  error: { className: "bg-err-bg text-err-tx", Icon: AlertCircle },
  info: { className: "bg-light text-pri-fg", Icon: Info },
};

let nextId = 1;

export function ToastProvider({ children, closeLabel }: { children: ReactNode; closeLabel: string }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback(
    (message: ReactNode, tone: Tone = "success") => {
      const id = nextId++;
      setToasts((all) => [...all.slice(-2), { id, tone, message }]);
      window.setTimeout(() => dismiss(id), DURATION_MS);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext value={api}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-center gap-2 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:items-end"
      >
        {toasts.map(({ id, tone, message }) => {
          const { className, Icon } = TONES[tone];
          return (
            <div
              key={id}
              className={cx(
                "pointer-events-auto flex max-w-[420px] items-start gap-3 rounded-xl px-4 py-3.5 text-sm shadow-sh2",
                className,
              )}
            >
              <Icon size={20} aria-hidden="true" className="flex-none" />
              <span className="flex-1">{message}</span>
              <button
                type="button"
                aria-label={closeLabel}
                onClick={() => dismiss(id)}
                className="flex-none cursor-pointer border-0 bg-transparent p-0 text-current"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside <ToastProvider>");
  return api;
}
