"use client";

import Link from "next/link";
import type { PlayerStats as PlayerStatsType } from "@/lib/api";

function pctStr(pct: number | null | undefined): string {
  if (pct == null) return "–";
  return `${(pct * 100).toFixed(1)}%`;
}

function patternLabel(p: string): string {
  return p.split("").map((c) => (c === "W" ? "В" : "П")).join("–");
}

interface PlayerStatsBlockProps {
  title: string;
  playerId: string | null;
  playerName: string;
  stats: PlayerStatsType | null;
  compact?: boolean;
}

export function PlayerStatsBlock({ title, playerId, playerName, stats, compact }: PlayerStatsBlockProps) {
  if (!stats) {
    return (
      <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-4">
        <h3 className="text-slate-400 font-medium mb-2">{title}</h3>
        <p className="text-slate-500 text-sm">Нет данных по игроку</p>
      </div>
    );
  }

  const recommendations: string[] = [];
  if (stats.win_first_set_pct != null) {
    if (stats.win_first_set_pct >= 0.6) recommendations.push(`Часто выигрывает 1-й сет (${pctStr(stats.win_first_set_pct)})`);
    else if (stats.win_first_set_pct <= 0.4 && (stats.matches_with_first_set ?? 0) >= 10)
      recommendations.push(`Редко выигрывает 1-й сет (${pctStr(stats.win_first_set_pct)})`);
  }
  if (stats.win_second_set_pct != null) {
    if (stats.win_second_set_pct >= 0.6) recommendations.push(`Сильный во 2-м сете (${pctStr(stats.win_second_set_pct)})`);
    else if (stats.win_second_set_pct <= 0.4 && (stats.matches_with_second_set ?? 0) >= 10)
      recommendations.push(`Слаб во 2-м сете (${pctStr(stats.win_second_set_pct)})`);
  }
  if (stats.avg_sets_per_match != null) {
    if (stats.avg_sets_per_match >= 5) recommendations.push(`Часто играет долгие матчи (в ср. ${stats.avg_sets_per_match} сетов)`);
    else if (stats.avg_sets_per_match <= 3.5) recommendations.push(`Часто заканчивает матчи быстро (в ср. ${stats.avg_sets_per_match} сетов)`);
  }
  if (stats.win_rate != null && stats.total_matches >= 15) {
    if (stats.win_rate >= 0.65) recommendations.push(`Высокий % побед (${pctStr(stats.win_rate)})`);
    else if (stats.win_rate <= 0.35) recommendations.push(`Низкий % побед (${pctStr(stats.win_rate)})`);
  }
  if (stats.set_patterns?.length) {
    const top = stats.set_patterns[0];
    if (top && top.pct != null && top.pct >= 0.15)
      recommendations.push(`Частый порядок сетов: ${patternLabel(top.pattern)} (${pctStr(top.pct)})`);
  }

  return (
    <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-4">
      <h3 className="text-slate-300 font-semibold mb-2">
        {playerId ? (
          <Link href={`/player/${playerId}`} className="hover:text-emerald-400 hover:underline">
            {playerName}
          </Link>
        ) : (
          playerName
        )}
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm mb-3">
        <div>
          <span className="text-slate-500 text-xs">1-й сет</span>
          <div className="font-mono text-emerald-400/90">{pctStr(stats.win_first_set_pct)}</div>
        </div>
        <div>
          <span className="text-slate-500 text-xs">2-й сет</span>
          <div className="font-mono text-emerald-400/90">{pctStr(stats.win_second_set_pct)}</div>
        </div>
        <div>
          <span className="text-slate-500 text-xs">Сетов/матч</span>
          <div className="font-mono text-white">{stats.avg_sets_per_match ?? "–"}</div>
        </div>
        <div>
          <span className="text-slate-500 text-xs">Побед</span>
          <div className="font-mono text-white">{pctStr(stats.win_rate)}</div>
        </div>
      </div>
      {!compact && stats.set_win_pct_by_position && stats.set_win_pct_by_position.length > 0 && (
        <div className="mb-3">
          <span className="text-slate-500 text-xs">Выигрыш по сетам:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {stats.set_win_pct_by_position.map((s) => (
              <span key={s.set_number} className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                {s.set_number}: {pctStr(s.pct)}
              </span>
            ))}
          </div>
        </div>
      )}
      {!compact && stats.set_patterns && stats.set_patterns.length > 0 && (
        <div className="mb-3">
          <span className="text-slate-500 text-xs">Порядок сетов (В=выиграл, П=проиграл):</span>
          <ul className="mt-1 space-y-0.5 text-xs text-slate-400">
            {stats.set_patterns.slice(0, 5).map((sp, i) => (
              <li key={i}>
                {patternLabel(sp.pattern)} — {sp.count} матчей ({pctStr(sp.pct)})
              </li>
            ))}
          </ul>
        </div>
      )}
      {recommendations.length > 0 && (
        <div className="border-t border-slate-700 pt-2 mt-2">
          <span className="text-slate-500 text-xs">Рекомендации:</span>
          <ul className="mt-1 space-y-0.5 text-xs text-emerald-400/90">
            {recommendations.map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
