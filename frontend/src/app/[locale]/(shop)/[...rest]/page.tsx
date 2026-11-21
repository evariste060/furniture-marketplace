import { notFound } from "next/navigation";

/** Any address no other storefront route matches shows NotFound.dc.html in the store frame. */
export default function UnknownPage() {
  notFound();
}
