import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";

/** "Sold by <store>" (ADR-014 phase 5): the store's name, linking to its public page. Used on
 * the product cards, the product page and the cart. The store comes from the API's product or
 * cart line, never from the browser. */
export function SoldBy({ store, className }: { store: { name: string; slug: string }; className?: string }) {
  const t = useTranslations("store.soldBy");
  return (
    <span className={cx("text-cap text-tx2", className)}>
      {t.rich("label", {
        store: () => (
          <Link href={`/store/${store.slug}`} className="relative font-medium text-pri-h hover:underline">
            {store.name}
          </Link>
        ),
      })}
    </span>
  );
}
