// All formats render through here, at any scale. The preview canvas and the
// export canvas call the same function, so what you see is what downloads.
//
// Visual language: riso print shop. Cream paper, green ink, pink
// misregistration, red rubber stamps, perforated tear lines, grain.

import { BRAND, EVENT, STACK } from "./brand";
import { FORMATS, styleSupports, type FormatId, type PhotoWindow, type StyleId } from "./layout";
import { coverSourceRect, type ViewState, DEFAULT_VIEW } from "./image-pipeline";
import { formatSeat } from "./seat";
import { getQr } from "./qr";
import { getFrameBg } from "./frames";

export interface Slot {
  bitmap: ImageBitmap | null;
  view: ViewState;
  label?: string; // per-person name on the team frame
}

export interface PassState {
  format: FormatId;
  styleId: StyleId;
  slots: Slot[];
  name: string;
  role: string;
  teamName: string;
  title: string;
  seat: number | null;
  passId: string;
}

type Ctx = CanvasRenderingContext2D;

function seeded(id: string): () => number {
  let h = 1779033703;
  for (let i = 0; i < id.length; i++) {
    h = Math.imul(h ^ id.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  };
}

function roundedPath(ctx: Ctx, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

/** Shrink-to-fit with a floor, then ellipsis. */
function fitText(
  ctx: Ctx,
  text: string,
  maxWidth: number,
  font: (size: number) => string,
  baseSize: number,
  minSize: number,
): { text: string; size: number } {
  let size = baseSize;
  ctx.font = font(size);
  while (ctx.measureText(text).width > maxWidth && size > minSize) {
    size -= 2;
    ctx.font = font(size);
  }
  let out = text;
  while (ctx.measureText(out).width > maxWidth && out.length > 1) {
    out = out.slice(0, -2) + "…";
  }
  return { text: out, size };
}

// ---------------------------------------------------------------------------
// print-shop texture kit

let grainCanvas: HTMLCanvasElement | null = null;

/** Deterministic paper-grain speckle, tiled as a pattern. */
function grainPattern(ctx: Ctx): CanvasPattern | null {
  if (!grainCanvas) {
    grainCanvas = document.createElement("canvas");
    grainCanvas.width = 180;
    grainCanvas.height = 180;
    const g = grainCanvas.getContext("2d");
    if (!g) return null;
    const img = g.createImageData(180, 180);
    let seed = 20261028;
    const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0), seed / 4294967296);
    for (let i = 0; i < img.data.length; i += 4) {
      const spec = rnd();
      img.data[i] = 20;
      img.data[i + 1] = 24;
      img.data[i + 2] = 18;
      img.data[i + 3] = spec < 0.82 ? 0 : spec * 26;
    }
    g.putImageData(img, 0, 0);
  }
  return ctx.createPattern(grainCanvas, "repeat");
}

function applyGrain(ctx: Ctx, W: number, H: number) {
  const p = grainPattern(ctx);
  if (!p) return;
  ctx.save();
  ctx.fillStyle = p;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

/** Riso misregistration: offset pass in a second ink, then the true pass. */
function risoText(
  ctx: Ctx,
  text: string,
  x: number,
  y: number,
  font: string,
  ink: string,
  ghost: string,
  off: number,
) {
  ctx.font = font;
  ctx.fillStyle = ghost;
  ctx.globalAlpha = 0.75;
  ctx.fillText(text, x + off, y + off * 0.8);
  ctx.globalAlpha = 1;
  ctx.fillStyle = ink;
  ctx.fillText(text, x, y);
}

/** Letters along a circle. Top arcs read upright at 12 o'clock; bottom at 6. */
function arcText(
  ctx: Ctx,
  text: string,
  cx: number,
  cy: number,
  radius: number,
  center: number,
  bottom: boolean,
  font: string,
  color: string,
  spacing = 0.78,
  halo?: string,
) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.font = font;
  ctx.textAlign = "center";
  const px = parseFloat(font.match(/([\d.]+)px/)?.[1] ?? "16");
  const step = (px / radius) * spacing;
  for (let i = 0; i < text.length; i++) {
    const a = center + (i - (text.length - 1) / 2) * step * (bottom ? -1 : 1);
    ctx.save();
    ctx.translate(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius);
    ctx.rotate(a + (bottom ? -Math.PI / 2 : Math.PI / 2));
    if (halo) {
      ctx.strokeStyle = halo;
      ctx.lineWidth = px * 0.3;
      ctx.lineJoin = "round";
      ctx.strokeText(text[i], 0, 0);
    }
    ctx.fillText(text[i], 0, 0);
    ctx.restore();
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------
// Goa motif kit: line-art in the same ink language as the rest of the sheet

/** Palm frond: curved stem with tapering leaflets, drawn as line art. */
function drawFrond(
  ctx: Ctx,
  bx: number,
  by: number,
  tx: number,
  ty: number,
  cx: number,
  cy: number,
  s: number,
  color: string,
  alpha: number,
) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 3.2 * s;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.quadraticCurveTo(cx, cy, tx, ty);
  ctx.stroke();
  const q = (t: number) => ({
    x: (1 - t) * (1 - t) * bx + 2 * (1 - t) * t * cx + t * t * tx,
    y: (1 - t) * (1 - t) * by + 2 * (1 - t) * t * cy + t * t * ty,
    dx: 2 * (1 - t) * (cx - bx) + 2 * t * (tx - cx),
    dy: 2 * (1 - t) * (cy - by) + 2 * t * (ty - cy),
  });
  const stemLen = Math.hypot(tx - bx, ty - by);
  for (let i = 1; i <= 9; i++) {
    const t = 0.08 + (i / 9) * 0.86;
    const p = q(t);
    const ang = Math.atan2(p.dy, p.dx);
    const len = stemLen * 0.26 * (1.06 - t);
    for (const side of [-1, 1]) {
      const la = ang + side * 1.02;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.quadraticCurveTo(
        p.x + Math.cos(la) * len * 0.55 + Math.cos(ang) * len * 0.25,
        p.y + Math.sin(la) * len * 0.55 + Math.sin(ang) * len * 0.25,
        p.x + Math.cos(la) * len * 0.8 + Math.cos(ang) * len * 0.55,
        p.y + Math.sin(la) * len * 0.8 + Math.sin(ang) * len * 0.55,
      );
      ctx.stroke();
    }
  }
  ctx.restore();
}

/** Riso sun: pink ghost pass, yellow disc, green ring and tick rays. */
function drawSun(ctx: Ctx, cx: number, cy: number, r: number, s: number) {
  ctx.save();
  ctx.globalAlpha = 0.75;
  ctx.fillStyle = BRAND.pink;
  ctx.beginPath();
  ctx.arc(cx + 5 * s, cy + 4 * s, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = BRAND.yellow;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 3 * s;
  ctx.stroke();
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * (r + 7 * s), cy + Math.sin(a) * (r + 7 * s));
    ctx.lineTo(cx + Math.cos(a) * (r + 18 * s), cy + Math.sin(a) * (r + 18 * s));
    ctx.stroke();
  }
  ctx.restore();
}

/** Rows of scallop wave lines. */
function drawWaves(ctx: Ctx, x: number, y: number, w: number, rows: number, s: number, color: string, alpha: number) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 2.6 * s;
  const r = 13 * s;
  for (let row = 0; row < rows; row++) {
    const ry = y + row * 13 * s;
    const off = row % 2 === 1 ? r : 0;
    for (let cx = x + r + off; cx <= x + w - r; cx += r * 2) {
      ctx.beginPath();
      ctx.arc(cx, ry, r, Math.PI, 0);
      ctx.stroke();
    }
  }
  ctx.restore();
}

/** Little fishing boat with a lateen sail, riding two wave strokes. */
function drawBoat(ctx: Ctx, x: number, y: number, k: number, s: number, color: string, alpha: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(k * s, k * s);
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 3 / k / s;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(-42, 0);
  ctx.quadraticCurveTo(0, 20, 42, 0);
  ctx.lineTo(34, -8);
  ctx.lineTo(-34, -8);
  ctx.closePath();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(0, -8);
  ctx.lineTo(0, -52);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(2, -50);
  ctx.quadraticCurveTo(30, -38, 26, -12);
  ctx.quadraticCurveTo(14, -20, 2, -14);
  ctx.closePath();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-52, 12);
  ctx.quadraticCurveTo(-42, 6, -32, 12);
  ctx.moveTo(36, 14);
  ctx.quadraticCurveTo(46, 8, 56, 14);
  ctx.stroke();
  ctx.restore();
}

