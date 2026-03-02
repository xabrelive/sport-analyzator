"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Match, OddsSnapshot } from "@/lib/api";
import { setsTotal, formatSetScoresTT, formatTimeOnly } from "@/lib/format";

const WINNER_MARKETS = ["winner", "win", "92_1"];

function getWinnerOdds(odds: OddsSnapshot[] | undefined): { home: string; away: string; impliedHome: number | null; impliedAway: number | null } {
  if (!odds?.length) return { home: "–", away: "–", impliedHome: null, impliedAway: null };
  const winner = odds.filter((o) => WINNER_MARKETS.includes(o.market));
  const homeSnap = winner.find((o) => o.selection === "home" || o.selection === "1" || o.selection?.toLowerCase().includes("home"));
  const awaySnap = winner.find((o) => o.selection === "away" || o.selection === "2" || o.selection?.toLowerCase().includes("away"));
  const homeOdds = homeSnap ? Number(homeSnap.odds) : NaN;
  const awayOdds = awaySnap ? Number(awaySnap.odds) : NaN;
  let impliedHome: number | null = null;
  let impliedAway: number | null = null;
  if (homeSnap?.implied_probability != null && awaySnap?.implied_probability != null) {
    const h = parseFloat(String(homeSnap.implied_probability));
    const a = parseFloat(String(awaySnap.implied_probability));
    if (!Number.isNaN(h) && !Number.isNaN(a)) {
      const sum = h + a;
      if (sum > 0) {
        impliedHome = (h / sum) * 100;
        impliedAway = (a / sum) * 100;
      }
    }
  } else if (!Number.isNaN(homeOdds) && !Number.isNaN(awayOdds) && homeOdds > 0 && awayOdds > 0) {
    const invSum = 1 / homeOdds + 1 / awayOdds;
    if (invSum > 0) {
      impliedHome = (1 / homeOdds / invSum) * 100;
      impliedAway = (1 / awayOdds / invSum) * 100;
    }
  }
  return {
    home: homeSnap ? String(homeOdds.toFixed(2)) : "–",
    away: awaySnap ? String(awayOdds.toFixed(2)) : "–",
    impliedHome,
    impliedAway,
  };
}

export interface LiveMatchRowProps {
  match: Match;
  recommendation?: string | null;
  showAnalyticsBlur?: boolean;
}

const NO_DATA_LABEL = "Мало данных для расчёта — смотрите аналитику матча";

