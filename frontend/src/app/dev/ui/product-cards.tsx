import { ListingCard } from "@/components/store/listing-card";
import { ProductCard } from "@/components/store/product-card";
import { Card } from "@/components/ui/card";
import { getProducts } from "@/lib/api/catalogue";

/** ProductCard and ListingCard in their states, with real products from the dev API (no sample
 * data): regular, discounted, "New" without a button, and out of stock. Ratings stay empty until
 * reviews part 2 adds approved reviews, so every card shows the no-rating state. */
export async function ProductCards() {
  const pick = async (query: Parameters<typeof getProducts>[0]) => (await getProducts({ ...query, size: 1 }).catch(() => null))?.items[0];
  const [featured, deal, newest, out] = await Promise.all([
    pick({ featured: true, on_sale: false }),
    pick({ on_sale: true }),
    pick({ sort_by: "newest" }),
    pick({ in_stock: false }),
  ]);
  if (!featured && !deal && !newest) {
    return (
      <Card padding={24}>
        <p className="text-sm text-tx2">Start the API and load the development seed to see the product cards.</p>
      </Card>
    );
  }
  return (
    <Card padding={24} className="flex flex-col gap-4">
      <h3 className="t-h3">ProductCard · regular, discount, New (no button)</h3>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {featured && <ProductCard product={featured} />}
        {deal && <ProductCard product={deal} />}
        {newest && <ProductCard product={newest} isNew showButton={false} />}
      </div>
      <h3 className="t-h3">ListingCard · discount, out of stock</h3>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {deal && <ListingCard product={deal} />}
        {(out ?? featured) && <ListingCard product={(out ?? featured)!} />}
      </div>
    </Card>
  );
}
