import { notFound } from "next/navigation";

/** Any /seller address no other seller route matches. */
export default function UnknownSellerPage() {
  notFound();
}
