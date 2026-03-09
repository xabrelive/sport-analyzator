import type { Metadata } from "next";
import { Outfit, DM_Sans } from "next/font/google";
import { AuthProvider } from "@/contexts/AuthContext";
import "./globals.css";

const outfit = Outfit({
  subsets: ["latin", "latin-ext"],
  variable: "--font-display",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin", "latin-ext"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PingWin — спортивная аналитика",
  description:
    "PingWin (pingwin.pro): аналитика спортивных событий — лайв, линия, статистика по игрокам. Только данные. Регистрация по почте или Telegram.",
  metadataBase: new URL("https://pingwin.pro"),
  openGraph: {
    title: "PingWin — спортивная аналитика",
    description: "Аналитика спортивных событий. Только данные. Регистрация по почте или Telegram.",
    url: "https://pingwin.pro",
  },
  icons: {
    icon: "/pingwin-logo.png",
    apple: "/pingwin-logo.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${outfit.variable} ${dmSans.variable}`}>
      <body className="antialiased font-sans bg-[var(--bg)] text-slate-100 min-h-screen">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
