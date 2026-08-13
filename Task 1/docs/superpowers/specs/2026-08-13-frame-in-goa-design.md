# Frame in Goa: HH Goa 2026 Pass Generator, Design Spec

Date: 13 Aug 2026. Deadline for the live link and X post: 11:59 pm tonight.

## What this is

The shortlisting task for Hacker House Goa 2026. A web tool where someone uploads a photo and gets back a branded HH Goa graphic in seconds, ready to download and share on X with #FrameInGoa. No login, no signup gate, works in one pass on a phone.

Hard rules from the updated task PDF (the Google Drive copy, stricter than the first one):

- The submission X post must contain #FrameInGoa or it gets flagged invalid.
- One submission per team.
- Must handle JPG, PNG and HEIC uploads.
- If sharing goes through a link, the link preview has to show the actual generated graphic, not a default thumbnail.
- Submit the live link at https://forms.gle/jM5hTaGvsrfEfixPA plus the X post.
- The official site adds one the PDF doesn't have: "Use that same generator to bring your teammates into one combined frame." So a team frame is core scope, not an extra. Teams are 1 to 3 people per the selection framework.

## Why this design wins

I audited 9 live competitor submissions. Two systemic failures showed up: 6 of 8 live sites have broken or missing og:image (one points at localhost:3000, one at an SSO-blocked Vercel preview), and 7 of 9 claim HEIC support while only 2 actually convert it. Nobody has face-aware cropping, gyroscope tilt, a story format or a seat counter. Table stakes are both formats, client-side canvas, builder titles with reroll, pan and zoom, and an X intent share. So the wedge is simple: be the one where every stated requirement actually works, then stack the viral-ticket tricks (personal share pages, seat numbers, tilt, holo) that the Vercel and Supabase ticket generators proved out.

## Brand tokens (pulled from hhgoa.com CSS, not guessed)

- Green #0B6839, yellow #FEE101, cream #FFFBE8, hot pink #FF0080, reds #BF000F and #E40014.
- Fonts: Imbue (display serif, the wordmark face) and Victor Mono (mono, labels). Self-hosted woff2 subsets, loaded through the FontFace constructor and awaited before any canvas text draw.
- Motifs: HACKER HOUSE wordmark with the pink Devanagari sticker (see asset note below), "Less Noise. More Signal", the 247 builders number, Goa dates 28-31 Oct 2026.

Asset note: the wordmark and sticker get rebuilt as SVG by hand to approximate the official look. Rendering Devanagari to canvas needs a Devanagari-capable font subset; if that turns messy under deadline, the sticker ships as a pre-rendered PNG at 2x export size.

## Stack

Next.js App Router + TypeScript + Tailwind, deployed on Vercel. All image processing is client-side Canvas 2D. The only server pieces:

1. An upload-token route for Vercel Blob client uploads. The store gets created with access "public" (X's crawler fetches OG images anonymously, and Vercel locks a store's access mode at creation, so this cannot be an afterthought). The server knows the store's base URL through a BLOB_BASE_URL env var; /pass/[id] builds its image URLs as {base}/og/{id}.png and never accepts an image URL from query parameters, so nobody can point our share pages at arbitrary images.
2. A seat-counter route backed by Upstash Redis (Vercel Marketplace). Assignment is idempotent and atomic: one Lua script (EVAL) checks seat:{id}, increments the global counter only when the id is new, stores the mapping and returns the seat, all as a single Redis operation, so concurrent retries or double-taps can't race two commands apart. One pass id, one number, forever. If Redis isn't provisioned in time, seats fall back to a stable hash of the pass id, and nothing else breaks.
3. The share page /pass/[id], server-rendered so crawlers see the meta tags.

No database beyond Redis. No auth anywhere.

## Image pipeline

