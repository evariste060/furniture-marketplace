"use client";

import { Building2, ChevronRight, Globe, Palette, Store, Truck, User, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { Drawer } from "@/components/ui/dialog";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import type { CatalogCategory } from "@/lib/catalogue";
import { IMAGE_SIZES } from "@/lib/images";
import { AccountAnchor, LanguageToggle, ThemeToggle, useAccountLink } from "./header-actions";
import { Logo } from "./logo";
import { useMenuState } from "./menu-state";

const ROW_BASE = "flex items-center gap-3 px-4 py-3 hover:bg-page";
const ROW = `${ROW_BASE} text-tx hover:text-tx`;

/** MobileMenu.dc.html: the category menu, a drawer from the left. Each category shows its image
 * (the package placeholder when it has none; owner decision 2026-10-27). */
export function MobileMenu({ categories }: { categories: CatalogCategory[] }) {
  const t = useTranslations("store");
  const { open, setOpen } = useMenuState();
  const close = useCallback(() => setOpen(false), [setOpen]);
  const { signedIn } = useAccountLink();
  return (
    <Drawer
      open={open}
      onClose={close}
      side="left"
      title={t("menu.title")}
      closeLabel={t("menu.close")}
      header={<Logo height={38} alt={t("logoAlt")} />}
    >
      <nav aria-label={t("header.categories")} className="flex min-h-full flex-col">
        <AccountAnchor onClick={close} className="flex items-center gap-3 bg-light p-4 text-head hover:text-head">
          <span className="flex size-9 flex-none items-center justify-center rounded-full bg-card text-pri-fg">
            <User size={18} aria-hidden="true" />
          </span>
          <span className="flex flex-1 flex-col">
            <b className="font-semibold">{t(signedIn ? "menu.myAccount" : "menu.signIn")}</b>
            <span className="text-cap text-tx2">{t(signedIn ? "menu.accountHint" : "menu.signInHint")}</span>
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </AccountAnchor>
        <span className="t-over px-4 pt-4 pb-1.5 text-mut">{t("menu.shopByCategory")}</span>
        <ul className="m-0 list-none p-0">
          {categories.map((c) => (
            <li key={c.id}>
              <Link href={`/category/${c.slug}`} onClick={close} className={ROW}>
                <ProductImage image={c.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} iconSize={16} className="size-7 rounded-md bg-card" />
                <span className="flex-1 font-medium">{c.name}</span>
                <ChevronRight size={16} aria-hidden="true" className="text-mut" />
              </Link>
            </li>
          ))}
          {/* Deals last, in red, as on the category bar (owner, 2026-11-18). */}
          <li>
            <Link href="/deals" onClick={close} className={`${ROW_BASE} text-err-fg hover:text-err-tx`}>
              <span className="flex size-7 items-center justify-center" aria-hidden="true">
                <Zap size={22} />
              </span>
              <span className="flex-1 font-medium">{t("header.deals")}</span>
            </Link>
          </li>
          {/* The existing seller application, as on the category bar (SC-07). */}
          <li>
            <Link href="/account/seller" onClick={close} className={`${ROW_BASE} font-semibold text-pri-h hover:text-pri-fg`}>
              <span className="flex size-7 items-center justify-center" aria-hidden="true">
                <Store size={22} />
              </span>
              <span className="flex-1">{t("header.becomeSeller")}</span>
              <ChevronRight size={16} aria-hidden="true" className="text-mut" />
            </Link>
          </li>
        </ul>
        <span className="t-over mt-2 border-t border-bd px-4 pt-4 pb-1.5 text-mut">{t("menu.help")}</span>
        <Link href="/track" onClick={close} className="flex items-center gap-3 px-4 py-2.5 text-sm text-tx2 hover:text-tx">
          <Truck size={18} aria-hidden="true" />
          {t("menu.trackOrder")}
        </Link>
        <Link href="/contact" onClick={close} className="flex items-center gap-3 px-4 py-2.5 text-sm text-tx2 hover:text-tx">
          <Building2 size={18} aria-hidden="true" />
          {t("menu.business")}
        </Link>
        <span className="flex-1" />
        <div className="flex items-center gap-2 border-t border-bd px-4 pt-4">
          <Palette size={18} aria-hidden="true" className="text-mut" />
          <span className="flex-1 text-sm text-tx2">{t("menu.theme")}</span>
          <ThemeToggle withLabel />
        </div>
        <div className="flex items-center gap-2 p-4">
          <Globe size={18} aria-hidden="true" className="text-mut" />
          <span className="flex-1 text-sm text-tx2">{t("menu.language")}</span>
          <LanguageToggle />
        </div>
      </nav>
    </Drawer>
  );
}
