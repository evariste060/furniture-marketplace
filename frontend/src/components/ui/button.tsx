import type { ButtonHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

/** .btn and its variants in tokens-and-components.css. */
export type ButtonVariant =
  | "primary" // btn-p
  | "outline" // btn-o
  | "secondary" // btn-s
  | "ghost" // btn-g
  | "neutral" // btn-n
  | "danger" // btn-d
  | "danger-outline" // btn-do
  | "dark" // btn-dk
  | "white" // btn-w
  | "outline-white" // btn-ow
  | "whatsapp" // btn-wa
  | "whatsapp-outline"; // btn-oa
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-pri text-white hover:bg-pri-h hover:text-white",
  outline: "bg-card text-pri-fg border-pri/45 hover:text-pri-h",
  // WCAG AA: --pri on --light is 4.44:1, so the text uses --pri-h (6.15:1).
  secondary: "border-transparent bg-light text-pri-h hover:text-pri-h",
  ghost: "border-transparent bg-transparent text-pri-fg hover:text-pri-h",
  neutral: "bg-card text-tx border-bd hover:text-tx",
  danger: "border-transparent bg-err text-white hover:text-white",
  "danger-outline": "bg-card text-err-fg border-err-bd hover:text-err-fg",
  dark: "border-transparent bg-navy text-white hover:text-white",
  white: "border-transparent bg-card text-pri-fg hover:text-pri-h",
  "outline-white": "bg-transparent text-white border-white/60 hover:text-white",
  whatsapp: "border-transparent bg-wa text-wa-ink hover:text-wa-ink",
  "whatsapp-outline": "bg-card text-ok-tx border-wa hover:text-ok-tx",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-9 px-3.5 text-sm",
  md: "h-11 px-5 text-base leading-5",
  lg: "h-13 px-[26px] text-btn-lg",
};

export type ButtonStyle = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  /** Square button for a single number or icon (pagination). */
  square?: boolean;
  className?: string;
};

/** The button classes, also for links styled as buttons (<a className={buttonClasses(...)}>). */
export function buttonClasses({
  variant = "primary",
  size = "md",
  block = false,
  square = false,
  className,
}: ButtonStyle = {}): string {
  return cx(
    "inline-flex items-center justify-center gap-2 rounded-lg border font-semibold whitespace-nowrap no-underline cursor-pointer",
    "disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:cursor-not-allowed aria-disabled:opacity-45",
    VARIANTS[variant],
    SIZES[size],
    square && (size === "sm" ? "w-9 px-0" : size === "lg" ? "w-13 px-0" : "w-11 px-0"),
    block && "w-full",
    className,
  );
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & ButtonStyle;

export function Button({ variant, size, block, square, className, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={buttonClasses({ variant, size, block, square, className })} {...props} />;
}

/** .icbtn: a 40px icon-only button. Always pass an aria-label. */
export function IconButton({
  className,
  type = "button",
  bordered = true,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { "aria-label": string; bordered?: boolean }) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex size-10 flex-none cursor-pointer items-center justify-center rounded-lg bg-card text-tx2",
        bordered ? "border border-bd" : "border-0",
        className,
      )}
      {...props}
    />
  );
}
