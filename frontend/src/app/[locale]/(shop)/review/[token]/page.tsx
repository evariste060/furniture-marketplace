import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { WriteReview } from "@/features/reviews/write-review";

export async function generateMetadata({ params }: PageProps<"/[locale]/review/[token]">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.review" });
  // The token is a secret: never indexed, never sent on as a referrer.
  return { title: t("metaTitle"), robots: { index: false }, referrer: "no-referrer" };
}

async function Review({ params }: { params: PageProps<"/[locale]/review/[token]">["params"] }) {
  const raw = (await params).token;
  // Tokens are URL-safe base64; anything else is answered as an unknown link by the page.
  const token = /^[A-Za-z0-9_-]{20,200}$/.test(raw) ? raw : "invalid-link-0000000000";
  return <WriteReview token={token} />;
}

/** /review/[token] (WriteReview.dc.html), with the thank-you, expired and already-reviewed states. */
export default function ReviewPage({ params }: PageProps<"/[locale]/review/[token]">) {
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex max-w-[880px] flex-col gap-5 pt-10 pb-16 max-sm:pt-5">
        <Suspense fallback={null}>
          <Review params={params} />
        </Suspense>
      </div>
    </main>
  );
}