/** Scallop shell: radiating ribs under an outer rim. */
function drawShell(ctx: Ctx, x: number, y: number, r: number, s: number, color: string, alpha: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.strokeStyle = color;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 2.6 * s;
  ctx.lineCap = "round";
  for (let i = -2; i <= 2; i++) {
    const a = -Math.PI / 2 + i * 0.38;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(Math.cos(a) * r * 0.6 + i * 2 * s, Math.sin(a) * r * 0.6, Math.cos(a) * r, Math.sin(a) * r);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.arc(0, -r * 0.12, r * 0.92, -Math.PI + 0.55, -0.55);
  ctx.stroke();
  ctx.restore();
}

/** Red rubber stamp: double ring, arc text, big center numeral. */
function drawStamp(ctx: Ctx, cx: number, cy: number, r: number, s: number, rot = -0.22) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rot);
  ctx.globalAlpha = 0.82;
  ctx.strokeStyle = BRAND.red;
  ctx.lineWidth = 4 * s;
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = 1.6 * s;
  ctx.setLineDash([5 * s, 4 * s]);
  ctx.beginPath();
  ctx.arc(0, 0, r * 0.74, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  arcText(ctx, "HACKER HOUSE GOA", 0, 0, r * 0.86, -Math.PI / 2, false, `700 ${r * 0.155}px ${STACK.mono}`, BRAND.red, 0.95);
  arcText(ctx, "28-31 OCT 2026", 0, 0, r * 0.86, Math.PI / 2, true, `700 ${r * 0.155}px ${STACK.mono}`, BRAND.red, 0.95);
  ctx.fillStyle = BRAND.red;
  ctx.textAlign = "center";
  ctx.font = `600 ${r * 0.62}px ${STACK.display}`;
  ctx.fillText("247", 0, r * 0.2);
  ctx.restore();
}

