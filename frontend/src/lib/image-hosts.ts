/** Image hosts allowed for next/image, read from IMAGE_REMOTE_PATTERNS by next.config.ts.
 * Kept free of Next.js imports so the config can load it. */

export type ImagePattern = {
  protocol: "http" | "https";
  hostname: string;
  port: string;
  pathname: string;
  search: "";
};

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Comma-separated URL patterns, e.g. "http://localhost:8000/media/**". */
export function imageRemotePatterns(value: string | undefined): ImagePattern[] {
  return (value ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      const url = new URL(entry);
      const protocol = url.protocol.replace(":", "");
      if (protocol !== "http" && protocol !== "https") {
        throw new Error(`IMAGE_REMOTE_PATTERNS: unsupported protocol in ${entry}`);
      }
      return { protocol, hostname: url.hostname, port: url.port, pathname: url.pathname, search: "" };
    });
}

export function hasLocalImageHost(patterns: ImagePattern[]): boolean {
  return patterns.some((pattern) => LOCAL_HOSTS.has(pattern.hostname));
}
