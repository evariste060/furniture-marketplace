import { Banknote } from "lucide-react";
import { cx } from "@/lib/cx";
import type { PaymentMethod } from "@/lib/checkout";

/** The provider marks of CheckoutPayment.dc.html. MTN yellow and Airtel red are the providers'
 * own brand colours (like the flag in the header), not theme colours; cash uses --ok-tx. */
export function PaymentMark({ method, size = "md" }: { method: PaymentMethod; size?: "sm" | "md" | "lg" }) {
  const box = size === "lg" ? "h-10 w-[60px] text-sm" : size === "md" ? "h-[34px] w-[52px] text-cap" : "h-5 px-2 text-cap";
  const base = cx("inline-flex flex-none items-center justify-center font-semibold", size === "sm" ? "rounded-sm" : "rounded-lg", box);
  if (method === "mtn_momo") return <span aria-hidden="true" className={cx(base, "bg-[#FFCC00] text-tx")}>MoMo</span>;
  if (method === "airtel_money") return <span aria-hidden="true" className={cx(base, "bg-[#E40000] text-white")}>airtel</span>;
  return (
    <span aria-hidden="true" className={cx(base, "bg-ok-tx text-white")}>
      <Banknote size={size === "lg" ? 18 : 16} />
    </span>
  );
}
