// Canvas never repaints when a late font lands, so every export awaits this.
// FontFace constructor route: @font-face alone never loads a font no DOM node uses.

let loading: Promise<void> | null = null;

export function loadBrandFonts(): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    const faces = [
      new FontFace("Imbue", "url(/fonts/imbue-latin.woff2)", { weight: "100 900" }),
      new FontFace("Victor Mono", "url(/fonts/victor-mono-latin.woff2)", { weight: "100 700" }),
      new FontFace("Noto Sans Devanagari", "url(/fonts/noto-devanagari.woff2)", { weight: "700" }),
    ];
    const load = Promise.all(
      faces.map((f) => f.load().then((loaded) => document.fonts.add(loaded))),
    );
    // A missing font beats a hung export: 3 s, then system fallbacks draw.
    await Promise.race([load, new Promise((r) => setTimeout(r, 3000))]);
  })();
  return loading;
}
