declare module "heic-to" {
  export function isHeic(file: File | Blob): Promise<boolean>;
  export function heicTo(options: {
    blob: Blob;
    type: "image/jpeg" | "image/png";
    quality?: number;
  }): Promise<Blob>;
}