/** Perforated tear line: dashes plus real punched holes (PNG transparency). */
function perforate(ctx: Ctx, y: number, W: number, s: number) {
  ctx.save();
  ctx.strokeStyle = BRAND.green;
  ctx.globalAlpha = 0.45;
  ctx.lineWidth = 2 * s;
  ctx.setLineDash([9 * s, 7 * s]);
  ctx.beginPath();
  ctx.moveTo(30 * s, y);
  ctx.lineTo(W - 30 * s, y);
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.globalCompositeOperation = "destination-out";
  for (const x of [0, W]) {
    ctx.beginPath();
    ctx.arc(x, y, 16 * s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

/** The HACKER HOUSE lockup in ink, गोवा sticker straddling the gap. */
function drawWordmark(
  ctx: Ctx,
  cx: number,
  topY: number,
  size: number,
  s: number,
  ink: string = BRAND.green,
  ghost: string = BRAND.pink,
) {
  const lineGap = size * 0.82;
  ctx.textAlign = "center";
  risoText(ctx, "HACKER", cx, topY + size * 0.72 * s, `600 ${size * s}px ${STACK.display}`, ink, ghost, 4 * s);
  risoText(ctx, "HOUSE", cx, topY + (size * 0.72 + lineGap) * s, `600 ${size * s}px ${STACK.display}`, ink, ghost, 4 * s);

  const stW = size * 0.98 * s;
  const stH = size * 0.46 * s;
  ctx.save();
  ctx.translate(cx, topY + size * 0.82 * s);
  ctx.rotate(-0.09);
  roundedPath(ctx, -stW / 2, -stH / 2, stW, stH, stH / 2.6);
  ctx.fillStyle = BRAND.pink;
  ctx.fill();
  ctx.fillStyle = BRAND.yellow;
  ctx.font = `700 ${size * 0.3 * s}px ${STACK.devanagari}`;
  ctx.fillText("गोवा", 0, size * 0.11 * s);
  ctx.restore();
}

function drawPhoto(ctx: Ctx, slot: Slot, win: PhotoWindow, s: number, border: string = BRAND.green) {
  const { x, y, w, h, r } = { x: win.x * s, y: win.y * s, w: win.w * s, h: win.h * s, r: win.r * s };
  ctx.save();
  roundedPath(ctx, x, y, w, h, r);
  ctx.clip();
  if (slot.bitmap) {
    const { sx, sy, sw, sh } = coverSourceRect(slot.bitmap.width, slot.bitmap.height, w, h, slot.view);
    ctx.drawImage(slot.bitmap, sx, sy, sw, sh, x, y, w, h);
  } else {
    ctx.fillStyle = "#EFE8CF";
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = BRAND.green;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 2 * s;
    ctx.setLineDash([10 * s, 8 * s]);
    roundedPath(ctx, x + 14 * s, y + 14 * s, w - 28 * s, h - 28 * s, Math.max(0, r - 10 * s));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 0.6;
    ctx.fillStyle = BRAND.green;
    ctx.font = `700 ${26 * s}px ${STACK.mono}`;
    ctx.textAlign = "center";
    ctx.fillText("PASTE PHOTO HERE", x + w / 2, y + h / 2 + 9 * s);
    ctx.globalAlpha = 1;
  }
  ctx.restore();
  roundedPath(ctx, x, y, w, h, r);
  ctx.strokeStyle = border;
  ctx.lineWidth = 5 * s;
  ctx.stroke();
}

function drawBarcode(ctx: Ctx, x: number, y: number, w: number, h: number, rng: () => number, color: string) {
  let cx = x;
  ctx.fillStyle = color;
  while (cx < x + w) {
    const bw = 2 + Math.floor(rng() * 6);
    if (rng() > 0.42) ctx.fillRect(cx, y, bw, h);
    cx += bw + 2;
  }
}

function mrzLine(name: string, title: string): string {
  const clean = (t: string) =>
    t.toUpperCase().replace(/[^A-Z0-9]+/g, "<").replace(/<+/g, "<");
  return `HHG26<${clean(name || "BUILDER")}<${clean(title)}<FRAMEINGOA${"<".repeat(24)}`.slice(0, 52);
}

/** Green footer band: barcode, MRZ, dates, hashtag. Perforation above. */
function drawFooterBand(ctx: Ctx, W: number, H: number, s: number, state: PassState, bandH: number) {
  const y = H - bandH;
  perforate(ctx, y, W, s);
  ctx.fillStyle = BRAND.green;
  ctx.fillRect(0, y + 6 * s, W, bandH - 6 * s);
  const rng = seeded(state.passId);
  const by = y + 6 * s + (bandH - 6 * s) * 0.24;
  drawBarcode(ctx, 36 * s, by, 150 * s, (bandH - 6 * s) * 0.52, rng, BRAND.cream);
  ctx.fillStyle = BRAND.cream;
  ctx.textAlign = "left";
  ctx.font = `500 ${18 * s}px ${STACK.mono}`;
  ctx.fillText(
    mrzLine(state.format === "team" ? state.teamName : state.name, state.title),
    210 * s,
    y + 6 * s + (bandH - 6 * s) * 0.42,
  );
  ctx.font = `700 ${18 * s}px ${STACK.mono}`;
  ctx.fillText(`${EVENT.dates} · ${EVENT.place} · ${EVENT.tagline}`, 210 * s, y + 6 * s + (bandH - 6 * s) * 0.78);
  ctx.textAlign = "right";
  ctx.fillStyle = BRAND.yellow;
  ctx.font = `700 ${21 * s}px ${STACK.mono}`;
  ctx.fillText(EVENT.hashtag, W - 36 * s, y + 6 * s + (bandH - 6 * s) * 0.62);
}

/** Double-rule print frame around the sheet. */
function drawSheetFrame(ctx: Ctx, W: number, H: number, s: number) {
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 3 * s;
  ctx.strokeRect(20 * s, 20 * s, W - 40 * s, H - 40 * s);
  ctx.lineWidth = 1.2 * s;
  ctx.strokeRect(30 * s, 30 * s, W - 60 * s, H - 60 * s);
}

function label(ctx: Ctx, text: string, x: number, y: number, s: number, color = BRAND.green, size = 22) {
  ctx.fillStyle = color;
  ctx.font = `500 ${size * s}px ${STACK.mono}`;
  ctx.fillText(text.split("").join(" "), x, y);
}

function titlePill(ctx: Ctx, title: string, cx: number, y: number, s: number, size = 30) {
  if (!title) return;
  ctx.textAlign = "center";
  ctx.font = `700 ${size * s}px ${STACK.mono}`;
  const t = title.toUpperCase();
  const tw = ctx.measureText(t).width;
  const pw = tw + 64 * s;
  const ph = size * 1.75 * s;
  ctx.save();
  ctx.translate(cx, y + ph / 2);
  ctx.rotate(-0.012);
  roundedPath(ctx, -pw / 2, -ph / 2, pw, ph, ph / 2);
  ctx.fillStyle = BRAND.pink;
  ctx.fill();
  ctx.fillStyle = BRAND.yellow;
  ctx.fillText(t, 0, size * 0.36 * s);
  ctx.restore();
}

// ---------------------------------------------------------------------------
// formats

function renderCard(ctx: Ctx, state: PassState, s: number) {
  const spec = FORMATS.card;
  const W = spec.width * s;
  const H = spec.height * s;
  ctx.fillStyle = BRAND.cream;
  ctx.fillRect(0, 0, W, H);
  drawSheetFrame(ctx, W, H, s);

  // Goa in the margins: fronds arch in from the top corners behind the
  // wordmark, a riso sun rises on the right, waves flank the edition line,
  // a fishing boat and a shell hold the bottom corners.
  drawFrond(ctx, 52 * s, 68 * s, 330 * s, 200 * s, 210 * s, 40 * s, s, BRAND.green, 0.34);
  drawFrond(ctx, (1080 - 52) * s, 68 * s, (1080 - 330) * s, 200 * s, (1080 - 210) * s, 40 * s, s, BRAND.green, 0.34);
  drawSun(ctx, 925 * s, 300 * s, 46 * s, s);
  drawWaves(ctx, 62 * s, 315 * s, 130 * s, 3, s, BRAND.green, 0.4);

  drawWordmark(ctx, W / 2, 58 * s, 148, s);
  ctx.textAlign = "center";
  label(ctx, "BUILDER ID · EDITION 2026", W / 2, 338 * s, s);

  const win = spec.windows(1)[0];
  drawBoat(ctx, 130 * s, 1090 * s, 1.05, s, BRAND.green, 0.55);
  drawShell(ctx, 950 * s, 1120 * s, 52 * s, s, BRAND.green, 0.5);
  drawPhoto(ctx, state.slots[0] ?? { bitmap: null, view: DEFAULT_VIEW }, win, s);
  drawStamp(ctx, (win.x + win.w - 28) * s, (win.y + win.h - 14) * s, 96 * s, s);

  if (state.seat !== null) {
    ctx.save();
    ctx.translate(W - 64 * s, 400 * s);
    ctx.rotate(Math.PI / 2);
    ctx.textAlign = "left";
    ctx.fillStyle = BRAND.red;
    ctx.font = `700 ${33 * s}px ${STACK.mono}`;
    ctx.fillText(`SEAT ${formatSeat(state.seat)}`, 0, 0);
    ctx.restore();
  }

  ctx.textAlign = "center";
  const name = fitText(ctx, state.name || "Your Name", 880 * s, (z) => `500 ${z * s}px ${STACK.display}`, 96, 54);
  risoText(ctx, name.text, W / 2, 1128 * s, `500 ${name.size * s}px ${STACK.display}`, BRAND.green, BRAND.pink, 2.5 * s);

  const role = fitText(ctx, (state.role || "builder").toUpperCase(), 860 * s, (z) => `500 ${z * s}px ${STACK.mono}`, 29, 20);
  ctx.fillStyle = BRAND.green;
  ctx.globalAlpha = 0.8;
  ctx.font = `500 ${role.size * s}px ${STACK.mono}`;
  ctx.fillText(role.text, W / 2, 1172 * s);
  ctx.globalAlpha = 1;

  titlePill(ctx, state.title, W / 2, 1196 * s, s);

  applyGrain(ctx, W, H);
  drawFooterBand(ctx, W, H, s, state, 96 * s);
}

function renderTeam(ctx: Ctx, state: PassState, s: number, bg?: ImageBitmap | null) {
  const spec = FORMATS.team;
  const W = spec.width * s;
  const H = spec.height * s;
  const filled = state.slots.filter((sl) => sl.bitmap).length || 1;
  const wins = spec.windows(filled);

  if (bg) {
    const cover = Math.max(W / bg.width, H / bg.height);
    ctx.drawImage(bg, (W - bg.width * cover) / 2, (H - bg.height * cover) / 2, bg.width * cover, bg.height * cover);
    wordmarkSticker(ctx, 150 * s, 96 * s, s);
    ctx.textAlign = "center";
    const team = fitText(ctx, (state.teamName || "The Squad").toUpperCase(), 520 * s, (z) => `700 ${z * s}px ${STACK.mono}`, 40, 26);
    drawRibbon(ctx, W / 2, 90 * s, Math.max(380 * s, ctx.measureText(team.text).width + 90 * s), 64 * s, s, BRAND.green);
    ctx.fillStyle = BRAND.cream;
    ctx.font = `700 ${team.size * s}px ${STACK.mono}`;
    ctx.fillText(team.text, W / 2, 101 * s);
    titlePill(ctx, state.title, W / 2, 168 * s, s, 25);
  } else {
    ctx.fillStyle = BRAND.cream;
    ctx.fillRect(0, 0, W, H);
    drawSheetFrame(ctx, W, H, s);

    drawFrond(ctx, (1600 - 48) * s, 60 * s, (1600 - 300) * s, 175 * s, (1600 - 190) * s, 36 * s, s, BRAND.green, 0.32);
    drawSun(ctx, 1425 * s, 122 * s, 40 * s, s);
    drawWaves(ctx, 66 * s, 730 * s, 130 * s, 3, s, BRAND.green, 0.4);
    drawWaves(ctx, (1600 - 196) * s, 730 * s, 130 * s, 3, s, BRAND.green, 0.4);
    drawBoat(ctx, 120 * s, 700 * s, 0.9, s, BRAND.green, 0.55);

    drawWordmark(ctx, 245 * s, 42 * s, 88, s);
    ctx.textAlign = "left";
    const team = fitText(ctx, state.teamName || "The Squad", 880 * s, (z) => `500 ${z * s}px ${STACK.display}`, 86, 46);
    risoText(ctx, team.text, 470 * s, 122 * s, `500 ${team.size * s}px ${STACK.display}`, BRAND.green, BRAND.pink, 2.5 * s);
    label(ctx, `TEAM MANIFEST · ${filled} BUILDER${filled > 1 ? "S" : ""} · EDITION 2026`, 470 * s, 170 * s, s, BRAND.green, 20);
  }

  wins.forEach((win, i) => {
    const slot = state.slots[i] ?? { bitmap: null, view: DEFAULT_VIEW };
    if (bg) {
      taggedPrint(ctx, slot, win, s, i % 2 ? 0.022 : -0.025, slot.label || `Builder ${i + 1}`);
    } else {
      drawPhoto(ctx, slot, win, s);
      ctx.textAlign = "center";
      const person = fitText(ctx, slot.label || `Builder ${i + 1}`, win.w * s, (z) => `700 ${z * s}px ${STACK.mono}`, 28, 19);
      ctx.fillStyle = BRAND.green;
      ctx.font = `700 ${person.size * s}px ${STACK.mono}`;
      ctx.fillText(person.text, (win.x + win.w / 2) * s, (win.y + win.h + 50) * s);
    }
  });

  const lastWin = wins[wins.length - 1];
  drawStamp(ctx, (lastWin.x + lastWin.w - 16) * s, (lastWin.y + lastWin.h - 6) * s, 82 * s, s, bg ? 0.5 : 0.16);

  if (!bg) titlePill(ctx, state.title, W / 2, 736 * s, s, 27);

  applyGrain(ctx, W, H);
  drawFooterBand(ctx, W, H, s, state, 86 * s);
}

function renderPfp(ctx: Ctx, state: PassState, s: number, bg?: ImageBitmap | null) {
  const spec = FORMATS.pfp;
  const W = spec.width * s;
  const cx = W / 2;
  const cy = W / 2;
  const rOuter = 540 * s;
  const rBand = 462 * s;

  if (bg) {
    // AI art fills the square; it stays visible in the corners and in the
    // ring between the photo and the paper band
    const cover = Math.max(W / bg.width, W / bg.height);
    ctx.drawImage(bg, (W - bg.width * cover) / 2, (W - bg.height * cover) / 2, bg.width * cover, bg.height * cover);
  } else {
    // green corners behind the paper ring, planted with cream fronds
    ctx.fillStyle = BRAND.green;
    ctx.fillRect(0, 0, W, W);
    drawFrond(ctx, 24 * s, 24 * s, 235 * s, 148 * s, 150 * s, 20 * s, s, BRAND.cream, 0.4);
    drawFrond(ctx, (1080 - 24) * s, 24 * s, (1080 - 235) * s, 148 * s, (1080 - 150) * s, 20 * s, s, BRAND.cream, 0.4);
    drawFrond(ctx, 24 * s, (1080 - 24) * s, 235 * s, (1080 - 148) * s, 150 * s, (1080 - 20) * s, s, BRAND.cream, 0.4);
    drawFrond(ctx, (1080 - 24) * s, (1080 - 24) * s, (1080 - 235) * s, (1080 - 148) * s, (1080 - 150) * s, (1080 - 20) * s, s, BRAND.cream, 0.4);
  }

  drawPhoto(ctx, state.slots[0] ?? { bitmap: null, view: DEFAULT_VIEW }, spec.windows(1)[0], s, BRAND.cream);

  if (bg) {
    // the art keeps its own border; just ring the photo for definition
    ctx.beginPath();
    ctx.arc(cx, cy, 406 * s, 0, Math.PI * 2);
    ctx.strokeStyle = BRAND.green;
    ctx.lineWidth = 5 * s;
    ctx.stroke();
  } else {
    // paper ring
    ctx.beginPath();
    ctx.arc(cx, cy, rOuter, 0, Math.PI * 2);
    ctx.arc(cx, cy, rBand, 0, Math.PI * 2, true);
    ctx.fillStyle = BRAND.cream;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(cx, cy, rBand, 0, Math.PI * 2);
    ctx.strokeStyle = BRAND.green;
    ctx.lineWidth = 5 * s;
    ctx.stroke();
  }

  const mid = (rOuter + rBand) / 2;
  const halo = bg ? BRAND.cream : undefined;
  arcText(ctx, "HACKER", cx, cy, mid - 14 * s, -Math.PI / 2 - 0.46, false, `600 ${56 * s}px ${STACK.display}`, BRAND.green, 0.78, halo);
  arcText(ctx, "HOUSE", cx, cy, mid - 14 * s, -Math.PI / 2 + 0.44, false, `600 ${56 * s}px ${STACK.display}`, BRAND.green, 0.78, halo);
  arcText(ctx, "28-31 OCT 2026 · GOA, INDIA", cx, cy, mid - 12 * s, Math.PI / 2, true, `700 ${34 * s}px ${STACK.mono}`, BRAND.green, 0.78, halo);

  // गोवा sticker at 12 o'clock
  const stW = 196 * s;
  const stH = 86 * s;
  ctx.save();
  ctx.translate(cx, cy - rBand - 38 * s);
  ctx.rotate(-0.08);
  roundedPath(ctx, -stW / 2, -stH / 2, stW, stH, stH / 2.6);
  ctx.fillStyle = BRAND.pink;
  ctx.fill();
  ctx.fillStyle = BRAND.yellow;
  ctx.textAlign = "center";
  ctx.font = `700 ${47 * s}px ${STACK.devanagari}`;
  ctx.fillText("गोवा", 0, 17 * s);
  ctx.restore();

  drawStamp(ctx, cx + rBand * 0.66, cy + rBand * 0.75, 88 * s, s, 0.18);
  applyGrain(ctx, W, W);
}

/** Four-point sparkle. */
function drawSparkle(ctx: Ctx, x: number, y: number, r: number, color: string, alpha: number) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.globalAlpha = alpha;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.quadraticCurveTo(x, y, x, y + r);
  ctx.quadraticCurveTo(x, y, x - r, y);
  ctx.quadraticCurveTo(x, y, x, y - r);
  ctx.fill();
  ctx.restore();
}

/** Standing surfboard with a center stripe. */
function drawSurfboard(ctx: Ctx, x: number, y: number, h: number, rot: number, s: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rot);
  const w = h * 0.32;
  ctx.fillStyle = BRAND.yellow;
  ctx.strokeStyle = BRAND.greenDeep;
  ctx.lineWidth = 3.5 * s;
  ctx.beginPath();
  ctx.moveTo(0, -h / 2);
  ctx.quadraticCurveTo(w / 2, -h * 0.18, w * 0.42, h * 0.16);
  ctx.quadraticCurveTo(w * 0.34, h * 0.44, 0, h / 2);
  ctx.quadraticCurveTo(-w * 0.34, h * 0.44, -w * 0.42, h * 0.16);
  ctx.quadraticCurveTo(-w / 2, -h * 0.18, 0, -h / 2);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(0, -h * 0.42);
  ctx.lineTo(0, h * 0.42);
  ctx.stroke();
  ctx.restore();
}

/** Signpost with stacked arrow boards. */
function drawSignpost(ctx: Ctx, x: number, y: number, s: number, words: string[]) {
  ctx.save();
  ctx.strokeStyle = BRAND.greenDeep;
  ctx.fillStyle = BRAND.greenDeep;
  ctx.lineWidth = 5 * s;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x, y - 150 * s);
  ctx.stroke();
  words.forEach((word, i) => {
    const by = y - (138 - i * 46) * s;
    const dir = i % 2 === 0 ? 1 : -1;
    const bw = 118 * s;
    const bh = 36 * s;
    ctx.save();
    ctx.translate(x, by);
    ctx.beginPath();
    if (dir === 1) {
      ctx.moveTo(-bw / 2, -bh / 2);
      ctx.lineTo(bw / 2 - 14 * s, -bh / 2);
      ctx.lineTo(bw / 2, 0);
      ctx.lineTo(bw / 2 - 14 * s, bh / 2);
      ctx.lineTo(-bw / 2, bh / 2);
    } else {
      ctx.moveTo(bw / 2, -bh / 2);
      ctx.lineTo(-bw / 2 + 14 * s, -bh / 2);
      ctx.lineTo(-bw / 2, 0);
      ctx.lineTo(-bw / 2 + 14 * s, bh / 2);
      ctx.lineTo(bw / 2, bh / 2);
    }
    ctx.closePath();
    ctx.fillStyle = BRAND.yellow;
    ctx.fill();
    ctx.strokeStyle = BRAND.greenDeep;
    ctx.lineWidth = 3 * s;
    ctx.stroke();
    ctx.fillStyle = BRAND.greenDeep;
    ctx.font = `700 ${19 * s}px ${STACK.mono}`;
    ctx.textAlign = "center";
    ctx.fillText(word, 0, 7 * s);
    ctx.restore();
  });
  ctx.restore();
}

