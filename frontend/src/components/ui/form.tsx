import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

/** .field / .lbl / .inp / .help in tokens-and-components.css. */

const CONTROL =
  "w-full rounded-lg border border-bd bg-card px-3.5 text-base text-tx outline-none placeholder:text-mut " +
  "focus:border-pri focus:shadow-focus disabled:bg-subtle disabled:text-mut " +
  "aria-invalid:border-err";

export function inputClasses(className?: string) {
  return cx(CONTROL, "h-11", className);
}

type FieldProps = {
  label: ReactNode;
  /** Helper text under the control. */
  help?: ReactNode;
  /** Error text; marks the control invalid and replaces the help text. */
  error?: ReactNode;
  className?: string;
  children: (control: { id: string; "aria-describedby"?: string; "aria-invalid"?: true }) => ReactNode;
};

/** A label, one control, and its help or error text, wired together for screen readers. */
export function Field({ label, help, error, className, children }: FieldProps) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? help;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-tx">
        {label}
      </label>
      {children({
        id,
        "aria-describedby": note ? noteId : undefined,
        "aria-invalid": error ? true : undefined,
      })}
      {note && (
        <span id={noteId} className={cx("text-cap", error ? "text-err-fg" : "text-mut")}>
          {note}
        </span>
      )}
    </div>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={inputClasses(className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(CONTROL, "min-h-[110px] resize-y py-3", className)} {...props} />;
}

const CHEVRON =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2364748B' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")";

export function Select({ className, style, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cx(CONTROL, "h-11 appearance-none bg-[length:18px] bg-[right_12px_center] bg-no-repeat pr-10", className)}
      style={{ backgroundImage: CHEVRON, ...style }}
      {...props}
    />
  );
}

/** .prefix: a Rwandan mobile number after a fixed +250. */
export function PhoneInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div
      className={cx(
        "flex h-11 items-center overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri focus-within:shadow-focus has-aria-invalid:border-err",
        className,
      )}
    >
      <span className="flex h-full items-center border-r border-bd bg-page px-3 text-base text-tx2" aria-hidden="true">
        +250
      </span>
      <input type="tel" inputMode="tel" autoComplete="tel-national" className="h-full min-w-0 flex-1 border-0 px-3.5 text-base outline-none" {...props} />
    </div>
  );
}

type ChoiceProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode };

/** .chk: a native checkbox with its label. */
export function Checkbox({ label, className, ...props }: ChoiceProps) {
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-2 text-sm text-tx", className)}>
      <input type="checkbox" className="m-0 size-4 flex-none accent-pri" {...props} />
      {label}
    </label>
  );
}

/** A native radio button with its label (same look as .chk). */
export function Radio({ label, className, ...props }: ChoiceProps) {
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-2 text-sm text-tx", className)}>
      <input type="radio" className="m-0 size-4 flex-none accent-pri" {...props} />
      {label}
    </label>
  );
}

/** .opt with .radio: a large selectable option (delivery, payment, adjustment type). The native
 * radio is visually hidden but keeps keyboard and screen-reader behaviour. */
export function RadioOption({ label, className, ...props }: ChoiceProps) {
  return (
    <label
      className={cx(
        "flex cursor-pointer items-center gap-3.5 rounded-xl border border-bd bg-card p-4",
        "has-checked:border-2 has-checked:border-pri has-checked:bg-light has-checked:p-[15px]",
        "has-focus-visible:outline-2 has-focus-visible:outline-pri",
        className,
      )}
    >
      <input type="radio" className="peer sr-only" {...props} />
      <span
        aria-hidden="true"
        className="size-5 flex-none rounded-full border-[1.5px] border-bd2 bg-card peer-checked:border-6 peer-checked:border-pri"
      />
      {label}
    </label>
  );
}
