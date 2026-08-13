"use client";

import { useCallback, useEffect, useState } from "react";
import { buildCaption, buildIntentUrl } from "@/lib/caption";
import { canShareFile, downloadBlob, shareFile, uploadPass } from "@/lib/share";
import { exportPng, renderOg, renderPass, type PassState } from "@/lib/render";
import { loadBrandFonts } from "@/lib/fonts";

interface Props {
  state: PassState;
  ready: boolean;
  /** parent regenerates the pass id after a successful upload + later edits */
  onUploaded: (passId: string) => void;
  uploadedPageUrl: string | null;
  setUploadedPageUrl: (url: string | null) => void;
}

type Busy = null | "x" | "native" | "download";

async function renderBlobs(state: PassState): Promise<{ pass: Blob; og: Blob }> {
  await loadBrandFonts();
  const passCanvas = document.createElement("canvas");
  renderPass(passCanvas, state);
  const ogCanvas = document.createElement("canvas");
  renderOg(ogCanvas, passCanvas);
  const toBlob = (c: HTMLCanvasElement) =>
    new Promise<Blob>((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error("export failed"))), "image/png"));
  return { pass: await toBlob(passCanvas), og: await toBlob(ogCanvas) };
}

export default function ShareBar({ state, ready, onUploaded, uploadedPageUrl, setUploadedPageUrl }: Props) {
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Pre-render the file between edits so the native share tap stays synchronous.
  const [nativeFile, setNativeFile] = useState<File | null>(null);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const blob = await exportPng(state);
        if (!cancelled) setNativeFile(new File([blob], "frame-in-goa.png", { type: "image/png" }));
      } catch {
        if (!cancelled) setNativeFile(null);
      }
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [state, ready]);

  const caption = buildCaption(state.seat, uploadedPageUrl ?? undefined);

  const shareToX = useCallback(async () => {
    if (!state.passId) return;
    setBusy("x");
    setError(null);
    try {
      let pageUrl = uploadedPageUrl;
      if (!pageUrl) {
        const { pass, og } = await renderBlobs(state);
        const up = await uploadPass(state.passId, pass, og, {
          name: state.format === "team" ? state.teamName : state.name,
          title: state.title,
          seat: state.seat,
        });
        pageUrl = new URL(up.pagePath, window.location.origin).toString();
        setUploadedPageUrl(pageUrl);
        onUploaded(state.passId);
      }
      window.open(buildIntentUrl(buildCaption(state.seat, pageUrl)), "_blank", "noopener");
    } catch {
      // Blob not configured or offline: intent still opens, user attaches the download.
      setError("Could not create a share link. Download the image and attach it to your post.");
      window.open(buildIntentUrl(buildCaption(state.seat)), "_blank", "noopener");
    } finally {
      setBusy(null);
    }
  }, [state, uploadedPageUrl, onUploaded, setUploadedPageUrl]);

  // Called directly from the tap; nothing awaited before navigator.share.
  const shareNative = useCallback(() => {
    if (!nativeFile) return;
    setBusy("native");
    setError(null);
    shareFile(nativeFile)
      .catch((e: unknown) => {
        if ((e as Error)?.name !== "AbortError") setError("Sharing failed. Try Download instead.");
      })
      .finally(() => setBusy(null));
  }, [nativeFile]);

  const download = useCallback(async () => {
    setBusy("download");
    setError(null);
    try {
      const blob = await exportPng(state);
      downloadBlob(blob, "frame-in-goa.png");
      // carry them straight to X with the caption ready; the fresh PNG is
      // sitting in downloads to attach
      const url = uploadedPageUrl ?? window.location.origin;
      window.open(buildIntentUrl(buildCaption(state.seat, url)), "_blank", "noopener");
    } catch {
      setError("Export failed on this device. Try a smaller photo.");
    } finally {
      setBusy(null);
    }
  }, [state, uploadedPageUrl]);

  const copyCaption = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(caption);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Copy failed. Long-press the caption text to copy it.");
    }
  }, [caption]);

  // Synchronous open straight from the tap, so popup blockers stay quiet
  // even when the async buttons above got their window.open swallowed.
  const openIntent = useCallback(() => {
    const url = uploadedPageUrl ?? window.location.origin;
    window.open(buildIntentUrl(buildCaption(state.seat, url)), "_blank", "noopener");
  }, [state.seat, uploadedPageUrl]);

  return (
    <div className="flex flex-col gap-3 w-full">
      <div className="flex flex-col gap-2.5">
        <button className="btn btn-primary text-sm" onClick={shareToX} disabled={!ready || busy !== null}>
          {busy === "x" ? "PRINTING YOUR LINK…" : "SHARE TO X"}
        </button>
        <div className="flex gap-2.5">
          {nativeFile && canShareFile(nativeFile) ? (
            <button className="btn btn-pink text-sm flex-1" onClick={shareNative} disabled={!ready || busy !== null}>
              SHARE IMAGE VIA…
            </button>
          ) : null}
          <button className="btn btn-ghost text-sm flex-1" onClick={download} disabled={!ready || busy !== null}>
            {busy === "download" ? "EXPORTING…" : "DOWNLOAD + POST"}
          </button>
        </div>
      </div>
      <div className="flex items-start gap-2 bg-[#fffef6] border-2 border-hh-green rounded-lg p-3">
        <p className="font-mono text-xs leading-relaxed flex-1 break-words min-w-0 text-hh-green-deep">{caption}</p>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <button
            className="font-mono text-xs font-bold text-hh-pink cursor-pointer underline underline-offset-4"
            onClick={copyCaption}
          >
            {copied ? "COPIED" : "COPY"}
          </button>
          <button
            className="font-mono text-xs font-bold text-hh-green cursor-pointer underline underline-offset-4"
            onClick={openIntent}
            disabled={!ready}
          >
            POST ON X ↗
          </button>
        </div>
      </div>
      {error ? <p className="font-mono text-xs font-bold text-hh-red">{error}</p> : null}
    </div>
  );
}
