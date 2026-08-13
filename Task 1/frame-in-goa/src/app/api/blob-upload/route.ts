import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";
import { NextResponse } from "next/server";

// Tokens are scoped hard: exact pathname shape, PNG only, 10 MB, no overwrite.
// Blobs are immutable by design; a re-render always gets a fresh id.
const ALLOWED_PATH = /^(passes|og)\/[A-Za-z0-9_-]{21}\.png$/;

export async function POST(request: Request): Promise<NextResponse> {
  const body = (await request.json()) as HandleUploadBody;
  try {
    const result = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        if (!ALLOWED_PATH.test(pathname)) {
          throw new Error("invalid pathname");
        }
        return {
          allowedContentTypes: ["image/png"],
          maximumSizeInBytes: 10 * 1024 * 1024,
          addRandomSuffix: false,
          allowOverwrite: false,
        };
      },
      onUploadCompleted: async () => {},
    });
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "upload failed" },
      { status: 400 },
    );
  }
}
