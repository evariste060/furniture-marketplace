import { redirect } from "next/navigation";

/** SC-05: administrators moderate products but do not create them; sellers add products to
 * their own store. The old address goes to the product list. */
export default function NewProductPage() {
  redirect("/admin/products");
}
