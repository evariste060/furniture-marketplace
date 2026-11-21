import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ConversationView } from "@/features/account/account-messages";
import { supportReference } from "@/features/support/support";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/messages/[reference]">): Promise<Metadata> {
  const { locale, reference } = await params;
  const t = await getTranslations({ locale, namespace: "store.support" });
  return { title: t("conversationTitle", { reference: supportReference(reference) ?? "" }), robots: { index: false } };
}

async function Conversation({ params }: { params: PageProps<"/[locale]/account/messages/[reference]">["params"] }) {
  const reference = supportReference((await params).reference);
  if (!reference) notFound();
  return <ConversationView reference={reference} />;
}

/** /account/messages/[reference]: one support conversation, read in the browser as its owner. */
export default function ConversationPage({ params }: PageProps<"/[locale]/account/messages/[reference]">) {
  return (
    <Suspense fallback={null}>
      <Conversation params={params} />
    </Suspense>
  );
}
