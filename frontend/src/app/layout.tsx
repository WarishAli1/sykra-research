import type { Metadata } from "next";
import "./globals.css";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
export const metadata: Metadata = {
  title: {
    default: "Sykra Research — Go from question to cited answer",
    template: "%s | Sykra Research",
  },
  description:
    "Ask across your papers and the open literature. Every answer arrives cited, sourced, and ready to export.",
  keywords: ["AI research assistant", "literature review", "paper search", "citation assistant"],
  openGraph: {
    title: "Sykra Research — Go from question to cited answer",
    description:
      "Research faster with answers grounded in real papers and ready to export.",
    type: "website",
    siteName: "Sykra Research",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-paper text-ink">{children}</body>
    </html>
  );
}
