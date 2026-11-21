import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { imageRemotePatterns, hasLocalImageHost } from "./src/lib/image-hosts";
import { clientIpConfig } from "./src/lib/client-ip-config";

// Signed client IPs (ADR-006, 2026-11-13): a CLIENT_IP_SOURCE without a usable signing secret
// stops the build and the server here, instead of running without the shopper's address.
clientIpConfig();

const remotePatterns = imageRemotePatterns(process.env.IMAGE_REMOTE_PATTERNS);

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  cacheLife: {
    // Public catalogue data (categories, products, banners): about a minute, fetched at request
    // time. `next build` never needs the backend: the reads in src/lib/api/catalogue.ts wait for
    // connection() first, so the prerender leaves them out.
    catalogue: { stale: 30, revalidate: 60, expire: 120 },
  },
  images: {
    // One width list everywhere (ADR-009): the optimizer locally, a CDN loader later.
    deviceSizes: [400, 800, 1600],
    imageSizes: [64, 128, 256],
    qualities: [75],
    remotePatterns,
    // In development the images come from the API on localhost, which the optimizer refuses by
    // default. Allowed only when a configured image host is itself local.
    dangerouslyAllowLocalIP: hasLocalImageHost(remotePatterns),
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default createNextIntlPlugin("./src/i18n/request.ts")(nextConfig);
