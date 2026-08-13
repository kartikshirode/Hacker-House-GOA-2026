"use client";

// Dev fixture gallery: every format against nasty inputs (long names,
// Devanagari, extreme aspect ratios), all through the real renderer. Also
// renders the homepage OG canvas and exposes it for extraction.

import { useEffect, useRef } from "react";
import { renderPass, renderOg, type PassState } from "@/lib/render";
import { loadBrandFonts } from "@/lib/fonts";
import { DEFAULT_VIEW } from "@/lib/image-pipeline";
import { warmQr } from "@/lib/qr";
import { warmFrames } from "@/lib/frames";

async function syntheticPhoto(w: number, h: number, hue: number): Promise<ImageBitmap> {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, `hsl(${hue} 45% 38%)`);
  g.addColorStop(1, `hsl(${hue + 60} 55% 62%)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#f0c9a2";
  ctx.beginPath();
  ctx.arc(w * 0.62, h * 0.4, Math.min(w, h) * 0.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#1c1c1c";
  ctx.beginPath();
  ctx.arc(w * 0.57, h * 0.37, Math.min(w, h) * 0.024, 0, Math.PI * 2);
  ctx.arc(w * 0.67, h * 0.37, Math.min(w, h) * 0.024, 0, Math.PI * 2);
  ctx.fill();
  return createImageBitmap(c);
}

export default function Fixtures() {
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      await loadBrandFonts();
      await warmQr(window.location.origin);
      await warmFrames();
      const portrait = await syntheticPhoto(900, 1600, 190);
      const landscape = await syntheticPhoto(2200, 1000, 20);
      const square = await syntheticPhoto(1200, 1200, 120);
      if (disposed) return;

      const base = {
        styleId: "print" as const,
        slots: [{ bitmap: portrait, view: DEFAULT_VIEW }],
        name: "Kartik",
        role: "TypeScript",
        teamName: "Reef Runners",
        title: "Kokum Compiler",
        seat: 42,
        passId: "fixture-fixture-fixtu",
      };
      const cases: { label: string; state: PassState }[] = [
        { label: "card / portrait photo", state: { ...base, format: "card" } },
        { label: "card / GOA DAY scene", state: { ...base, format: "card", styleId: "day" } },
        { label: "card / GOA SUNSET scene", state: { ...base, format: "card", styleId: "sunset" } },
        { label: "poster / GOA DAY scene", state: { ...base, format: "poster", styleId: "day" } },
        { label: "poster / GOA SUNSET scene, long name", state: { ...base, format: "poster", styleId: "sunset", name: "Aleksandrina Konstantinova" } },
        {
          label: "card / long name + long role + seat overflow",
          state: {
            ...base,
            format: "card",
            slots: [{ bitmap: landscape, view: DEFAULT_VIEW }],
            name: "Aleksandrina Konstantinova-Duraiswamy",
            role: "Distributed systems, embedded, growth",
            seat: 412,
          },
        },
        {
          label: "card / Devanagari name",
          state: { ...base, format: "card", slots: [{ bitmap: square, view: DEFAULT_VIEW }], name: "कार्तिक शिरोडे" },
        },
        {
          label: "team / 3 slots, mixed aspects",
          state: {
            ...base,
            format: "team",
            slots: [
              { bitmap: portrait, view: DEFAULT_VIEW, label: "Kartik" },
              { bitmap: landscape, view: DEFAULT_VIEW, label: "A Very Long Builder Name" },
              { bitmap: square, view: DEFAULT_VIEW, label: "देव" },
            ],
          },
        },
        {
          label: "team / GOA DAY scene, 3 slots",
          state: {
            ...base,
            format: "team",
            styleId: "day",
            slots: [
              { bitmap: portrait, view: DEFAULT_VIEW, label: "Kartik" },
              { bitmap: landscape, view: DEFAULT_VIEW, label: "A Very Long Builder Name" },
              { bitmap: square, view: DEFAULT_VIEW, label: "देव" },
            ],
          },
        },
        { label: "pfp / landscape photo", state: { ...base, format: "pfp", slots: [{ bitmap: landscape, view: DEFAULT_VIEW }] } },
        { label: "pfp / GOA SUNSET scene", state: { ...base, format: "pfp", styleId: "sunset", slots: [{ bitmap: square, view: DEFAULT_VIEW }] } },
        { label: "poster / print style", state: { ...base, format: "poster" } },
        { label: "card / empty state", state: { ...base, format: "card", slots: [{ bitmap: null, view: DEFAULT_VIEW }], name: "", role: "" } },
      ];

      const grid = gridRef.current;
      if (!grid) return;
      grid.innerHTML = "";
      for (const c of cases) {
        const cell = document.createElement("div");
        const label = document.createElement("p");
        label.textContent = c.label;
        label.className = "font-mono text-xs py-2 opacity-80";
        const canvas = document.createElement("canvas");
        canvas.className = "w-full rounded-lg";
        renderPass(canvas, c.state, 420);
        cell.append(label, canvas);
        grid.append(cell);
      }

      // Homepage OG: sample card composed on brand green, extractable.
      const sampleCanvas = document.createElement("canvas");
      renderPass(sampleCanvas, { ...base, format: "card", name: "Your Name Here", role: "your stack", seat: 1 });
      const og = document.createElement("canvas");
      renderOg(og, sampleCanvas);
      const ogCell = document.createElement("div");
      const ogLabel = document.createElement("p");
      ogLabel.textContent = "homepage og 1200x630";
      ogLabel.className = "font-mono text-xs py-2 opacity-80";
      og.className = "w-full rounded-lg";
      og.id = "og-home";
      ogCell.append(ogLabel, og);
      grid.append(ogCell);
      (window as Window & { __ogHome?: string }).__ogHome = og.toDataURL("image/png");
    })();
    return () => {
      disposed = true;
    };
  }, []);

  return (
    <main className="p-6">
      <h1 className="font-display text-3xl text-hh-yellow pb-4">Renderer fixtures</h1>
      <div ref={gridRef} className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3" />
    </main>
  );
}
