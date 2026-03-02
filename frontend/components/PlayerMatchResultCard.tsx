"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Match } from "@/lib/api";
import { getPlayerMatchOutcome, formatStartTime } from "@/lib/format";

interface PlayerMatchResultCardProps {
  match: Match;
  playerId: string;
}

export function PlayerMatchResultCard({ match, playerId }: PlayerMatchResultCardProps) {
  const router = useRouter();
  const outcome = getPlayerMatchOutcome(match, playerId);
  if (!outcome) return null;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => router.push(`/match/${match.id}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(`/match/${match.id}`);
        }
      }}
      className="block rounded-xl border border-slate-700/80 bg-slate-900/60 hover:border-slate-600 hover:bg-slate-800/60 transition-colors p-4 cursor-pointer"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <span className="text-xs text-slate-500">{match.league?.name ?? "–"}</span>
          <span className="text-slate-500 text-xs ml-2">{formatStartTime(match.start_time)}</span>
        </div>
        <span
          className={`shrink-0 text-xs font-semibold px-2 py-0.5 rounded ${
            outcome.isWin ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
          }`}
        >
          {outcome.isWin ? "Победа" : "Поражение"}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-white font-medium">
          vs{" "}
          {outcome.opponentId ? (
            <Link
              href={`/player/${outcome.opponentId}`}
              onClick={(e) => e.stopPropagation()}
              className="hover:text-emerald-400 hover:underline"
            >
              {outcome.opponentName}
            </Link>
          ) : (
            outcome.opponentName
          )}
        </span>
        <span className="font-mono text-slate-200 font-semibold">{outcome.setsTotal}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {outcome.sets.map((s) => (
          <span
            key={s.set_number}
            className={`text-xs font-mono px-2 py-0.5 rounded ${
              s.won ? "bg-emerald-500/15 text-emerald-400" : "bg-slate-700 text-slate-400"
            }`}
            title={s.won ? "Выиграл сет" : "Проиграл сет"}
          >
            {s.myScore}:{s.oppScore} {s.won ? "✓" : "✗"}
          </span>
        ))}
      </div>
    </div>
  );
}
