import { upload } from "@vercel/blob/client";

export interface UploadedPass {
  passUrl: string;
  pagePath: string;
}

/** Upload the pass PNG and its OG crop. Both must land before the intent opens. */
export async function uploadPass(
  passId: string,
  passBlob: Blob,
  ogBlob: Blob,
  meta: { name: string; title: string; seat: number | null },
): Promise<UploadedPass> {
  const opts = {
    access: "public" as const,
    handleUploadUrl: "/api/blob-upload",
  };
  const [pass] = await Promise.all([
    upload(`passes/${passId}.png`, passBlob, opts),
    upload(`og/${passId}.png`, ogBlob, opts),
  ]);
  const params = new URLSearchParams();
  if (meta.name) params.set("n", meta.name);
  if (meta.title) params.set("t", meta.title);
  if (meta.seat !== null) params.set("s", String(meta.seat));
  return { passUrl: pass.url, pagePath: `/pass/${passId}?${params.toString()}` };
}

/** True when the OS can hand this exact payload to another app. */
export function canShareFile(file: File): boolean {
  return (
    typeof navigator !== "undefined" &&
    "canShare" in navigator &&
    navigator.canShare({ files: [file] })
  );
}

/**
 * Native share, called directly in the tap handler. Nothing is awaited before
 * this and no clipboard write shares the tap; both can demand the same
 * transient activation and the second consumer loses.
 */
export function shareFile(file: File): Promise<void> {
  return navigator.share({ files: [file] });
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
