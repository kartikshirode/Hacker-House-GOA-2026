// One place decides the canonical origin, so OG URLs can never point at
// localhost in production (a real bug in a competitor submission).
export function siteOrigin(): string {
  if (process.env.NEXT_PUBLIC_SITE_URL) return process.env.NEXT_PUBLIC_SITE_URL;
  if (process.env.VERCEL_PROJECT_PRODUCTION_URL)
    return `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`;
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return "http://localhost:3000";
}

// Server-side Blob base URL. Image URLs are always constructed from this plus
// a validated id; the share page never accepts an image URL from outside.
// Falls back to deriving the store hostname from the RW token
// (vercel_blob_rw_{storeId}_{secret}) so no extra env var is needed.
export function blobBase(): string | null {
  if (process.env.BLOB_BASE_URL) return process.env.BLOB_BASE_URL;
  const token = process.env.BLOB_READ_WRITE_TOKEN;
  const storeId = token?.match(/^vercel_blob_rw_([A-Za-z0-9]+)_/)?.[1];
  return storeId ? `https://${storeId.toLowerCase()}.public.blob.vercel-storage.com` : null;
}