/** Postage stamp: perforated edge, palm and sun inside. */
function drawPostage(ctx: Ctx, x: number, y: number, w: number, h: number, s: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-0.06);
  ctx.fillStyle = "#FFFEF8";
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 2.4 * s;
  ctx.fillRect(0, 0, w, h);
  ctx.setLineDash([7 * s, 5 * s]);
  ctx.strokeRect(0, 0, w, h);
  ctx.setLineDash([]);
  ctx.strokeRect(8 * s, 8 * s, w - 16 * s, h - 16 * s);
  ctx.fillStyle = BRAND.yellow;
  ctx.beginPath();
  ctx.arc(w * 0.68, h * 0.42, 13 * s, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = BRAND.green;
  drawFrond(ctx, w * 0.26, h * 0.78, w * 0.6, h * 0.28, w * 0.28, h * 0.34, s * 0.55, BRAND.green, 0.9);
  ctx.fillStyle = BRAND.green;
  ctx.font = `700 ${13 * s}px ${STACK.mono}`;
  ctx.textAlign = "center";
  ctx.fillText("GOA · 26", w / 2, h - 13 * s);
  ctx.restore();
}

/** Ribbon banner with notched tails, text centered. */
function drawRibbon(ctx: Ctx, cx: number, cy: number, w: number, h: number, s: number, fill: string) {
  ctx.save();
  ctx.fillStyle = fill;
  ctx.strokeStyle = BRAND.greenDeep;
  ctx.lineWidth = 3 * s;
  const tail = 34 * s;
  // tails
  for (const dir of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(cx + dir * (w / 2 - 6 * s), cy - h / 2 + 8 * s);
    ctx.lineTo(cx + dir * (w / 2 + tail), cy - h / 2 + 4 * s);
    ctx.lineTo(cx + dir * (w / 2 + tail - 16 * s), cy);
    ctx.lineTo(cx + dir * (w / 2 + tail), cy + h / 2 - 4 * s);
    ctx.lineTo(cx + dir * (w / 2 - 6 * s), cy + h / 2 - 8 * s);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
  // body
  ctx.beginPath();
  ctx.moveTo(cx - w / 2, cy - h / 2);
  ctx.quadraticCurveTo(cx, cy - h / 2 - 6 * s, cx + w / 2, cy - h / 2);
  ctx.lineTo(cx + w / 2, cy + h / 2);
  ctx.quadraticCurveTo(cx, cy + h / 2 + 6 * s, cx - w / 2, cy + h / 2);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

/** Poster ID: the dense collectible. Circle photo, stamps, signpost, QR. */
function renderPoster(ctx: Ctx, state: PassState, s: number) {
  const spec = FORMATS.poster;
  const W = spec.width * s;
  const H = spec.height * s;
  ctx.fillStyle = BRAND.cream;
  ctx.fillRect(0, 0, W, H);
  drawSheetFrame(ctx, W, H, s);

  // corner paraphernalia
  drawPostage(ctx, 56 * s, 52 * s, 130 * s, 96 * s, s);
  ctx.save();
  ctx.translate(W - 118 * s, 112 * s);
  ctx.rotate(0.1);
  arcText(ctx, "BUILD IN GOA", 0, 0, 58 * s, -Math.PI / 2, false, `700 ${15 * s}px ${STACK.mono}`, BRAND.green, 0.9);
  arcText(ctx, "SHIP FROM PARADISE", 0, 0, 58 * s, Math.PI / 2, true, `700 ${15 * s}px ${STACK.mono}`, BRAND.green, 0.9);
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 2.4 * s;
  ctx.beginPath();
  ctx.arc(0, 0, 74 * s, 0, Math.PI * 2);
  ctx.stroke();
  drawFrond(ctx, -18 * s, 26 * s, 22 * s, -26 * s, -26 * s, -8 * s, s * 0.8, BRAND.green, 0.9);
  ctx.restore();

  // one-line lockup: HACKER [गोवा] HOUSE
  ctx.textAlign = "center";
  risoText(ctx, "HACKER", W / 2 - 232 * s, 234 * s, `600 ${118 * s}px ${STACK.display}`, BRAND.green, BRAND.pink, 4 * s);
  risoText(ctx, "HOUSE", W / 2 + 250 * s, 234 * s, `600 ${118 * s}px ${STACK.display}`, BRAND.green, BRAND.pink, 4 * s);
  const stW = 138 * s;
  const stH = 64 * s;
  ctx.save();
  ctx.translate(W / 2 + 6 * s, 200 * s);
  ctx.rotate(-0.09);
  roundedPath(ctx, -stW / 2, -stH / 2, stW, stH, stH / 2.6);
  ctx.fillStyle = BRAND.pink;
  ctx.fill();
  ctx.fillStyle = BRAND.yellow;
  ctx.font = `700 ${40 * s}px ${STACK.devanagari}`;
  ctx.fillText("गोवा", 0, 14 * s);
  ctx.restore();
  label(ctx, "4 DAYS · ONE RHYTHM · EVERYTHING INTENTIONAL", W / 2, 292 * s, s, BRAND.green, 19);

  // side rails
  ctx.save();
  ctx.translate(58 * s, 560 * s);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillStyle = BRAND.red;
  ctx.font = `700 ${24 * s}px ${STACK.mono}`;
  ctx.fillText("28-31 OCT 2026", 0, 0);
  ctx.restore();
  ctx.save();
  ctx.translate(W - 58 * s, 560 * s);
  ctx.rotate(Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillStyle = BRAND.red;
  ctx.font = `700 ${24 * s}px ${STACK.mono}`;
  ctx.fillText("GOA, INDIA", 0, 0);
  ctx.restore();

  // scenery behind the circle
  drawSparkle(ctx, 210 * s, 350 * s, 12 * s, BRAND.pink, 0.8);
  drawSparkle(ctx, 880 * s, 370 * s, 10 * s, BRAND.yellow, 0.9);
  drawSparkle(ctx, 930 * s, 620 * s, 12 * s, BRAND.pink, 0.7);
  drawSparkle(ctx, 150 * s, 640 * s, 10 * s, BRAND.yellow, 0.9);
  drawBirds(
    ctx,
    [
      [200 * s, 420 * s],
      [250 * s, 395 * s],
      [860 * s, 430 * s],
    ],
    BRAND.green,
    s,
  );
  drawFrond(ctx, 40 * s, 980 * s, 250 * s, 760 * s, 60 * s, 800 * s, s, BRAND.green, 0.55);
  drawFrond(ctx, (1080 - 40) * s, 980 * s, (1080 - 250) * s, 760 * s, (1080 - 60) * s, 800 * s, s, BRAND.green, 0.55);
  drawSurfboard(ctx, 128 * s, 850 * s, 240 * s, -0.1, s);
  drawSignpost(ctx, 950 * s, 940 * s, s, ["BUILD", "SHIP", "REPEAT"]);
  drawWaves(ctx, 62 * s, 1010 * s, 150 * s, 2, s, BRAND.green, 0.4);
  drawWaves(ctx, (1080 - 212) * s, 1030 * s, 150 * s, 2, s, BRAND.green, 0.4);

  // circular photo with double ring
  const win = spec.windows(1)[0];
  const ccx = (win.x + win.w / 2) * s;
  const ccy = (win.y + win.h / 2) * s;
  ctx.beginPath();
  ctx.arc(ccx, ccy, (win.w / 2 + 26) * s, 0, Math.PI * 2);
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 8 * s;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(ccx, ccy, (win.w / 2 + 14) * s, 0, Math.PI * 2);
  ctx.strokeStyle = BRAND.red;
  ctx.lineWidth = 2.6 * s;
  ctx.setLineDash([8 * s, 7 * s]);
  ctx.stroke();
  ctx.setLineDash([]);
  drawPhoto(ctx, state.slots[0] ?? { bitmap: null, view: DEFAULT_VIEW }, win, s);

  // name ribbon + role + title plate
  ctx.textAlign = "center";
  const name = fitText(ctx, (state.name || "Your Name").toUpperCase(), 420 * s, (z) => `700 ${z * s}px ${STACK.mono}`, 40, 24);
  drawRibbon(ctx, W / 2, 1040 * s, Math.max(320 * s, ctx.measureText(name.text).width + 80 * s), 66 * s, s, BRAND.green);
  ctx.fillStyle = BRAND.cream;
  ctx.font = `700 ${name.size * s}px ${STACK.mono}`;
  ctx.fillText(name.text, W / 2, 1052 * s);

  const role = fitText(ctx, (state.role || "builder").toUpperCase(), 380 * s, (z) => `700 ${z * s}px ${STACK.mono}`, 24, 17);
  const rw = ctx.measureText(role.text).width + 56 * s;
  roundedPath(ctx, W / 2 - rw / 2, 1096 * s, rw, 44 * s, 22 * s);
  ctx.fillStyle = BRAND.red;
  ctx.fill();
  ctx.fillStyle = BRAND.cream;
  ctx.font = `700 ${role.size * s}px ${STACK.mono}`;
  ctx.fillText(role.text, W / 2, 1126 * s);

  if (state.title) {
    ctx.font = `700 ${26 * s}px ${STACK.mono}`;
    const t = `✶ ${state.title.toUpperCase()} ✶`;
    const tw = ctx.measureText(t).width + 70 * s;
    roundedPath(ctx, W / 2 - tw / 2, 1160 * s, tw, 52 * s, 12 * s);
    ctx.fillStyle = "#FFFEF8";
    ctx.fill();
    ctx.strokeStyle = BRAND.green;
    ctx.lineWidth = 2.6 * s;
    ctx.stroke();
    ctx.fillStyle = BRAND.pink;
    ctx.fillText(t, W / 2, 1195 * s);
  }

  // info row: QR / unique id + sunset / hosted by
  const infoY = 1260 * s;
  ctx.strokeStyle = BRAND.green;
  ctx.globalAlpha = 0.5;
  ctx.setLineDash([10 * s, 8 * s]);
  ctx.lineWidth = 2 * s;
  ctx.beginPath();
  ctx.moveTo(60 * s, infoY);
  ctx.lineTo(W - 60 * s, infoY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;

  const qr = getQr();
  if (qr) {
    ctx.drawImage(qr, 90 * s, (1290 + 6) * s, 150 * s, 150 * s);
    label(ctx, "SCAN TO JOIN", 165 * s, 1480 * s, s, BRAND.green, 15);
    ctx.textAlign = "center";
  } else {
    const rng = seeded(state.passId);
    drawBarcode(ctx, 90 * s, 1320 * s, 150 * s, 90 * s, rng, BRAND.greenDeep);
  }

  ctx.textAlign = "center";
  label(ctx, "BUILDER ID", W / 2, 1330 * s, s, BRAND.green, 17);
  ctx.fillStyle = BRAND.greenDeep;
  ctx.font = `700 ${34 * s}px ${STACK.mono}`;
  const uid = state.seat !== null ? `HHG-${String(state.seat).padStart(3, "0")}-26` : "HHG-···-26";
  ctx.fillText(uid, W / 2, 1372 * s);
  // tiny sunset over waves
  ctx.fillStyle = BRAND.red;
  ctx.beginPath();
  ctx.arc(W / 2, 1436 * s, 26 * s, Math.PI, 0);
  ctx.fill();
  drawWaves(ctx, W / 2 - 70 * s, 1444 * s, 140 * s, 1, s, BRAND.green, 0.7);

  ctx.textAlign = "center";
  label(ctx, "HOSTED BY", W - 190 * s, 1330 * s, s, BRAND.green, 17);
  ctx.fillStyle = BRAND.greenDeep;
  ctx.font = `600 ${52 * s}px ${STACK.display}`;
  ctx.fillText("2:47PM", W - 190 * s, 1392 * s);
  ctx.font = `700 ${22 * s}px ${STACK.mono}`;
  ctx.fillText("STUDIO", W - 190 * s, 1424 * s);

  applyGrain(ctx, W, H);
  drawFooterBand(ctx, W, H, s, state, 88 * s);
}

// ---------------------------------------------------------------------------
// scene styles: the whole postcard behind the photo

/** Filled palm silhouette: tapered trunk, six leaves, two coconuts. */
function drawPalm(ctx: Ctx, x: number, baseY: number, h: number, lean: number, color: string, alpha: number, s: number) {
  const topX = x + lean * h * 0.32;
  const topY = baseY - h;
  ctx.save();
  ctx.fillStyle = color;
  ctx.globalAlpha = alpha;
  ctx.beginPath();
  ctx.moveTo(x - 11 * s, baseY);
  ctx.quadraticCurveTo(x + lean * h * 0.08, baseY - h * 0.55, topX - 4 * s, topY);
  ctx.lineTo(topX + 4 * s, topY);
  ctx.quadraticCurveTo(x + lean * h * 0.16 + 9 * s, baseY - h * 0.5, x + 13 * s, baseY);
  ctx.closePath();
  ctx.fill();
  const leaves: [number, number][] = [
    [-2.75, 0.4],
    [-2.15, 0.5],
    [-1.4, 0.54],
    [-0.75, 0.52],
    [-0.15, 0.46],
    [0.4, 0.38],
  ];
  for (const [ang, k] of leaves) {
    const L = h * k;
    const ex = topX + Math.cos(ang) * L;
    const ey = topY + Math.sin(ang) * L;
    const mx = topX + Math.cos(ang) * L * 0.5;
    const my = topY + Math.sin(ang) * L * 0.5;
    const nx = Math.cos(ang + Math.PI / 2);
    const ny = Math.sin(ang + Math.PI / 2);
    const bulge = L * 0.2;
    ctx.beginPath();
    ctx.moveTo(topX, topY);
    ctx.quadraticCurveTo(mx + nx * bulge, my + ny * bulge, ex, ey);
    ctx.quadraticCurveTo(mx - nx * bulge * 0.35, my - ny * bulge * 0.35, topX, topY);
    ctx.fill();
  }
  ctx.beginPath();
  ctx.arc(topX - 9 * s, topY + 12 * s, 8 * s, 0, Math.PI * 2);
  ctx.arc(topX + 9 * s, topY + 15 * s, 8 * s, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawCloud(ctx: Ctx, x: number, y: number, k: number, color: string, alpha: number, s: number) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.globalAlpha = alpha;
  for (const [dx, dy, r] of [
    [0, 0, 26],
    [24, -10, 20],
    [48, 0, 24],
    [24, 8, 22],
  ]) {
    ctx.beginPath();
    ctx.arc(x + dx * k * s, y + dy * k * s, r * k * s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawBirds(ctx: Ctx, pts: [number, number][], color: string, s: number) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.6 * s;
  ctx.lineCap = "round";
  for (const [x, y] of pts) {
    ctx.beginPath();
    ctx.arc(x - 8 * s, y, 8 * s, Math.PI * 1.15, Math.PI * 1.85);
    ctx.arc(x + 8 * s, y, 8 * s, Math.PI * 1.15, Math.PI * 1.85);
    ctx.stroke();
  }
  ctx.restore();
}

/** Festival bunting: a sagging string of alternating pennants. */
function drawBunting(ctx: Ctx, x0: number, y0: number, x1: number, y1: number, sag: number, s: number) {
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2 + sag;
  ctx.save();
  ctx.strokeStyle = "#FFFEF8";
  ctx.globalAlpha = 0.9;
  ctx.lineWidth = 2.6 * s;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.quadraticCurveTo(cx, cy, x1, y1);
  ctx.stroke();
  const colors = [BRAND.yellow, BRAND.pink, "#FFFEF8"];
  for (let i = 1; i <= 8; i++) {
    const t = i / 9;
    const px = (1 - t) * (1 - t) * x0 + 2 * (1 - t) * t * cx + t * t * x1;
    const py = (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * cy + t * t * y1;
    ctx.fillStyle = colors[i % 3];
    ctx.beginPath();
    ctx.moveTo(px - 13 * s, py);
    ctx.lineTo(px + 13 * s, py);
    ctx.lineTo(px, py + 30 * s);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

function drawUmbrella(ctx: Ctx, x: number, y: number, r: number, s: number) {
  ctx.save();
  ctx.strokeStyle = BRAND.greenDeep;
  ctx.lineWidth = 4 * s;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x, y + r * 0.9);
  ctx.stroke();
  for (let i = 0; i < 6; i++) {
    ctx.fillStyle = i % 2 === 0 ? BRAND.pink : "#FFFEF8";
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.arc(x, y, r, Math.PI + (i * Math.PI) / 6, Math.PI + ((i + 1) * Math.PI) / 6);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

interface ScenePalette {
  sky: [string, string];
  sea: [string, string];
  sand: string;
  ink: string; // text ink over sand
  ghost: string;
  palm: string;
  wave: string;
}

const DAY: ScenePalette = {
  sky: ["#9BDCD6", "#D6F2EA"],
  sea: ["#2AA7AC", "#117F89"],
  sand: "#F1DDA3",
  ink: BRAND.greenDeep,
  ghost: BRAND.pink,
  palm: BRAND.green,
  wave: "#FFFEF8",
};

const SUNSET: ScenePalette = {
  sky: ["#3A1E55", "#FF9E4F"],
  sea: ["#174A5C", "#0E6070"],
  sand: "#CDA76F",
  ink: "#FFFBE8",
  ghost: BRAND.pink,
  palm: "#092E1E",
  wave: "#FFE9B8",
};

/** Tilted cream photo print with washi tape; sits naturally on any art. */
function taggedPrint(ctx: Ctx, slot: Slot, win: PhotoWindow, s: number, tilt: number, chinText?: string) {
  const chin = 46;
  const px = (win.x - 18) * s;
  const py = (win.y - 18) * s;
  const pw = (win.w + 36) * s;
  const ph = (win.h + 36 + chin) * s;
  // tilt the whole print like a photo taped into a travel journal
  ctx.save();
  ctx.translate(px + pw / 2, py + ph / 2);
  ctx.rotate(tilt);
  ctx.translate(-(px + pw / 2), -(py + ph / 2));
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.3)";
  ctx.shadowBlur = 26 * s;
  ctx.shadowOffsetY = 10 * s;
  ctx.fillStyle = BRAND.cream;
  roundedPath(ctx, px, py, pw, ph, 18 * s);
  ctx.fill();
  ctx.restore();
  roundedPath(ctx, px, py, pw, ph, 18 * s);
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 2.6 * s;
  ctx.stroke();
  drawPhoto(ctx, slot, win, s, BRAND.cream);
  if (chinText) {
    ctx.fillStyle = BRAND.greenDeep;
    ctx.textAlign = "center";
    const fit = fitText(ctx, chinText, (win.w - 24) * s, (z) => `700 ${z * s}px ${STACK.mono}`, 24, 15);
    ctx.font = `700 ${fit.size * s}px ${STACK.mono}`;
    ctx.fillText(fit.text, (win.x + win.w / 2) * s, (win.y + win.h + 44) * s);
  }
  // washi tape holding the print down, in brand inks
  const tape = (tx: number, ty: number, ang: number, color: string) => {
    ctx.save();
    ctx.translate(tx, ty);
    ctx.rotate(ang);
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = color;
    ctx.fillRect(-78 * s, -20 * s, 156 * s, 40 * s);
    ctx.globalAlpha = 1;
    ctx.restore();
  };
  tape(px + 8 * s, py + 4 * s, -0.6, BRAND.yellow);
  tape(px + pw - 8 * s, py + 4 * s, 0.6, BRAND.pink);
  ctx.restore();
}

/** Wordmark on a rotated cream sticker plate, legible over any art. */
function wordmarkSticker(ctx: Ctx, x: number, y: number, s: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-0.05);
  roundedPath(ctx, -118 * s, -66 * s, 236 * s, 148 * s, 16 * s);
  ctx.fillStyle = BRAND.cream;
  ctx.fill();
  ctx.strokeStyle = BRAND.green;
  ctx.lineWidth = 2.6 * s;
  ctx.stroke();
  drawWordmark(ctx, 0, -52 * s, 56, s);
  ctx.restore();
}

/** Overlays shared by both scene paths: polaroid, identity plates, band. */
function sceneOverlays(ctx: Ctx, state: PassState, s: number, p: ScenePalette, onArt: boolean) {
  const spec = FORMATS[state.format];
  const W = spec.width * s;
  const H = spec.height * s;

  const win = spec.windows(1)[0];
  taggedPrint(
    ctx,
    state.slots[0] ?? { bitmap: null, view: DEFAULT_VIEW },
    win,
    s,
    -0.025,
    state.seat !== null ? `SEAT ${formatSeat(state.seat)}` : undefined,
  );
  drawStamp(ctx, (win.x + win.w - 6) * s, (win.y + win.h + 10) * s, 80 * s, s);

  const nameY = state.format === "poster" ? 1140 : 1170;
  ctx.textAlign = "center";
  if (onArt) {
    // opaque plates guarantee legibility on any generated art
    const name = fitText(ctx, (state.name || "Your Name").toUpperCase(), 420 * s, (z) => `700 ${z * s}px ${STACK.mono}`, 38, 24);
    drawRibbon(ctx, W / 2, (nameY - 14) * s, Math.max(320 * s, ctx.measureText(name.text).width + 80 * s), 64 * s, s, BRAND.green);
    ctx.fillStyle = BRAND.cream;
    ctx.font = `700 ${name.size * s}px ${STACK.mono}`;
    ctx.fillText(name.text, W / 2, (nameY - 3) * s);
    const role = fitText(ctx, (state.role || "builder").toUpperCase(), 380 * s, (z) => `700 ${z * s}px ${STACK.mono}`, 22, 16);
    const rw = ctx.measureText(role.text).width + 52 * s;
    roundedPath(ctx, W / 2 - rw / 2, (nameY + 28) * s, rw, 40 * s, 20 * s);
    ctx.fillStyle = BRAND.red;
    ctx.fill();
    ctx.fillStyle = BRAND.cream;
    ctx.font = `700 ${role.size * s}px ${STACK.mono}`;
    ctx.fillText(role.text, W / 2, (nameY + 55) * s);
    titlePill(ctx, state.title, W / 2, (nameY + 78) * s, s, 24);
  } else {
    const name = fitText(ctx, state.name || "Your Name", 860 * s, (z) => `500 ${z * s}px ${STACK.display}`, state.format === "poster" ? 84 : 78, 48);
    risoText(ctx, name.text, W / 2, nameY * s, `500 ${name.size * s}px ${STACK.display}`, p.ink, p.ghost, 2.5 * s);
    const role = fitText(ctx, (state.role || "builder").toUpperCase(), 800 * s, (z) => `500 ${z * s}px ${STACK.mono}`, 27, 19);
    ctx.fillStyle = p.ink;
    ctx.globalAlpha = 0.85;
    ctx.font = `500 ${role.size * s}px ${STACK.mono}`;
    ctx.fillText(role.text, W / 2, (nameY + 40) * s);
    ctx.globalAlpha = 1;
    titlePill(ctx, state.title, W / 2, (nameY + 56) * s, s, state.format === "poster" ? 28 : 26);
  }

  applyGrain(ctx, W, H);
  drawFooterBand(ctx, W, H, s, state, (state.format === "poster" ? 84 : 78) * s);
}

/** Full illustrated Goa scene for any format. fancy = sunset variant. */
function renderScene(ctx: Ctx, state: PassState, s: number, fancy: boolean) {
  const styleKey = fancy ? "sunset" : "day";

  // team and pfp carry their art inside their own renderer; without the
  // generated background they simply come out in the print look
  if (state.format === "team") {
    renderTeam(ctx, state, s, getFrameBg("team", styleKey));
    return;
  }
  if (state.format === "pfp") {
    renderPfp(ctx, state, s, getFrameBg("pfp", styleKey));
    return;
  }

  const spec = FORMATS[state.format];
  const W = spec.width * s;
  const H = spec.height * s;
  const p = fancy ? SUNSET : DAY;

  // Preferred path: AI-illustrated background generated offline with Gemini.
  const bg = getFrameBg(state.format, styleKey);
  if (bg) {
    const cover = Math.max(W / bg.width, H / bg.height);
    const bw = bg.width * cover;
    const bh = bg.height * cover;
    ctx.drawImage(bg, (W - bw) / 2, (H - bh) / 2, bw, bh);
    // wordmark on a sticker plate so it reads on any art
    wordmarkSticker(ctx, 150 * s, 96 * s, s);
    sceneOverlays(ctx, state, s, p, true);
    return;
  }
  const horizon = H * (state.format === "poster" ? 0.4 : 0.44);
  const sandTop = H * (state.format === "poster" ? 0.62 : 0.66);

  // sky
  const sky = ctx.createLinearGradient(0, 0, 0, horizon);
  sky.addColorStop(0, p.sky[0]);
  sky.addColorStop(1, p.sky[1]);
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, horizon);

  // sun
  if (fancy) {
    const sunX = W * 0.68;
    const glow = ctx.createRadialGradient(sunX, horizon, 10 * s, sunX, horizon, 260 * s);
    glow.addColorStop(0, "rgba(255,211,122,0.9)");
    glow.addColorStop(1, "rgba(255,211,122,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, W, horizon);
    ctx.fillStyle = "#FFD37A";
    ctx.beginPath();
    ctx.arc(sunX, horizon - 8 * s, 110 * s, Math.PI, 0);
    ctx.fill();
    drawBirds(
      ctx,
      [
        [W * 0.24, horizon * 0.42],
        [W * 0.32, horizon * 0.34],
        [W * 0.42, horizon * 0.46],
      ],
      "#2E1A2E",
      s,
    );
  } else {
    drawSun(ctx, W * 0.82, horizon * 0.32, 62 * s, s);
  }
  drawCloud(ctx, W * 0.14, horizon * 0.3, 1.1, fancy ? "#FFC9A0" : "#FFFEF8", fancy ? 0.75 : 0.9, s);
  drawCloud(ctx, W * 0.58, horizon * 0.18, 0.8, fancy ? "#FFB3C2" : "#FFFEF8", fancy ? 0.6 : 0.75, s);

  // sea
  const sea = ctx.createLinearGradient(0, horizon, 0, sandTop);
  sea.addColorStop(0, p.sea[0]);
  sea.addColorStop(1, p.sea[1]);
  ctx.fillStyle = sea;
  ctx.fillRect(0, horizon, W, sandTop - horizon);
  if (fancy) {
    // sun glitter path
    ctx.save();
    ctx.fillStyle = "#FFD37A";
    ctx.globalAlpha = 0.75;
    let gw = 90 * s;
    for (let gy = horizon + 16 * s; gy < sandTop - 10 * s; gy += 22 * s) {
      ctx.fillRect(W * 0.68 - gw / 2, gy, gw, 5 * s);
      gw *= 1.18;
    }
    ctx.restore();
  }
  drawWaves(ctx, W * 0.06, horizon + 26 * s, W * 0.3, 2, s, p.wave, 0.5);
  drawWaves(ctx, W * 0.6, sandTop - 60 * s, W * 0.34, 2, s, p.wave, 0.4);
  drawBoat(ctx, W * (fancy ? 0.2 : 0.78), horizon + 52 * s, 0.95, s, fancy ? "#092E1E" : "#FFFEF8", 0.85);

  // sand
  ctx.fillStyle = p.sand;
  ctx.beginPath();
  ctx.moveTo(0, sandTop + 14 * s);
  ctx.quadraticCurveTo(W * 0.3, sandTop - 16 * s, W * 0.62, sandTop + 6 * s);
  ctx.quadraticCurveTo(W * 0.85, sandTop + 20 * s, W, sandTop - 4 * s);
  ctx.lineTo(W, H);
  ctx.lineTo(0, H);
  ctx.closePath();
  ctx.fill();

  // flora and props
  drawPalm(ctx, 74 * s, sandTop + 40 * s, H * 0.3, 0.5, p.palm, 1, s);
  drawPalm(ctx, W - 60 * s, sandTop + 26 * s, H * 0.24, -0.55, p.palm, 1, s);
  if (fancy) {
    drawUmbrella(ctx, W * 0.16, sandTop + 60 * s, 74 * s, s);
    drawBunting(ctx, 30 * s, 24 * s, W - 30 * s, 24 * s, 60 * s, s);
  } else {
    drawShell(ctx, W * 0.88, H * 0.79, 40 * s, s, BRAND.greenDeep, 0.55);
  }

  // compact wordmark in the sky
  drawWordmark(ctx, 190 * s, 40 * s, 64, s, fancy ? BRAND.cream : BRAND.greenDeep, BRAND.pink);

  sceneOverlays(ctx, state, s, p, false);
}

const RENDERERS: Record<FormatId, (ctx: Ctx, state: PassState, s: number) => void> = {
  card: renderCard,
  team: renderTeam,
  pfp: renderPfp,
  poster: renderPoster,
};

/** Render a pass at target width (export passes the spec width; preview passes less). */
export function renderPass(canvas: HTMLCanvasElement, state: PassState, targetWidth?: number): void {
  const spec = FORMATS[state.format];
  const w = targetWidth ?? spec.width;
  const s = w / spec.width;
  canvas.width = Math.round(spec.width * s);
  canvas.height = Math.round(spec.height * s);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.textBaseline = "alphabetic";
  if (state.styleId !== "print" && styleSupports(state.styleId, state.format)) {
    renderScene(ctx, state, s, state.styleId === "sunset");
  } else {
    RENDERERS[state.format](ctx, state, s);
  }
}

/** 1200x630 OG: the pass tilted on the press bed, headline ink to the left. */
export function renderOg(canvas: HTMLCanvasElement, passCanvas: HTMLCanvasElement): void {
  canvas.width = 1200;
  canvas.height = 630;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  ctx.fillStyle = BRAND.greenDeep;
  ctx.fillRect(0, 0, 1200, 630);
  ctx.fillStyle = BRAND.green;
  ctx.globalAlpha = 0.55;
  ctx.fillRect(0, 0, 1200, 630);
  ctx.globalAlpha = 1;

  // crop marks
  ctx.strokeStyle = BRAND.cream;
  ctx.globalAlpha = 0.7;
  ctx.lineWidth = 2;
  for (const [mx, my] of [[24, 24], [1176, 24], [24, 606], [1176, 606]] as const) {
    ctx.beginPath();
    ctx.moveTo(mx - 14, my);
    ctx.lineTo(mx + 14, my);
    ctx.moveTo(mx, my - 14);
    ctx.lineTo(mx, my + 14);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;

  // headline block, left
  ctx.textAlign = "left";
  ctx.fillStyle = BRAND.yellow;
  ctx.font = `600 108px ${STACK.display}`;
  ctx.fillText("FRAME", 70, 220);
  ctx.fillText("IN GOA", 70, 318);
  ctx.fillStyle = BRAND.cream;
  ctx.font = `500 25px ${STACK.mono}`;
  ctx.fillText("HACKER HOUSE GOA 2026", 72, 380);
  ctx.fillText("28-31 OCT · GOA, INDIA", 72, 416);
  ctx.fillStyle = BRAND.pink;
  ctx.font = `700 30px ${STACK.mono}`;
  ctx.fillText(EVENT.hashtag, 72, 478);
  ctx.fillStyle = BRAND.cream;
  ctx.globalAlpha = 0.75;
  ctx.font = `500 20px ${STACK.mono}`;
  ctx.fillText("get yours at the link", 72, 522);
  ctx.globalAlpha = 1;

  // the pass, tilted, right
  const scale = Math.min(560 / passCanvas.width, 560 / passCanvas.height);
  const w = passCanvas.width * scale;
  const h = passCanvas.height * scale;
  ctx.save();
  ctx.translate(870, 315);
  ctx.rotate(-0.05);
  ctx.shadowColor = "rgba(0,0,0,0.45)";
  ctx.shadowBlur = 44;
  ctx.shadowOffsetY = 14;
  ctx.drawImage(passCanvas, -w / 2, -h / 2, w, h);
  ctx.restore();

  applyGrain(ctx, 1200, 630);
}

/** Export helper with the old-device retry from the spec's memory policy. */
export async function exportPng(state: PassState): Promise<Blob> {
  const attempt = (width?: number) =>
    new Promise<Blob>((resolve, reject) => {
      try {
        const canvas = document.createElement("canvas");
        renderPass(canvas, state, width);
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("toBlob null"))), "image/png");
      } catch (e) {
        reject(e);
      }
    });
  try {
    return await attempt();
  } catch {
    return await attempt(1080);
  }
}
