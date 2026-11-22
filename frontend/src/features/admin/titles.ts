import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type adminMessages from "../../../messages/admin.json";

type TitleKey = keyof (typeof adminMessages)["titles"];

/** An admin page's browser-tab title in the admin's language (admin.titles.*), inside the
 * layout's "%s · Admin · <marketplace name>" (lib/marketplace.ts). */
export function adminMetadata(key: TitleKey): () => Promise<Metadata> {
  return async () => {
    const t = await getTranslations("admin.titles");
    return { title: t(key) };
  };
}
