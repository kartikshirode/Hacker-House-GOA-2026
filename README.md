# Hacker House Goa 2026

All my task code for HH Goa 2026. Each shortlisting task gets its own folder, and right now there's one.

## Task 1: Frame in Goa

The brief: a web tool where you upload a photo and get back a branded HH Goa graphic in seconds, ready to download and share on X with #FrameInGoa. The actual PDF sits in `Task 1/` next to the selection criteria doc.

My submission is `Task 1/frame-in-goa`, a Next.js 16 app that renders 4 pass formats from one shared canvas renderer: a builder ID card, a team frame for 1 to 3 people, a circular PFP frame and a poster with a QR code pointing back at the app. Photos stay in your browser unless you create a share link. It converts HEIC properly, auto-crops around your face with MediaPipe, and every pass gets a seat number.

Live: https://frame-in-goa-ruby.vercel.app

The app folder has its own README with the full breakdown of how it works.

## What's in here

```
Task 1/
  frame-in-goa/       the app (Next.js 16, TypeScript, Tailwind v4, Canvas 2D)
  docs/superpowers/   the design spec written before any code
  *.pdf               the task brief and selection criteria
  *.png               Gemini-generated source art for the frame backgrounds
```

## Run it

```
cd "Task 1/frame-in-goa"
npm install
npm run dev
```

The app comes up on localhost:3000. `npx vitest run` runs the unit tests in `tests/`.

Two optional env vars: share links need a Vercel Blob store (`BLOB_READ_WRITE_TOKEN`), and the seat counter uses Upstash Redis (`UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`). Without Redis the seats fall back to a stable hash, nothing breaks.
