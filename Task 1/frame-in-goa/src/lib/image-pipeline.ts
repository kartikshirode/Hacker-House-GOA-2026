// Upload -> decoded, size-capped ImageBitmap. Owns the memory policy:
// 25 MB input cap, 4096 px working cap, explicit close() on every swap.

export const MAX_FILE_BYTES = 25 * 1024 * 1024;
export const MAX_WORKING_EDGE = 4096;
export const PREVIEW_EDGE = 1600;

const HEIC_BRANDS = new Set(["heic", "heix", "hevc", "hevx", "heim", "heis", "mif1", "msf1"]);

// file.type is often empty for HEIC, so sniff the container instead.
export function sniffHeic(bytes: Uint8Array): boolean {
  if (bytes.length < 12) return false;
  const ascii = (off: number, len: number) =>
    String.fromCharCode(...bytes.subarray(off, off + len));
  return ascii(4, 4) === "ftyp" && HEIC_BRANDS.has(ascii(8, 4).toLowerCase());
}

export class PipelineError extends Error {
  constructor(
    message: string,
    public readonly kind: "too-big" | "heic-failed" | "decode-failed",
  ) {
    super(message);
  }
}

let heicWarmup: Promise<unknown> | null = null;

/** Prefetch the HEIC wasm on idle so conversion is warm before anyone picks a photo. */
export function warmHeicConverter(): void {
  if (heicWarmup) return;
  const kick = () => {
    heicWarmup = import("heic-to").catch(() => (heicWarmup = null));
  };
  if ("requestIdleCallback" in window) {
    (window as Window & { requestIdleCallback: (cb: () => void) => void }).requestIdleCallback(kick);
  } else {
    setTimeout(kick, 2000);
  }
}

async function toDecodableBlob(file: File): Promise<Blob> {
  const head = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  if (!sniffHeic(head)) return file;
  try {
    const { heicTo } = await import("heic-to");
    return await heicTo({ blob: file, type: "image/jpeg", quality: 0.9 });
  } catch {
    throw new PipelineError(
      "That HEIC photo would not convert. A JPG, PNG, or a screenshot of it will work.",
      "heic-failed",
    );
  }
}

/**
 * Decode a picked file into a working ImageBitmap, EXIF-upright, capped at
 * MAX_WORKING_EDGE on the long side. Caller owns the bitmap and must close it.
 */
export async function decodePhoto(file: File): Promise<ImageBitmap> {
  if (file.size > MAX_FILE_BYTES) {
    throw new PipelineError("That file is over 25 MB. Most photos are far smaller; try a normal export.", "too-big");
  }
  const blob = await toDecodableBlob(file);
  let full: ImageBitmap;
  try {
    full = await createImageBitmap(blob, { imageOrientation: "from-image" });
  } catch {
    throw new PipelineError("That file would not decode as an image.", "decode-failed");
  }
  const edge = Math.max(full.width, full.height);
  if (edge <= MAX_WORKING_EDGE) return full;
  const scale = MAX_WORKING_EDGE / edge;
  const resized = await createImageBitmap(full, {
    resizeWidth: Math.round(full.width * scale),
    resizeHeight: Math.round(full.height * scale),
    resizeQuality: "high",
  });
  full.close();
  return resized;
}

/** Downscaled copy for cheap preview or detection work. Caller closes it. */
export async function downscale(bitmap: ImageBitmap, maxEdge: number): Promise<ImageBitmap> {
  const edge = Math.max(bitmap.width, bitmap.height);
  if (edge <= maxEdge) {
    return createImageBitmap(bitmap);
  }
  const s = maxEdge / edge;
  return createImageBitmap(bitmap, {
    resizeWidth: Math.round(bitmap.width * s),
    resizeHeight: Math.round(bitmap.height * s),
    resizeQuality: "medium",
  });
}

/** Per-window pan/zoom state, normalized so it survives format switches. */
export interface ViewState {
  /** 1 = exact cover fit; 1.5 = zoomed 50% past cover */
  zoom: number;
  /** -1..1, fraction of the maximum pannable overflow in each axis */
  offsetX: number;
  offsetY: number;
}

export const DEFAULT_VIEW: ViewState = { zoom: 1, offsetX: 0, offsetY: 0 };

/**
 * Cover-fit draw geometry for a bitmap inside a w x h window under a ViewState.
 * Returns the source rect to sample, in bitmap pixels.
 */
export function coverSourceRect(
  bw: number,
  bh: number,
  w: number,
  h: number,
  view: ViewState,
): { sx: number; sy: number; sw: number; sh: number } {
  const zoom = Math.max(1, Math.min(4, view.zoom));
  const scale = Math.max(w / bw, h / bh) * zoom;
  const sw = w / scale;
  const sh = h / scale;
  const slackX = (bw - sw) / 2;
  const slackY = (bh - sh) / 2;
  const sx = slackX + Math.max(-1, Math.min(1, view.offsetX)) * slackX;
  const sy = slackY + Math.max(-1, Math.min(1, view.offsetY)) * slackY;
  return { sx, sy, sw, sh };
}
