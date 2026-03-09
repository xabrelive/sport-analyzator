"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Match, OddsSnapshot } from "@/lib/api";
import { formatHoursUntil, formatDateTimeWithYear } from "@/lib/format";

/** Рынок «победитель матча»: winner/win (общие), 92_1 (BetsAPI НТ), 1_1 (v4 prematch / футбол). */
const WINNER_MARKETS = ["winner", "win", "92_1", "1_1"];

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

export interface LineMatchRowProps {
  match: Match;
  /** Текст прогноза по матчу (из сигнала или расчёта); null = мало данных */
  recommendation?: string | null;
  showAnalyticsBlur?: boolean;
}

/** Форматирует сигнал в короткий прогноз для линии. */
export function formatSignalRecommendation(marketType: string, selection: string): string {
  const m = marketType.toLowerCase();
  const s = (selection || "").toLowerCase();
  if (m === "winner" || m === "win" || m === "92_1") {
    if (s === "home" || s === "1") return "П1 победа";
    if (s === "away" || s === "2") return "П2 победа";
  }
  if (m === "set_winner") {
    if (s === "set_1_home") return "1-й сет выиграет П1";
    if (s === "set_1_away") return "1-й сет выиграет П2";
    if (s === "set_2_home") return "2-й сет выиграет П1";
    if (s === "set_2_away") return "2-й сет выиграет П2";
    if (s.startsWith("set_1")) return s.includes("home") ? "1-й сет выиграет П1" : "1-й сет выиграет П2";
    if (s.startsWith("set_2")) return s.includes("home") ? "2-й сет выиграет П1" : "2-й сет выиграет П2";
  }
  if (m === "total" || m === "92_3") {
    if (s.startsWith("over")) return `ТБ ${s.replace("over", "").replace("_", "").trim() || ""}`.trim();
    if (s.startsWith("under")) return `ТМ ${s.replace("under", "").replace("_", "").trim() || ""}`.trim();
  }
  if (m === "handicap" || m === "92_2") {
    if (s.includes("home") || s.includes("1")) return "П1 по форе";
    if (s.includes("away") || s.includes("2")) return "П2 по форе";
  }
  return `${marketType}: ${selection}`;
}

const NO_DATA_LABEL = "Мало данных для расчёта — смотрите аналитику матча";

export function LineMatchRow({ match, recommendation, showAnalyticsBlur }: LineMatchRowProps) {
  const router = useRouter();
  const homeName = match.home_player?.name ?? "?";
  const awayName = match.away_player?.name ?? "?";
  const { home: oddsHome, away: oddsAway, impliedHome, impliedAway } = getWinnerOdds(match.odds_snapshots);
  const homeHref = match.home_player?.id ? `/player/${match.home_player.id}` : null;
  const awayHref = match.away_player?.id ? `/player/${match.away_player.id}` : null;

  const handlePlayerClick = (e: React.MouseEvent, href: string | null) => {
    if (!href) return;
    e.preventDefault();
    e.stopPropagation();
    router.push(href);
  };

  const impliedStr =
    impliedHome != null && impliedAway != null
      ? `${impliedHome.toFixed(0)}% / ${impliedAway.toFixed(0)}%`
      : "—";

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
      <td className="py-2.5 pr-3 text-slate-400 text-sm whitespace-nowrap">
        {formatHoursUntil(match.start_time)}
      </td>
      <td className="py-2.5 pr-3 text-slate-400 text-xs whitespace-nowrap">
        {formatDateTimeWithYear(match.start_time)}
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
        <span className="font-mono text-sm text-teal-400 tabular-nums">{oddsHome}</span>
      </td>
      <td className="py-2.5 px-1 text-center text-slate-500 text-xs font-medium">—</td>
      <td className="py-2.5 pl-2 pr-3 text-left">
        <span className="font-mono text-sm text-teal-400 tabular-nums">{oddsAway}</span>
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
          <Link href={`/match/${match.id}`} prefetch={false} onClick={(e) => e.stopPropagation()} className="text-teal-400 hover:text-teal-300 text-xs">
            <span className="text-transparent select-none blur-sm bg-white/20 rounded">Подробнее</span>
          </Link>
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className="text-slate-300 text-xs block">
              {recommendation ?? NO_DATA_LABEL}
            </span>
            <Link
              href={`/match/${match.id}`}
              prefetch={false}
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
