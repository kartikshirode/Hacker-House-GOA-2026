// Vercel build step. index.html here is the single source of truth for the
// UI; this fills public/ from it and stamps the backend origin into
// config.js from the VAANI_API env var, so the same file serves both from
// the backend (same origin, empty API) and from Vercel (cross origin).
import { mkdirSync, copyFileSync, writeFileSync } from "node:fs";

mkdirSync("public", { recursive: true });
copyFileSync("index.html", "public/index.html");

const api = (process.env.VAANI_API || "").replace(/\/+$/, "");
writeFileSync("public/config.js", `window.VAANI_API = ${JSON.stringify(api)};\n`);
console.log(`public/config.js -> ${api || "(same origin)"}`);