1. Input: file picker with accept="image/*,.heic,.heif". An earlier draft excluded HEIC from accept to lean on iOS auto-transcoding, but that blocks picking .heic files outright from the Files app on iOS and from Android and desktop pickers, and the transcode behavior is convention, not contract. The explicit image/heic MIME string stays out of the list (that exact string is what trips Safari 17's renamed-temp-file bug); image/* plus bare extensions covers everything without it.
2. HEIC detection by magic bytes (ftyp brand heic/heix/hevc/mif1/msf1), never by file.type. On a hit, dynamic-import heic-to (v1.5.x, current libheif) and convert to JPEG at quality 0.9. Since iOS will now hand over HEIC originals, this path is hot for iPhone users: the converter gets prefetched on idle after first paint so the wasm is warm before anyone picks a photo. Budget 1-3 s worst case on a mid-range phone, with a small progress state on the preview.
3. Decode via createImageBitmap. EXIF orientation is applied automatically by 2026 decode paths, so no rotation math.
4. Face-aware auto-crop: lazy-load @mediapipe/tasks-vision BlazeFace short range (model ~230 KB) after an image lands, runningMode IMAGE. Center the crop on the eye midpoint with roughly 2x face-height framing. Zero faces or a load failure means plain center crop. Manual pan plus pinch zoom (pointer events) always available on top.
5. Export: draw at full output resolution on the main thread, canvas.toBlob PNG. Never scale up a preview canvas. The DOM preview and the canvas export both read from one shared layout module (pure data: window positions, sizes, text boxes per format) so the download can't drift from what the preview showed.
6. Memory policy (phones are the audience, and a team frame can hold 3 photos at once):
   - Reject inputs over 25 MB with a friendly message before any decode.
   - Decode through createImageBitmap with resize options so the working image never exceeds 4096 px on its long edge; a 48MP photo becomes a 4096 px bitmap at decode time, not after.
   - Preview renders from a copy capped near 1600 px; face detection runs on a further-downscaled copy near 640 px.
   - Every replaced ImageBitmap gets .close() and every object URL gets revoked as soon as its consumer is done. Swapping a photo frees the old one immediately.
   - If the export canvas or its toBlob allocation fails (old devices), retry once at 1080 px wide, then tell the user plainly instead of hanging.

## Formats

One shared renderer module, four layouts:

- A, PFP frame, 1080x1080. Circular photo window, green ring, yellow Imbue arc text, pink गोवा sticker, dates.
- B, Builder ID card, 1080x1350 (4:5 reads best in the X timeline). Cream card on green, photo window, name in Imbue, stack/role in Victor Mono, generated builder title, seat number, MRZ-style strip carrying #FrameInGoa, the tagline, and a small barcode.
- T, Team frame, 1600x900. Required by the official site wording. 1 to 3 photo slots on one shared card (rounded windows, names under each, one team name field), same brand system as B. Slot count adapts to how many photos get added; each slot reuses the same pan/zoom and face-crop machinery as the solo formats.
- C, Story, 1080x1920. Vertical variant of B for Instagram stories. Optional, ships only after everything above works in production.

Seat numbers render as "#NNN / 247" while the counter sits at or below 247, then just "#NNN" beyond it. 247 is the residency motif (the studio literally runs on it), but the site also says 500 elite builders in one place, so the card treats the number as flavor, never as a live capacity claim.

Builder titles: two word pools (Goa flavor x builder flavor), examples "Deploy Captain", "Kokum Compiler", "Palm Tree Debugger". Reroll button, seeded so a reroll never repeats the last title. Pools live in one TypeScript file.

## Share flow

The task lives or dies on the X post carrying #FrameInGoa, so the path that guarantees the caption is primary everywhere:

1. Primary, the "Share to X" button on every platform: upload the rendered pass PNG and its 1200x630 OG crop to Vercel Blob, await BOTH uploads, then open x.com/intent/tweet pre-filled with the caption, #FrameInGoa and the URL of /pass/[id]. The intent deep-links into the X app on phones and the link preview shows the actual card, which is exactly the option the task text allows. A share sheet can't pre-select X or guarantee the caption survives, so it doesn't get the top spot.
2. Enhancement, a "Share image via..." button where navigator.canShare passes on the exact payload we'd send ({files: [file]}, single PNG File): calls navigator.share immediately in the tap handler with a pre-made File, nothing awaited in between. No clipboard write rides on the same tap; clipboard and share can each demand the same transient activation, and burning it on the copy makes the share throw. The caption sits visible next to the button with its own "Copy caption" control instead.
3. Floor: plain download button plus the same copy-caption button. Always visible regardless of the above.

One seat formatter is shared by the card renderer and the caption builder: "#NNN / 247" at or below 247, "#NNN" beyond, so the card and the tweet can never disagree.

Blob objects are immutable: every finalized graphic gets a fresh crypto-random id (nanoid, 21 chars), nothing is ever overwritten (allowOverwrite off), and a re-render after edits means a new id, so neither the Vercel CDN nor X's card cache can ever serve a stale card. The upload-token route only issues tokens for pathnames matching passes/{id}.png or og/{id}.png, content type image/png, and a 10 MB cap.

/pass/[id] is the personal page: title "{Name}'s pass to Hacker House Goa 2026", og:image and twitter:image point at {BLOB_BASE_URL}/og/{id}.png (the 1200x630 crop uploaded alongside the pass, so the preview never gets awkwardly cropped), twitter:card summary_large_image, and a "Get your own pass" CTA linking home. The page body shows the full pass from {BLOB_BASE_URL}/passes/{id}.png. Display text (name, title, seat) rides in query params so the page needs no database read; image URLs never do.

Caption text: "Boarding for Hacker House Goa 2026. Seat {formattedSeat}. Get yours: {url} #FrameInGoa", where {formattedSeat} comes from the shared seat formatter. Exact copy can shift, the hashtag cannot.

Text fields: name capped at 28 characters, stack/role at 32, team name at 24, enforced by input maxlength and re-checked in the renderer. Overflow handling is shrink-to-fit down to a floor size, then ellipsis. The canvas font stack is "Imbue, serif" and "Victor Mono, monospace" so scripts Imbue doesn't cover (Devanagari names included) fall through to system glyphs instead of tofu boxes; the fixture set includes a Devanagari name to prove it.

## Feel

DOM preview (not canvas) during editing, so effects are cheap: perspective tilt following the cursor on desktop, deviceorientation tilt on phones (iOS needs the permission tap, requested on first touch of the card), and a holo-foil shimmer on the ID card built from stacked blend-mode layers driven by the same tilt input. Canvas only renders at export time. Small confetti burst on first successful generation, and that's the whole animation budget.

## Error handling

- Unsupported or corrupt file: friendly inline message, input stays live.
- HEIC conversion failure: that upload can't proceed, so the message says so plainly and asks for a JPG or a screenshot of the photo, input stays live for the retry.
- Face detection failure: silent center-crop fallback.
- Blob upload or Redis failure: share button degrades to download plus text-only intent, with a toast explaining the image should be attached manually.
- Fonts not loaded: export waits on document.fonts readiness for the two families, 3 s timeout, then draws anyway (system serif fallback beats a blank card).

The upload-to-download core path makes one optional network call (the seat number) and degrades to the client-side hash if it fails, so no backend piece can take the core flow down.

## Testing

- Vitest units: title generator (pool coverage, no immediate repeats), HEIC magic-byte sniffing, share capability ladder selection, seat formatting.
- A dev-only /fixtures page that renders every format against a fixed sample set: rotated JPEG, transparent PNG, a 12MP photo, HEIC, an off-center portrait, a landscape group shot, and a long name plus a long title. One glance catches renderer regressions. Full pixel-diff golden tests would be flaky across machines and aren't worth tonight's hours; the fixture page plus unit tests on the layout math is the honest version.
- Manual device matrix before submitting: iPhone Safari (HEIC pick from Photos AND from Files, share sheet, gyro permission), Android Chrome (stray HEIC file, share sheet), desktop Chrome and Firefox (drag-drop, intent flow).
- OG validation from production, not a browser: curl the /pass/[id] page with a Twitterbot user agent and check the raw meta tags (query-param metadata makes the route dynamic, so the crawler response is the only response that counts), then one real X post as the final proof. This is the exact check 6 of 8 competitors skipped, so it happens before the form gets filled, not after.

## Build order

1. Scaffold, brand tokens, fonts, static frame assets.
2. Pipeline: upload, HEIC branch, decode, pan/zoom state, memory policy.
3. Renderer: format B first (it carries the most brand), then the team frame (required by the official site; the PDF's own formats are pick-one, so B alone satisfies it).
4. Download + captions + X intent.
5. Blob share pages with OG meta.
6. First production deploy, then the Twitterbot OG check and a phone HEIC test against the live URL. Nothing counts as submittable until this passes.
7. Format A (PFP frame). Cheap once the renderer exists, but optional per the PDF, so it sits after the gate.
8. Face auto-crop (post-core on purpose: the MediaPipe web API is still marked preview and detection runs synchronously on the main thread, so it stays an enhancement with the center-crop fallback).
9. Tilt, holo, confetti.
10. Seat counter (Redis), webcam selfie.
11. Story format.
12. Final device matrix, fresh OG check, submit the form and the X post.

Steps 1-6 are the submittable core, and 6 is the gate: deploy and verification come before any visual extra, so if the evening goes sideways the thing that exists is a working, verified submission rather than a pretty local demo. Everything after 6 lands independently in descending value-per-hour.

## Out of scope

Login of any kind, LinkedIn/Instagram API posting (caption copy button covers them), animated exports, background removal, Apple Wallet passes, golden-pass share detection, public gallery. Some of these are listed as post-deadline ideas in the research notes, none block submission.

## Logistics

- This folder is not a git repo and stays that way unless Kartik says otherwise.
- Deploy target Vercel; needs the Vercel CLI (npm i -g vercel) and a login from Kartik, or a repo connect through the dashboard if he prefers.
- One submission per team, so nothing gets posted or submitted without an explicit go.
