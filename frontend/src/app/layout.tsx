import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jbmono" });

export const metadata: Metadata = {
  title: "Infrastructure as Prompt",
  description: "Security-first AWS architecture from plain-English requirements, with verifiable evidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <TopBar />
        {children}
      </body>
    </html>
  );
}
