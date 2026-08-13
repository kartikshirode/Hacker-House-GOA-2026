"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { nanoid } from "nanoid";
import { EVENT } from "@/lib/brand";
import { FORMATS, STYLES, TEXT_LIMITS, styleSupports, type FormatId, type StyleId } from "@/lib/layout";
import {
  DEFAULT_VIEW,
  decodePhoto,
  PipelineError,
  warmHeicConverter,
  type ViewState,
} from "@/lib/image-pipeline";
import { generateTitle } from "@/lib/titles";
import { fallbackSeat } from "@/lib/seat";
import { detectFaceView } from "@/lib/face";
import type { PassState, Slot } from "@/lib/render";
import PassPreview from "@/components/PassPreview";
import ShareBar from "@/components/ShareBar";
import SelfieCapture from "@/components/SelfieCapture";

const TABS: { id: FormatId; label: string }[] = [
  { id: "card", label: "BUILDER ID" },
  { id: "team", label: "TEAM FRAME" },
  { id: "pfp", label: "PFP FRAME" },
  { id: "poster", label: "POSTER ID" },
];

/** Rotating sticker badge: text ring around a riso sun, rides the sheet corner. */
function SpinBadge() {
  return (
    <svg viewBox="0 0 120 120" className="w-full h-full" aria-hidden="true">
      <circle cx="60" cy="60" r="58" fill="var(--hh-cream)" stroke="var(--hh-green)" strokeWidth="2.5" strokeDasharray="5 4" />
      <g className="spin-badge">
        <path id="badge-ring" d="M 60 15 a 45 45 0 1 1 -0.01 0" fill="none" />
        <text fill="var(--hh-green)" fontSize="9.6" fontWeight="700" letterSpacing="1.2" style={{ fontFamily: "var(--font-mono)" }}>
          <textPath href="#badge-ring">#FRAMEINGOA · LESS NOISE · MORE SIGNAL ·</textPath>
        </text>
      </g>
      <circle cx="63" cy="58" r="17" fill="var(--hh-pink)" opacity="0.55" />
      <circle cx="60" cy="60" r="17" fill="var(--hh-yellow)" stroke="var(--hh-green-deep)" strokeWidth="2" />
      <circle cx="54" cy="57" r="1.8" fill="var(--hh-green-deep)" />
      <circle cx="66" cy="57" r="1.8" fill="var(--hh-green-deep)" />
      <path d="M 53 64 q 7 6 14 0" fill="none" stroke="var(--hh-green-deep)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

async function fetchSeat(passId: string): Promise<number> {
  try {
    const res = await fetch("/api/seat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ passId }),
    });
    if (!res.ok) throw new Error();
    const data = (await res.json()) as { seat: number };
    return data.seat;
  } catch {
    return fallbackSeat(passId);
  }
}

export default function Home() {
  const [format, setFormat] = useState<FormatId>("card");
  const [styleId, setStyleId] = useState<StyleId>("print");
  const [slots, setSlots] = useState<Slot[]>([{ bitmap: null, view: DEFAULT_VIEW }]);
  const [activeSlot, setActiveSlot] = useState(0);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [teamName, setTeamName] = useState("");
  const [title, setTitle] = useState("");
  const [passId, setPassId] = useState("");
  const [seat, setSeat] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [decoding, setDecoding] = useState(false);
  const [uploadedPageUrl, setUploadedPageUrl] = useState<string | null>(null);
  const [selfieOpen, setSelfieOpen] = useState(false);
  const [printKey, setPrintKey] = useState(0);
  const uploadedIdRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const slotsRef = useRef(slots);
  slotsRef.current = slots;

  const [, bumpFrames] = useState(0);
  useEffect(() => {
    warmHeicConverter();
    void import("@/lib/qr").then((m) => m.warmQr(window.location.origin));
    void import("@/lib/frames").then((m) => m.warmFrames().then(() => bumpFrames((n) => n + 1)));
  }, []);

  // Both are randomized, so they must be born on the client only; running them
  // during SSR guarantees a hydration mismatch.
  useEffect(() => {
    setTitle(generateTitle());
    setPassId(nanoid());
  }, []);

  useEffect(() => {
    if (!passId) return;
    let live = true;
    fetchSeat(passId).then((s) => live && setSeat(s));
    return () => {
      live = false;
    };
  }, [passId]);

  // Any content edit after a successful upload means a fresh immutable pass.
  const touch = useCallback(() => {
    if (uploadedIdRef.current) {
      uploadedIdRef.current = null;
      setUploadedPageUrl(null);
      setPassId(nanoid());
    }
  }, []);

  const spec = FORMATS[format];
  const hasPhoto = slots.some((s) => s.bitmap);
  const state: PassState = { format, styleId, slots, name, role, teamName, title, seat, passId };

  const setSlot = useCallback(
    (index: number, patch: Partial<Slot>) => {
      touch();
      setSlots((prev) => {
        const next = [...prev];
        next[index] = { ...(next[index] ?? { bitmap: null, view: DEFAULT_VIEW }), ...patch };
        return next;
      });
    },
    [touch],
  );

  const onPickFile = useCallback(
    async (file: File | undefined | null, slotIndex: number) => {
      if (!file) return;
      setUploadError(null);
      setDecoding(true);
      try {
        const bitmap = await decodePhoto(file);
        const old = slotsRef.current[slotIndex]?.bitmap;
        old?.close();
        setSlot(slotIndex, { bitmap, view: DEFAULT_VIEW });
        setPrintKey((k) => k + 1);
        // Face-aware auto-center, best effort; center crop already shows.
        void detectFaceView(bitmap).then((view) => {
          if (view && slotsRef.current[slotIndex]?.bitmap === bitmap) {
            setSlot(slotIndex, { view });
          }
        });
      } catch (e) {
        setUploadError(
          e instanceof PipelineError ? e.message : "That photo would not load. Try a JPG or PNG.",
        );
      } finally {
        setDecoding(false);
      }
    },
    [setSlot],
  );

  const onViewChange = useCallback(
    (index: number, view: ViewState) => setSlot(index, { view }),
    [setSlot],
  );

  const switchFormat = useCallback(
    (f: FormatId) => {
      touch();
      setFormat(f);
      setActiveSlot(0);
      setStyleId((cur) => (styleSupports(cur, f) ? cur : "print"));
      setSlots((prev) => {
        const max = FORMATS[f].maxPhotos;
        if (prev.length > max) {
          prev.slice(max).forEach((s) => s.bitmap?.close());
          return prev.slice(0, max);
        }
        return prev;
      });
    },
    [touch],
  );

  const switchStyle = useCallback(
    (id: StyleId) => {
      touch();
      setStyleId(id);
    },
    [touch],
  );

  const reroll = useCallback(() => {
    touch();
    setTitle((t) => generateTitle(Math.random, t));
  }, [touch]);

  const filledCount = slots.filter((s) => s.bitmap).length;
  const canAddMore = format === "team" && filledCount < spec.maxPhotos && filledCount === slots.length;

  return (
    <div className="flex-1 flex flex-col min-h-dvh">
      {/* compact masthead: one row, sticker-sheet chips instead of tickers */}
      <header className="grain grain-light relative px-4 sm:px-8 pt-3 pb-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div>
          <p className="font-mono text-[9px] font-bold tracking-[0.4em] text-hh-yellow/80 pb-1">
            2:47PM STUDIO PRESENTS
          </p>
          <div className="relative inline-block leading-none">
            <h1 className="font-display font-semibold text-hh-yellow text-[clamp(2.2rem,6vw,3.4rem)] tracking-tight whitespace-nowrap">
              HACKER HOUSE
            </h1>
            <span
              className="sticker absolute -right-5 -top-1.5 bg-hh-pink text-hh-yellow font-bold rounded-full px-2.5 py-0.5 text-[clamp(0.8rem,1.8vw,1.05rem)]"
              style={{ fontFamily: "'Noto Sans Devanagari', sans-serif" }}
            >
              गोवा
            </span>
          </div>
          <p className="font-mono text-[10px] tracking-[0.24em] text-hh-cream/80 pt-1">
            TURN A PHOTO INTO YOUR BUILDER PASS
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 pr-0 lg:pr-28" aria-hidden="true">
          <span className="chip chip-yellow">{EVENT.dates}</span>
          <span className="chip chip-cream">{EVENT.place.toUpperCase()}</span>
          <span className="chip chip-pink">RUN OF 247</span>
        </div>
      </header>

      {/* press sheet */}
      <main className="flex-1 w-full max-w-6xl mx-auto px-3 sm:px-6 pb-3">
        <div className="press-sheet grain relative p-4 sm:p-6">
          <div className="crop" style={{ top: -8, left: -8 }} />
          <div className="crop" style={{ top: -8, right: -8 }} />
          <div className="crop" style={{ bottom: -8, left: -8 }} />

          <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
            <p className="font-mono text-[10px] font-bold tracking-[0.3em] text-hh-green">
              PRESS SHEET Nº {seat !== null ? String(seat).padStart(3, "0") : "···"} · PICK A FORMAT
            </p>
            <div className="flex gap-2 flex-wrap">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => switchFormat(t.id)}
                  className={`stub ${format === t.id ? "stub-active" : ""}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 pb-3">
            <p className="font-mono text-[10px] font-bold tracking-[0.3em] text-hh-green">STYLE</p>
            {STYLES.map((st) => (
              <button
                key={st.id}
                onClick={() => switchStyle(st.id)}
                className={`stub ${styleId === st.id ? "stub-active" : ""}`}
              >
                {st.label}
              </button>
            ))}
          </div>

          <div className="grid md:grid-cols-[1fr_330px] gap-6 items-start">
            {/* press bed with the live pass */}
            <div className="press-bed grain grain-light p-4 sm:p-5">
              <div className="hidden sm:block absolute -bottom-7 -left-7 w-[112px] h-[112px] z-10 pointer-events-none drop-shadow-[3px_4px_0_rgba(0,0,0,0.3)]">
                <SpinBadge />
              </div>
              <div className="reg-mark" style={{ top: 10, left: 10 }} />
              <div className="reg-mark" style={{ top: 10, right: 10 }} />
              <div className="reg-mark" style={{ bottom: 10, left: 10 }} />
              <div className="reg-mark" style={{ bottom: 10, right: 10 }} />
              <div
                className="mx-auto w-full"
                style={{
                  // fit the pass inside one viewport: width backed out of the
                  // remaining height through this format's aspect ratio
                  maxWidth: `min(34rem, max(15rem, calc((100dvh - 368px) * ${(spec.width / spec.height).toFixed(4)})))`,
                }}
              >
                <PassPreview
                  state={state}
                  activeSlot={activeSlot}
                  onSlotTap={setActiveSlot}
                  onViewChange={onViewChange}
                  printKey={printKey}
                />
              </div>
              <p className="font-mono text-[10px] tracking-[0.14em] text-hh-cream/60 text-center pt-3">
                {hasPhoto
                  ? `DRAG TO REPOSITION · PINCH OR SCROLL TO ZOOM${format === "team" ? " · TAP A WINDOW TO SELECT" : ""}`
                  : "THE PRESS IS WARM · ADD A PHOTO TO PRINT"}
              </p>
            </div>

            {/* print job form */}
            <div className="flex flex-col gap-4">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,.heic,.heif"
                className="hidden"
                onChange={(e) => {
                  void onPickFile(e.target.files?.[0], canAddMore ? filledCount : activeSlot);
                  e.target.value = "";
                }}
              />
              <div>
                <span className="field-label">Photo</span>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={decoding}
                  className="w-full border-2 border-dashed border-hh-green rounded-xl px-4 py-5 font-mono text-sm font-bold text-hh-green hover:bg-hh-green/5 disabled:opacity-50 cursor-pointer"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    void onPickFile(e.dataTransfer.files?.[0], canAddMore ? filledCount : activeSlot);
                  }}
                >
                  {decoding
                    ? "READING PHOTO…"
                    : hasPhoto
                      ? format === "team" && canAddMore
                        ? `ADD BUILDER ${filledCount + 1} OF ${spec.maxPhotos}`
                        : "REPLACE PHOTO"
                      : "UPLOAD A PHOTO (JPG · PNG · HEIC)"}
                </button>
                <button
                  onClick={() => setSelfieOpen(true)}
                  className="font-mono text-xs text-hh-green underline underline-offset-4 pt-2 cursor-pointer"
                >
                  or snap a selfie
                </button>
              </div>
              {uploadError ? <p className="font-mono text-xs font-bold text-hh-red">{uploadError}</p> : null}

              {format === "team" ? (
                <>
                  <div>
                    <label className="field-label" htmlFor="team-name">
                      Team name
                    </label>
                    <input
                      id="team-name"
                      className="field"
                      placeholder="Reef Runners"
                      maxLength={TEXT_LIMITS.teamName}
                      value={teamName}
                      onChange={(e) => {
                        touch();
                        setTeamName(e.target.value);
                      }}
                    />
                  </div>
                  {slots.map((s, i) =>
                    s.bitmap ? (
                      <div key={i}>
                        <label className="field-label" htmlFor={`builder-${i}`}>
                          Builder {i + 1}
                        </label>
                        <input
                          id={`builder-${i}`}
                          className="field"
                          placeholder="Name on the card"
                          maxLength={TEXT_LIMITS.name}
                          value={s.label ?? ""}
                          onChange={(e) => setSlot(i, { label: e.target.value })}
                        />
                      </div>
                    ) : null,
                  )}
                </>
              ) : format !== "pfp" ? (
                <>
                  <div>
                    <label className="field-label" htmlFor="name">
                      Name
                    </label>
                    <input
                      id="name"
                      className="field"
                      placeholder="Name on the card"
                      maxLength={TEXT_LIMITS.name}
                      value={name}
                      onChange={(e) => {
                        touch();
                        setName(e.target.value);
                      }}
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="role">
                      Stack / role
                    </label>
                    <input
                      id="role"
                      className="field"
                      placeholder="Rust, design, growth…"
                      maxLength={TEXT_LIMITS.role}
                      value={role}
                      onChange={(e) => {
                        touch();
                        setRole(e.target.value);
                      }}
                    />
                  </div>
                </>
              ) : null}

              {format !== "pfp" ? (
                <div>
                  <span className="field-label">Builder title</span>
                  <div className="flex items-center gap-2 bg-[#fffef6] border-2 border-hh-green rounded-lg px-3 py-2.5">
                    <span className="font-mono text-sm font-bold text-hh-pink flex-1 uppercase">{title || "…"}</span>
                    <button
                      onClick={reroll}
                      className="font-mono text-xs font-bold text-hh-green underline underline-offset-4 cursor-pointer"
                    >
                      ↻ REROLL
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="pt-1">
                <ShareBar
                  state={state}
                  ready={hasPhoto && !decoding}
                  onUploaded={(id) => (uploadedIdRef.current = id)}
                  uploadedPageUrl={uploadedPageUrl}
                  setUploadedPageUrl={setUploadedPageUrl}
                />
              </div>
              <p className="font-mono text-[10px] leading-relaxed text-hh-green/75 tracking-wide">
                NO LOGIN. YOUR PHOTO NEVER LEAVES THIS DEVICE UNLESS YOU CREATE A SHARE LINK.
              </p>
            </div>
          </div>
        </div>
      </main>

      <SelfieCapture
        open={selfieOpen}
        onClose={() => setSelfieOpen(false)}
        onCapture={(file) => void onPickFile(file, canAddMore ? filledCount : activeSlot)}
      />
    </div>
  );
}
