import createClient from "openapi-fetch";
import type { paths } from "./schema";

/** Browser calls go through this app's /api/backend proxy, which adds the credentials from the
 * httpOnly cookies. Paths keep their /api/v1 prefix, e.g. client.GET("/api/v1/cart"). */
export const browserApi = createClient<paths>({ baseUrl: "/api/backend" });
