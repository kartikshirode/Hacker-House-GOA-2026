import type { Metadata } from "next";
import "./globals.css";
import { siteOrigin } from "@/lib/site";
import { EVENT } from "@/lib/brand";

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin()),
  title: `Frame in Goa · ${EVENT.name} Pass Generator`,
  description: `Upload a photo, get your ${EVENT.name} builder pass or team frame, and post it with ${EVENT.hashtag}. No login, photos stay on your device.`,
  openGraph: {
    title: `Frame in Goa · ${EVENT.name}`,
    description: `Generate your builder pass for ${EVENT.name}. ${EVENT.hashtag}`,
    type: "website",
    images: [{ url: "/og-home.png", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    title: `Frame in Goa · ${EVENT.name}`,
    description: `Generate your builder pass for ${EVENT.name}. ${EVENT.hashtag}`,
    images: ["/og-home.png"],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
