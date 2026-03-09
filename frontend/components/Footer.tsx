"use client";

import Link from "next/link";
import Image from "next/image";

const TG_CHANNEL = "https://t.me/PingwinBets";
const EMAIL = "info@pingwin.pro";

export function Footer() {
  return (
    <footer className="border-t border-slate-800/60 bg-slate-950/50">
      <div className="mx-auto max-w-6xl px-4 py-10">
        <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
          <div className="flex items-center gap-3">
            <Image
              src="/pingwin-logo.png"
              alt="PingWin"
              width={40}
              height={40}
              className="rounded-xl"
            />
            <span className="font-display text-lg font-semibold text-white">
              PingWin
            </span>
          </div>
          <nav className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <Link
              href="/about"
              className="text-slate-400 transition hover:text-cyan-400"
            >
              О проекте
            </Link>
            <Link
              href="/advantages"
              className="text-slate-400 transition hover:text-cyan-400"
            >
              Преимущества
            </Link>
            <Link
              href="/privacy"
              className="text-slate-400 transition hover:text-cyan-400"
            >
              Политика конфиденциальности
            </Link>
            <Link
              href="/terms"
              className="text-slate-400 transition hover:text-cyan-400"
            >
              Правила использования
            </Link>
          </nav>
          <div className="flex flex-col gap-2 text-sm">
            <span className="text-slate-500">Связь:</span>
            <a
              href={TG_CHANNEL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-cyan-400 transition hover:text-cyan-300"
            >
              @PingwinBets
            </a>
            <a
              href={`mailto:${EMAIL}`}
              className="text-cyan-400 transition hover:text-cyan-300"
            >
              {EMAIL}
            </a>
          </div>
        </div>
        <p className="mt-8 text-center text-xs text-slate-500">
          pingwin.pro — только аналитика. Решения и риски — на вашей стороне.
        </p>
      </div>
    </footer>
  );
}
