import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { AuthProvider } from "@/contexts/AuthContext";
import { SubscriptionProvider } from "@/contexts/SubscriptionContext";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "PingWin - AI-аналитика спорта",
  description: "AI-аналитика спортивных событий: лайв, линия, статистика по игрокам и матчам. Регистрация для доступа.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" className={inter.variable}>
      <body className="antialiased font-sans bg-slate-950 text-slate-100 min-h-screen">
        <AuthProvider>
          <SubscriptionProvider>
            <AppShell>{children}</AppShell>
          </SubscriptionProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
