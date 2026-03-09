"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Match } from "@/lib/api";
import { setsTotal, formatSetScoresTT, formatTimeOnly } from "@/lib/format";

export interface ResultsMatchRowProps {
  match: Match;
}

export function ResultsMatchRow({ match }: ResultsMatchRowProps) {
  const router = useRouter();
  const homeName = match.home_player?.name ?? "?";
  const awayName = match.away_player?.name ?? "?";
  const homeHref = match.home_player?.id ? `/player/${match.home_player.id}` : null;
  const awayHref = match.away_player?.id ? `/player/${match.away_player.id}` : null;
  const scoreSets = setsTotal(match);
  const scoreDetail = match.status === "cancelled"
    ? "Отменён"
    : match.scores?.length
      ? formatSetScoresTT(match.scores, false)
      : match.result?.final_score ?? "–";
  const winnerName = match.status === "cancelled" ? null : (match.result?.winner_name ?? null);
  const leagueName = match.league?.name ?? "–";
  const timeStr = formatTimeOnly(match.started_at ?? match.start_time);

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
      <td className="py-2 pr-3 text-slate-400 text-sm whitespace-nowrap">
        {timeStr}
      </td>
      <td className="py-2 pr-3 min-w-0">
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
      <td className="py-2 px-2 text-center min-w-[90px]">
        <div className="flex flex-col items-center gap-0.5">
          <span className="font-mono font-bold text-teal-400 text-sm">{scoreSets}</span>
          <span className="text-[10px] text-slate-500 font-mono leading-tight">{scoreDetail}</span>
        </div>
      </td>
      <td className="py-2 pl-2 pr-3 min-w-0">
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
      <td className="py-2 pr-3 text-emerald-400/90 text-xs font-medium max-w-[120px] truncate" title={winnerName ?? undefined}>
        {winnerName ?? "–"}
      </td>
      <td className="py-2 pr-3 text-slate-500 text-xs max-w-[100px] truncate" title={leagueName}>
        {leagueName}
      </td>
      <td className="py-2 pl-2">
        <Link
          href={`/match/${match.id}`}
          prefetch={false}
          className="inline-flex items-center gap-1 text-xs font-medium text-teal-400 hover:text-teal-300 w-fit"
          onClick={(e) => e.stopPropagation()}
        >
          В матч
          <span className="opacity-70">→</span>
        </Link>
      </td>
    </tr>
  );
}
