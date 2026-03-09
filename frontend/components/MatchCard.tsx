"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Match, OddsSnapshot } from "@/lib/api";
import { formatStartTime, formatHoursUntil, setsTotal, formatSetScoresTT } from "@/lib/format";

/** Рынок «победитель матча»: winner/win или 92_1 (BetsAPI). */
const WINNER_MARKETS = ["winner", "win", "92_1"];

function getWinnerOdds(odds: OddsSnapshot[] | undefined): { home: string; away: string } {
  if (!odds?.length) return { home: "–", away: "–" };
  const winner = odds.filter((o) => WINNER_MARKETS.includes(o.market));
  const home = winner.find((o) => o.selection === "home" || o.selection === "1" || o.selection?.toLowerCase().includes("home"));
  const away = winner.find((o) => o.selection === "away" || o.selection === "2" || o.selection?.toLowerCase().includes("away"));
  return {
    home: home ? String(Number(home.odds).toFixed(2)) : "–",
    away: away ? String(Number(away.odds).toFixed(2)) : "–",
  };
}

interface MatchCardProps {
  match: Match;
  showOdds?: boolean;
  showResult?: boolean;
  compact?: boolean;
  /** Показать «через N ч M мин» до начала (для линии) */
  showStartsIn?: boolean;
  /** Показать строку аналитики с размытыми значениями (для гостей) */
  showAnalyticsBlur?: boolean;
}

export function MatchCard({ match, showOdds, showResult, compact, showStartsIn, showAnalyticsBlur }: MatchCardProps) {
  const router = useRouter();
  const homeName = match.home_player?.name ?? "?";
  const awayName = match.away_player?.name ?? "?";
  const leagueName = match.league?.name ?? "–";
  const isLive = match.status === "live";
  const isFinished = match.status === "finished";
  const isCancelled = match.status === "cancelled";
  const { home: oddsHome, away: oddsAway } = getWinnerOdds(match.odds_snapshots);

  const homePlayerHref = match.home_player?.id ? `/player/${match.home_player.id}` : null;
  const awayPlayerHref = match.away_player?.id ? `/player/${match.away_player.id}` : null;

  const handlePlayerClick = (e: React.MouseEvent, href: string | null) => {
    if (!href) return;
    e.preventDefault();
    e.stopPropagation();
    router.push(href);
  };

  return (
    <Link
      href={`/match/${match.id}`}
      prefetch={false}
      className={`block rounded-xl border border-slate-700 bg-slate-800/60 hover:border-teal-500/30 hover:bg-slate-800 transition-all ${compact ? "p-2.5" : "p-4"}`}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs text-slate-500 truncate">{leagueName}</span>
        {isLive && (
          <span className="shrink-0 flex items-center gap-1 text-xs font-medium text-red-400">
            <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
            Live
          </span>
        )}
        {isCancelled && (
          <span className="shrink-0 text-xs font-medium text-amber-400/90">Отменён</span>
        )}
        {!isLive && !isFinished && !isCancelled && (
          <span className="text-xs text-zinc-500">
            {showStartsIn ? formatHoursUntil(match.start_time) : formatStartTime(match.start_time)}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-white">
            {homePlayerHref ? (
              <span
                role="link"
                tabIndex={0}
                className="hover:text-teal-400 hover:underline cursor-pointer"
                onClick={(e) => handlePlayerClick(e, homePlayerHref)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    e.stopPropagation();
                    router.push(homePlayerHref);
                  }
                }}
              >
                {homeName}
              </span>
            ) : (
              <span>{homeName}</span>
            )}
          </div>
          <div className="font-medium text-white">
            {awayPlayerHref ? (
              <span
                role="link"
                tabIndex={0}
                className="hover:text-teal-400 hover:underline cursor-pointer"
                onClick={(e) => handlePlayerClick(e, awayPlayerHref)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    e.stopPropagation();
                    router.push(awayPlayerHref);
                  }
                }}
              >
                {awayName}
              </span>
            ) : (
              <span>{awayName}</span>
            )}
          </div>
        </div>
        <div className="shrink-0 flex flex-col items-end gap-0.5">
          {isCancelled ? (
            <span className="text-amber-400/90 font-medium text-sm">Отменён</span>
          ) : isLive || isFinished ? (
            <>
              {match.scores?.length ? (
                <>
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-0.5">По сетам</span>
                  <span className="font-mono font-bold text-teal-400">{setsTotal(match)}</span>
                  <span className="text-xs text-zinc-500 font-mono">{formatSetScoresTT(match.scores, isLive)}</span>
                </>
              ) : match.result?.final_score ? (
                <span className="font-mono font-bold text-teal-400">{match.result.final_score}</span>
              ) : (
                <span className="font-mono text-slate-500">–</span>
              )}
            </>
          ) : showOdds ? (
            <div className="flex gap-2 font-mono text-sm">
              <span className="text-teal-400">{oddsHome}</span>
              <span className="text-slate-500">-</span>
              <span className="text-teal-400">{oddsAway}</span>
            </div>
          ) : null}
          {showResult && (match.result ? (
            <span className="text-xs text-slate-400">
              {match.result.winner_name ?? match.result.final_score}
            </span>
          ) : isCancelled ? (
            <span className="text-xs text-amber-400/90">Отменён</span>
          ) : null)}
        </div>
      </div>
      {showAnalyticsBlur && (
        <div className="mt-2 pt-2 border-t border-slate-700/50 flex items-center gap-3 text-xs text-slate-400">
          <span>1-й сет <span className="text-transparent select-none blur-sm bg-white/20 rounded">68%</span></span>
          <span>2-й сет <span className="text-transparent select-none blur-sm bg-white/20 rounded">55%</span></span>
          <span>Сетов <span className="text-transparent select-none blur-sm bg-white/20 rounded">5.2</span></span>
        </div>
      )}
    </Link>
  );
}
