import type { Metadata, Viewport } from "next";
import { Inter, Sora } from "next/font/google";

import { Providers } from "@/components/providers";
import { THEME_COLORS, THEME_SCRIPT } from "@/lib/theme-script";

import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const sora = Sora({ variable: "--font-sora", subsets: ["latin"], weight: ["400", "500", "600", "700"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "Voryn — Intelligence Behind Every Trade", template: "%s · Voryn" },
  description:
    "Plataforma de inteligência para investimentos em criptomoedas: carteira, mercado e análise baseada em dados.",
  applicationName: "Voryn",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  // Updated to the active theme by THEME_SCRIPT / lib/theme.ts.
  themeColor: THEME_COLORS.dark,
  colorScheme: "light dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The theme class and color-scheme are set by THEME_SCRIPT before React hydrates, so
    // they legitimately differ from the server HTML on this one element.
    <html lang="pt-BR" className={`${inter.variable} ${sora.variable} h-full`} suppressHydrationWarning>
      <head>
        {/* Blocking on purpose: applies the saved/system theme before first paint (no flash). */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
