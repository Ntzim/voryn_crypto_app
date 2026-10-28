import type { Metadata, Viewport } from "next";
import { Inter, Sora } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const sora = Sora({ variable: "--font-sora", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "Voryn — Intelligence Behind Every Trade", template: "%s · Voryn" },
  description:
    "Plataforma de inteligência para investimentos em criptomoedas: carteira, mercado e análise baseada em dados.",
  applicationName: "Voryn",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#080F14",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`dark ${inter.variable} ${sora.variable} h-full`}>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
