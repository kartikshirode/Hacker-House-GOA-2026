declare module "qrcode" {
  interface QRCodeToCanvasOptions {
    margin?: number;
    width?: number;
    errorCorrectionLevel?: "L" | "M" | "Q" | "H";
    color?: { dark?: string; light?: string };
  }
  function toCanvas(
    canvas: HTMLCanvasElement,
    text: string,
    options?: QRCodeToCanvasOptions,
  ): Promise<HTMLCanvasElement>;
  const QRCode: { toCanvas: typeof toCanvas };
  export default QRCode;
}
