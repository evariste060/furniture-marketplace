import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ListingHeader, ListingHeaderFallback } from "@/features/listing/listing-header";
import { ListingFallback, ListingResults } from "@/features/listing/listing-results";
import { getCategories } from "@/lib/api/catalogue";
import { categoryTrail as findTrail } from "@/lib/catalogue";

type Props = PageProps<"/[locale]/category/[slug]">;

async function categoryTrail(slug: string) {
  return findTrail(await getCategories(), slug);
}

async function category(slug: string) {
  return (await categoryTrail(slug))?.at(-1) ?? null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const found = await category(slug).catch(() => null);
  return found ? { title: found.name, description: found.description ?? undefined } : {};
}

/** /category/[slug]: Category.dc.html (desktop) and MobileCategory.dc.html (phone), with the
 * compact header (Home / parent / category, then its name); the body is the shared listing with
 * the category as the page's own filter, which includes its subcategories' products (category
 * hierarchy, 2026-11-16). The main category's subcategories are the filters' first group, not
 * links above the listing (owner, 2026-11-17). */
export default function CategoryPage({ params, searchParams }: Props) {
  return (
    <main id="main">
      <Suspense fallback={<ListingHeaderFallback />}>
        <Header params={params} />
      </Suspense>
      <Suspense fallback={<ListingFallback />}>
        <Body params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Header({ params }: Pick<Props, "params">) {
  const { slug } = await params;
  const trail = await categoryTrail(slug);
  const found = trail?.at(-1);
  if (!trail || !found) notFound();
  const parents = trail.slice(0, -1).map((c) => ({ label: c.name, href: `/category/${c.slug}` }));
  return <ListingHeader title={found.name} trail={parents} />;
}

async function Body({ params, searchParams }: Props) {
  const { slug } = await params;
  const trail = await categoryTrail(slug);
  const found = trail?.at(-1);
  if (!trail || !found) return null;
  // The main category's subcategories, on its page and on each subcategory's page.
  const main = trail[0];
  const subs = main.children ?? [];
  const subcategories = subs.length
    ? { main: { name: main.name, slug: main.slug }, items: subs.map((c) => ({ name: c.name, slug: c.slug })), current: found.slug }
    : undefined;
  return <ListingResults searchParams={searchParams} base={{ category: found.slug }} path={`/category/${found.slug}`} subcategories={subcategories} />;
}
