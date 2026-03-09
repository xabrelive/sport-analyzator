"use client";

import Link from "next/link";
import type { Match } from "@/lib/api";
import { formatSetScoresTT, setsTotal, formatHoursUntil } from "@/lib/format";

/**
 * Карточка матча в формате настольного тенниса:
 * Строка 1: Лига (например Setka Cup. Токио)
 * Строка 2: Игрок1 — Игрок2 (7-11 8-11 12-10 4-2*)
 * Строка 3: Счёт по сетам 1:2 и аналитика
 */
export function LandingMatchRow({
  match,
  isLive,
  blurValues = true,
}: {
  match: Match;
  isLive: boolean;
  blurValues?: boolean;
}) {
  const home = match?.home_player?.name ?? "?";
  const away = match?.away_player?.name ?? "?";
  const league = match?.league?.name ?? "–";
  const isOngoing = isLive && match?.status !== "finished";
  const setScoresStr = formatSetScoresTT(match?.scores, isOngoing);
  const setsWon = match?.scores?.length ? setsTotal(match) : "-";

  const Value = ({ children }: { children: React.ReactNode }) =>
    blurValues ? (
      <span className="inline-block min-w-[1.5rem] text-transparent select-none blur-sm bg-white/20 rounded" aria-hidden>
        {children}
      </span>
    ) : (
      <span>{children}</span>
    );

  return (
    <div className="group rounded-xl border border-slate-700/60 bg-slate-800/40 p-3.5 transition-all duration-300 hover:border-teal-500/40 hover:bg-slate-800/70 hover:shadow-lg hover:shadow-teal-500/5 hover:-translate-y-0.5 min-w-0">
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider truncate" title={league}>
          {league}
        </span>
        {isLive ? (
          match?.status === "finished" ? (
            <span className="shrink-0 inline-flex items-center rounded-full bg-slate-600 px-2 py-0.5 text-xs font-medium text-slate-200">
              Завершён
            </span>
          ) : (
            <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-red-500/90 px-2 py-0.5 text-xs font-semibold text-white">
              <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse" />
              Live
            </span>
          )
        ) : (
          <span className="shrink-0 inline-flex items-center rounded-full border border-slate-600 bg-slate-700/80 px-2 py-0.5 text-xs font-medium text-slate-300">
            {formatHoursUntil(match?.start_time ?? new Date().toISOString())}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1 mb-2 min-w-0">
        <span className="font-semibold text-white" title={`${home} - ${away}`}>
          {home} — {away}
        </span>
        {(setScoresStr !== "-" || setsWon !== "-") && (
          <>
            <span className="text-[10px] text-slate-500 uppercase tracking-wider">По сетам: {setsWon}</span>
            <span className="font-mono text-sm text-teal-400 break-all">{setScoresStr}</span>
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-700/50">
        <span className="font-mono text-base font-bold text-teal-400 tabular-nums">{setsWon}</span>
        <div className="flex items-center gap-2 text-xs text-slate-400 flex-shrink-0">
          <span>1-й <Value>68%</Value></span>
          <span>2-й <Value>55%</Value></span>
          <span>Сет <Value>5.2</Value></span>
          {blurValues && (
            <Link href="/register" className="font-medium text-teal-400 hover:text-teal-300 transition-colors">
              Открыть →
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

export function LandingMatchTableHeader({ isLive }: { isLive: boolean }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      {isLive && (
        <span className="flex h-2 w-2 rounded-full bg-red-500 animate-pulse" aria-hidden />
      )}
      <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        {isLive ? "Счёт по сетам · идёт матч" : "Предстоящие матчи"}
      </span>
    </div>
  );
}