export function LiveMatchRow({ match, recommendation, showAnalyticsBlur }: LiveMatchRowProps) {
  const router = useRouter();
  const homeName = match.home_player?.name ?? "?";
  const awayName = match.away_player?.name ?? "?";
  const { home: oddsHome, away: oddsAway, impliedHome, impliedAway } = getWinnerOdds(match.odds_snapshots);
  const homeHref = match.home_player?.id ? `/player/${match.home_player.id}` : null;
  const awayHref = match.away_player?.id ? `/player/${match.away_player.id}` : null;
  const isLive = match.status === "live";
  const isFinished = match.status === "finished";
  const isCancelled = match.status === "cancelled";
  const scoreSets = setsTotal(match);
  const scoreDetail = isCancelled
    ? "Отменён"
    : match.scores?.length
      ? formatSetScoresTT(match.scores, isLive)
      : match.result?.final_score ?? "–";
  const winnerName = isCancelled ? null : (match.result?.winner_name ?? null);

  const startTimeStr = formatTimeOnly(match.started_at ?? match.start_time);

  const showOdds = !isFinished && !isCancelled;
  const oddsHomeDisplay = showOdds ? oddsHome : "–";
  const oddsAwayDisplay = showOdds ? oddsAway : "–";
  const impliedStr =
    showOdds && impliedHome != null && impliedAway != null
      ? `${impliedHome.toFixed(0)}% / ${impliedAway.toFixed(0)}%`
      : "—";

  const handlePlayerClick = (e: React.MouseEvent, href: string | null) => {
    if (!href) return;
    e.preventDefault();
    e.stopPropagation();
    router.push(href);
  };

  return (
    <tr
      role="button"
      tabIndex={0}
      className="group border-b border-slate-800/80 hover:bg-slate-800/50 transition-colors cursor-pointer"
      onClick={() => router.push(`/match/${match.id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(`/match/${match.id}`);
        }
      }}
    >
      <td className="py-2.5 pr-3 whitespace-nowrap">
        <div className="flex flex-col gap-0.5">
          {isLive ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-red-400">
              <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" aria-hidden />
              Live
            </span>
          ) : isFinished ? (
            <span className="text-slate-500 text-xs">Завершён</span>
          ) : isCancelled ? (
            <span className="text-amber-400/90 text-xs font-medium">Отменён</span>
          ) : (
            <span className="text-slate-500 text-xs">—</span>
          )}
          {startTimeStr !== "—" && (
            <span className="text-slate-500 text-[10px]" title="Время начала матча">
              Начало {startTimeStr}
            </span>
          )}
        </div>
      </td>
      <td className="py-2.5 pr-3 min-w-0">
        {homeHref ? (
          <span
            role="link"
            tabIndex={0}
            className="text-white font-medium block cursor-pointer hover:text-teal-400 hover:underline"
            onClick={(e) => handlePlayerClick(e, homeHref)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                router.push(homeHref);
              }
            }}
          >
            {homeName}
          </span>
        ) : (
          <span className="text-white font-medium block">{homeName}</span>
        )}
      </td>
      <td className="py-2.5 pr-2 text-right">
        <span className={`font-mono text-sm tabular-nums ${showOdds ? "text-teal-400" : "text-slate-500"}`}>{oddsHomeDisplay}</span>
      </td>
      <td className="py-2.5 px-2 text-center min-w-[100px]">
        <div className="flex flex-col items-center gap-0.5">
          <span className="font-mono font-bold text-teal-400 text-sm">{scoreSets}</span>
          <span className="text-[10px] text-slate-500 font-mono leading-tight">{scoreDetail}</span>
          {isFinished && winnerName && (
            <span className="text-[10px] text-emerald-400/90 font-medium mt-0.5">Победитель: {winnerName}</span>
          )}
        </div>
      </td>
      <td className="py-2.5 pl-2 pr-3 text-left">
        <span className={`font-mono text-sm tabular-nums ${showOdds ? "text-teal-400" : "text-slate-500"}`}>{oddsAwayDisplay}</span>
      </td>
      <td className="py-2.5 pr-3 min-w-0">
        {awayHref ? (
          <span
            role="link"
            tabIndex={0}
            className="text-white font-medium block cursor-pointer hover:text-teal-400 hover:underline text-right"
            onClick={(e) => handlePlayerClick(e, awayHref)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                router.push(awayHref);
              }
            }}
          >
            {awayName}
          </span>
        ) : (
          <span className="text-white font-medium block text-right">{awayName}</span>
        )}
      </td>
      <td className="py-2.5 pr-3 text-slate-400 text-xs font-mono whitespace-nowrap">
        {showAnalyticsBlur ? (
          <span className="text-transparent select-none blur-sm bg-white/20 rounded">42% / 58%</span>
        ) : (
          impliedStr
        )}
      </td>
      <td className="py-2.5 pl-2 max-w-[220px]">
        {showAnalyticsBlur ? (
          <Link href={`/match/${match.id}`} onClick={(e) => e.stopPropagation()} className="text-teal-400 hover:text-teal-300 text-xs">
            <span className="text-transparent select-none blur-sm bg-white/20 rounded">Подробнее</span>
          </Link>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className="text-slate-300 text-xs block">
              {recommendation ?? NO_DATA_LABEL}
            </span>
            <Link
              href={`/match/${match.id}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-teal-400 hover:text-teal-300 w-fit"
              onClick={(e) => e.stopPropagation()}
            >
              В матч
              <span className="opacity-70">→</span>
            </Link>
          </div>
        )}
      </td>
    </tr>
  );
}
