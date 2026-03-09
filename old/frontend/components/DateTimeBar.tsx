"use client";

import { useEffect, useState } from "react";
import { fetchServerTime } from "@/lib/api";

function formatDataTime(iso: string, tzLabel: string): string {
  try {
    const d = new Date(iso);
    return `${d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })} ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })} ${tzLabel}`;
  } catch {
    return "-";
  }
}

function formatUserTime(): string {
  const d = new Date();
  return `${d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" })} ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

const PLACEHOLDER = "-";

export function DateTimeBar() {
  const [dataTime, setDataTime] = useState<string>(PLACEHOLDER);
  const [userTime, setUserTime] = useState<string>(PLACEHOLDER);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    let cancelled = false;
    setUserTime(formatUserTime());
    fetchServerTime()
      .then((r) => {
        if (!cancelled) setDataTime(formatDataTime(r.iso, r.timezone));
      })
      .catch(() => {});
    const interval = setInterval(() => {
      if (!cancelled) setUserTime(formatUserTime());
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [mounted]);

  useEffect(() => {
    if (!mounted) return;
    const t = setInterval(() => {
      fetchServerTime()
        .then((r) => setDataTime(formatDataTime(r.iso, r.timezone)))
        .catch(() => {});
    }, 60_000);
    return () => clearInterval(t);
  }, [mounted]);

  return (
    <div className="border-b border-slate-800/60 bg-slate-900/80">
      <div className="max-w-6xl mx-auto px-4 py-1.5 flex flex-wrap items-center justify-center gap-6 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="text-slate-500">Данные:</span>
          <span className="font-mono text-slate-300 tabular-nums">{dataTime}</span>
        </span>
        <span className="text-slate-600">|</span>
        <span className="flex items-center gap-1.5">
          <span className="text-slate-500">У вас:</span>
          <span className="font-mono text-slate-300 tabular-nums">{userTime}</span>
        </span>
      </div>
    </div>
  );
}
