import { notFound } from "next/navigation";

/** Any /admin address no other admin route matches. */
export default function UnknownAdminPage() {
  notFound();
}
