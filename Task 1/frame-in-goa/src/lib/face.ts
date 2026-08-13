// Face-aware auto-crop. Lazy MediaPipe BlazeFace (short range); every failure
// path returns null so the caller falls back to a plain center crop.
// Detection runs on a <=640 px copy to keep the main thread cheap.

import type { FaceDetector } from "@mediapipe/tasks-vision";
import { downscale, type ViewState } from "./image-pipeline";

const MP_VERSION = "1.0.1"; // keep in lockstep with package.json
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";

let detectorPromise: Promise<FaceDetector | null> | null = null;

function getDetector(): Promise<FaceDetector | null> {
  if (!detectorPromise) {
    detectorPromise = (async () => {
      try {
        const { FaceDetector, FilesetResolver } = await import("@mediapipe/tasks-vision");
        const vision = await FilesetResolver.forVisionTasks(
          `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`,
        );
        return await FaceDetector.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL_URL },
          runningMode: "IMAGE",
        });
      } catch {
        return null;
      }
    })();
  }
  return detectorPromise;
}

/**
 * Compute a ViewState that centers the (first) detected face in a square
 * photo window, framed at ~2.2x face height, eyes slightly above center.
 * Null when no face or the detector can't load.
 */
export async function detectFaceView(bitmap: ImageBitmap): Promise<ViewState | null> {
  const detector = await getDetector();
  if (!detector) return null;

  let small: ImageBitmap | null = null;
  try {
    small = await downscale(bitmap, 640);
    const canvas = document.createElement("canvas");
    canvas.width = small.width;
    canvas.height = small.height;
    canvas.getContext("2d")?.drawImage(small, 0, 0);
    const scaleUp = bitmap.width / small.width;
    const result = detector.detect(canvas);
    const det = result.detections?.[0];
    if (!det?.boundingBox) return null;

    const bb = det.boundingBox;
    // eye midpoint beats box center for circular crops; keypoints 0/1 are eyes
    const eyes = det.keypoints?.slice(0, 2);
    const fx =
      eyes && eyes.length === 2
        ? ((eyes[0].x + eyes[1].x) / 2) * small.width * scaleUp
        : (bb.originX + bb.width / 2) * scaleUp;
    const fy =
      eyes && eyes.length === 2
        ? ((eyes[0].y + eyes[1].y) / 2) * small.height * scaleUp
        : (bb.originY + bb.height / 2) * scaleUp;
    const faceH = bb.height * scaleUp;

    // All photo windows in layout.ts are square, so aspect math uses w = h.
    const bw = bitmap.width;
    const bh = bitmap.height;
    const win = 1000;
    const base = Math.max(win / bw, win / bh);
    const zoom = Math.max(1, Math.min(4, win / (base * faceH * 2.2)));
    const sw = win / (base * zoom);
    const sh = sw;

    const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
    const desiredSx = clamp(fx - sw / 2, 0, bw - sw);
    const desiredSy = clamp(fy - sh * 0.42, 0, bh - sh);
    const slackX = (bw - sw) / 2;
    const slackY = (bh - sh) / 2;
    return {
      zoom,
      offsetX: slackX > 0 ? clamp((desiredSx - slackX) / slackX, -1, 1) : 0,
      offsetY: slackY > 0 ? clamp((desiredSy - slackY) / slackY, -1, 1) : 0,
    };
  } catch {
    return null;
  } finally {
    small?.close();
  }
}
