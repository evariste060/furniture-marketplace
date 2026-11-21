import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { GuestConversationView } from "@/features/support/guest-conversation";
import { supportKey, supportReference } from "@/features/support/support";

export async function generateMetadata({ params }: PageProps<"/[locale]/support/[reference]/[key]">): Promise<Metadata> {
  const { locale, reference } = await params;
  const t = await getTranslations({ locale, namespace: "store.support" });
  // The key is a secret: never indexed, never sent on as a referrer.
  return { title: t("conversationTitle", { reference: supportReference(reference) ?? "" }), robots: { index: false }, referrer: "no-referrer" };
}

async function Conversation({ params }: { params: PageProps<"/[locale]/support/[reference]/[key]">["params"] }) {
  const { reference, key } = await params;
  const ref = supportReference(reference);
  const linkKey = supportKey(key);
  if (!ref || !linkKey) notFound();
  return <GuestConversationView reference={ref} linkKey={linkKey} />;
}

/** /support/[reference]/[key]: a support conversation by its private link, for senders without an
 * account (the link is shown after sending and put in each reply email). */
export default function SupportConversationPage({ params }: PageProps<"/[locale]/support/[reference]/[key]">) {
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex max-w-[880px] flex-col gap-5 pt-10 pb-16 max-sm:pt-5">
        <Suspense fallback={null}>
          <Conversation params={params} />
        </Suspense>
      </div>
    </main>
  );
}
