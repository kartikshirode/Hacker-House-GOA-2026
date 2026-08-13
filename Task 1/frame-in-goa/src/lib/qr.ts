// One QR, rendered once, reused by every export. The renderer stays
// synchronous: it draws whatever is warm and skips cleanly when nothing is.
import QRCode from "qrcode";

let qrCanvas: HTMLCanvasElement | null = null;

export function getQr(): HTMLCanvasElement | null {
  return qrCanvas;
}

export async function warmQr(url: string): Promise<void> {
  if (qrCanvas) return;
  try {
    const c = document.createElement("canvas");
    await QRCode.toCanvas(c, url, {
      margin: 0,
      width: 320,
      errorCorrectionLevel: "M",
      color: { dark: "#07472aff", light: "#00000000" },
    });
    qrCanvas = c;
  } catch {
    qrCanvas = null;
  }
}
