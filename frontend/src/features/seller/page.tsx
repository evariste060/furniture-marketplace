import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense, type ReactNode } from "react";
import { getSellerStore } from "@/lib/seller";
import type adminMessages from "../../../messages/admin.json";

type TitleKey = Exclude<keyof (typeof adminMessages)["seller"]["titles"], "suffix">;

/** A seller page's browser-tab title, inside the layout's "%s · Seller dashboard". */
export function sellerMetadata(key: TitleKey): () => Promise<Metadata> {
  return async () => {
    const t = await getTranslations("admin.seller.titles");
    return { title: t(key) };
  };
}

/** Each seller page's own server-side check, as the admin's AdminPage does: nothing renders unless
 * the visitor owns an approved store (the layout shows the reason otherwise). The page streams in
 * its own Suspense boundary. */
export function SellerPage({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div aria-busy="true" className="min-h-[60vh]" />}>
      <Check>{children}</Check>
    </Suspense>
  );
}

async function Check({ children }: { children: ReactNode }) {
  return (await getSellerStore()) ? <>{children}</> : null;
}
