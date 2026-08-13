import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { blobBase, siteOrigin } from "@/lib/site";
import { buildCaption, buildIntentUrl } from "@/lib/caption";
import { EVENT } from "@/lib/brand";

const PASS_ID = /^[A-Za-z0-9_-]{21}$/;

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ n?: string; t?: string; s?: string }>;
}

function clean(v: string | undefined, max: number): string {
  return (v ?? "").slice(0, max).trim();
}

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { id } = await params;
  const q = await searchParams;
  if (!PASS_ID.test(id)) return {};
  const base = blobBase();
  const name = clean(q.n, 28) || "A builder";
  const title = `${name}'s pass to ${EVENT.name}`;
  const description = `Boarding for ${EVENT.name}, 28-31 Oct. Generate yours and post it with ${EVENT.hashtag}.`;
  const ogImage = base ? `${base}/og/${id}.png` : undefined;
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      ...(ogImage ? { images: [{ url: ogImage, width: 1200, height: 630 }] } : {}),
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      ...(ogImage ? { images: [ogImage] } : {}),
    },
  };
}

export default async function PassPage({ params, searchParams }: Props) {
  const { id } = await params;
  const q = await searchParams;
  if (!PASS_ID.test(id)) notFound();
  const base = blobBase();
  if (!base) notFound();

  const name = clean(q.n, 28);
  const builderTitle = clean(q.t, 40);
  const seat = /^\d{1,6}$/.test(q.s ?? "") ? Number(q.s) : null;
  const pageUrl = `${siteOrigin()}/pass/${id}`;
  const caption = buildCaption(seat, pageUrl);

  return (
    <main className="min-h-screen bg-[var(--hh-green)] text-[var(--hh-cream)] flex flex-col items-center px-4 py-10 gap-8">
      <h1 className="font-display text-4xl sm:text-5xl text-[var(--hh-yellow)] text-center">
        {name ? `${name}'s pass` : "A builder's pass"}
      </h1>
      {builderTitle ? (
        <p className="font-mono text-sm tracking-widest uppercase text-[var(--hh-pink)]">{builderTitle}</p>
      ) : null}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${base}/passes/${id}.png`}
        alt={`${name || "A builder"}'s ${EVENT.name} pass`}
        className="w-full max-w-xl rounded-xl shadow-2xl"
      />
      <div className="flex flex-col sm:flex-row gap-3 items-center">
        <a
          href={buildIntentUrl(caption)}
          target="_blank"
          rel="noopener noreferrer"
          className="bg-[var(--hh-yellow)] text-[var(--hh-ink)] font-mono font-bold px-6 py-3 rounded-full"
        >
          Post it on X
        </a>
        <Link
          href="/"
          className="border border-[var(--hh-cream)] font-mono px-6 py-3 rounded-full"
        >
          Get your own pass
        </Link>
      </div>
      <p className="font-mono text-xs opacity-70">{EVENT.dates} · {EVENT.place} · {EVENT.tagline}</p>
    </main>
  );
}
