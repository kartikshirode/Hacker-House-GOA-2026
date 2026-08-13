"use client";

// Live preview = the real renderer at preview scale, wrapped in a tilt shell.
// Pan: drag. Zoom: pinch, wheel, or the slider in the controls.

import { useCallback, useEffect, useRef } from "react";
import { FORMATS } from "@/lib/layout";
import { renderPass, type PassState } from "@/lib/render";
import { loadBrandFonts } from "@/lib/fonts";
import type { ViewState } from "@/lib/image-pipeline";

interface Props {
  state: PassState;
  activeSlot: number;
  onSlotTap: (index: number) => void;
  onViewChange: (index: number, view: ViewState) => void;
  /** bump to replay the print-out animation (new photo landed) */
  printKey?: number;
}

export default function PassPreview({ state, activeSlot, onSlotTap, onViewChange, printKey = 0 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{ dist: number; zoom: number } | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Re-render on any state change, after fonts are ready.
  useEffect(() => {
    let cancelled = false;
    loadBrandFonts().then(() => {
      if (cancelled || !canvasRef.current) return;
      const container = canvasRef.current.parentElement;
      const width = Math.min(container?.clientWidth ?? 540, 640);
      renderPass(canvasRef.current, state, width);
    });
    return () => {
      cancelled = true;
    };
  }, [state]);

  // Tilt: pointer on desktop, gyroscope on phones (iOS asks on first tap).
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    // Kept deliberately gentle: the card should feel like paper, not a gimbal.
    const setTilt = (nx: number, ny: number) => {
      shell.style.setProperty("--ry", `${nx * 2.4}deg`);
      shell.style.setProperty("--rx", `${-ny * 2.4}deg`);
      shell.style.setProperty("--gx", `${50 + nx * 32}%`);
      shell.style.setProperty("--gy", `${50 + ny * 32}%`);
    };
    const onMouse = (e: MouseEvent) => {
      const r = shell.getBoundingClientRect();
      setTilt(((e.clientX - r.left) / r.width - 0.5) * 2, ((e.clientY - r.top) / r.height - 0.5) * 2);
    };
    const onLeave = () => setTilt(0, 0);
    const onOrient = (e: DeviceOrientationEvent) => {
      if (e.gamma === null || e.beta === null) return;
      setTilt(Math.max(-1, Math.min(1, e.gamma / 55)), Math.max(-1, Math.min(1, (e.beta - 45) / 55)));
    };
    shell.addEventListener("mousemove", onMouse);
    shell.addEventListener("mouseleave", onLeave);
    window.addEventListener("deviceorientation", onOrient);
    return () => {
      shell.removeEventListener("mousemove", onMouse);
      shell.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("deviceorientation", onOrient);
    };
  }, []);

  const requestGyro = useCallback(() => {
    const DOE = window.DeviceOrientationEvent as unknown as
      | { requestPermission?: () => Promise<string> }
      | undefined;
    DOE?.requestPermission?.().catch(() => {});
  }, []);

  const hitSlot = useCallback((clientX: number, clientY: number): number => {
    const canvas = canvasRef.current;
    if (!canvas) return 0;
    const rect = canvas.getBoundingClientRect();
    const s = stateRef.current;
    const spec = FORMATS[s.format];
    const scale = rect.width / spec.width;
    const x = (clientX - rect.left) / scale;
    const y = (clientY - rect.top) / scale;
    const filled = s.format === "team" ? Math.max(1, s.slots.filter((sl) => sl.bitmap).length) : 1;
    const wins = spec.windows(filled);
    const idx = wins.findIndex((w) => x >= w.x && x <= w.x + w.w && y >= w.y && y <= w.y + w.h);
    return idx === -1 ? activeSlot : idx;
  }, [activeSlot]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      requestGyro();
      (e.target as Element).setPointerCapture(e.pointerId);
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.current.size === 1) onSlotTap(hitSlot(e.clientX, e.clientY));
      if (pointers.current.size === 2) {
        const [a, b] = [...pointers.current.values()];
        pinchStart.current = {
          dist: Math.hypot(a.x - b.x, a.y - b.y),
          zoom: stateRef.current.slots[activeSlot]?.view.zoom ?? 1,
        };
      }
    },
    [activeSlot, hitSlot, onSlotTap, requestGyro],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const prev = pointers.current.get(e.pointerId);
      if (!prev) return;
      const slot = stateRef.current.slots[activeSlot];
      if (!slot?.bitmap) return;
      const view = slot.view;

      if (pointers.current.size === 2 && pinchStart.current) {
        pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
        const [a, b] = [...pointers.current.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        const zoom = Math.max(1, Math.min(4, (pinchStart.current.zoom * dist) / pinchStart.current.dist));
        onViewChange(activeSlot, { ...view, zoom });
        return;
      }

      const dx = e.clientX - prev.x;
      const dy = e.clientY - prev.y;
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      // Drag distance as a fraction of the window, boosted by zoom so panning
      // feels 1:1 with the photo rather than the frame.
      const k = (2 / rect.width) * (2.2 / view.zoom);
      onViewChange(activeSlot, {
        ...view,
        offsetX: Math.max(-1, Math.min(1, view.offsetX - dx * k * 300)),
        offsetY: Math.max(-1, Math.min(1, view.offsetY - dy * k * 300)),
      });
    },
    [activeSlot, onViewChange],
  );

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinchStart.current = null;
  }, []);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      const slot = stateRef.current.slots[activeSlot];
      if (!slot?.bitmap) return;
      const zoom = Math.max(1, Math.min(4, slot.view.zoom * (1 - e.deltaY * 0.0012)));
      onViewChange(activeSlot, { ...slot.view, zoom });
    },
    [activeSlot, onViewChange],
  );

  const showHolo = state.format === "card" || state.format === "poster";

  return (
    <div
      key={printKey}
      ref={shellRef}
      className={`tilt relative rounded-xl ${printKey > 0 ? "print-anim" : ""}`}
      style={{ touchAction: "none" }}
    >
      {printKey > 0 ? <div className="print-head" /> : null}
      <canvas
        ref={canvasRef}
        className="w-full rounded-xl shadow-2xl select-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
      />
      {showHolo ? <div className="holo" /> : null}
    </div>
  );
}
