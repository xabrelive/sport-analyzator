"use client";

import type { Match } from "@/lib/api";

function scoreStr(scores: Match["scores"]): string {
  if (!scores?.length) return "–";
  return scores.map((s) => `${s.home_score}:${s.away_score}`).join(" ");
}

function evColor(ev: number | null): string {
  if (ev === null) return "text-slate-400";
  if (ev >= 0.05) return "text-value font-medium";
  if (ev >= 0.02) return "text-near";
  return "text-slate-400";
}

interface MatchTableProps {
  matches: Match[];
  showProbability?: boolean;
  showEv?: boolean;
}

export function MatchTable({ matches, showProbability, showEv }: MatchTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-800 text-slate-300">
          <tr>
            <th className="px-4 py-3">Лига</th>
            <th className="px-4 py-3">Игроки</th>
            <th className="px-4 py-3">Счёт</th>
            <th className="px-4 py-3">Статус</th>
            {showProbability && (
              <>
                <th className="px-4 py-3">P(1)</th>
                <th className="px-4 py-3">P(2)</th>
              </>
            )}
            {showEv && <th className="px-4 py-3">EV</th>}
          </tr>
        </thead>
        <tbody>
          {matches.length === 0 ? (
            <tr>
              <td colSpan={showProbability && showEv ? 7 : 4} className="px-4 py-8 text-center text-slate-500">
                Нет матчей
              </td>
            </tr>
          ) : (
            matches.map((m) => (
              <tr key={m.id} className="border-t border-slate-700 hover:bg-slate-800/50">
                <td className="px-4 py-3">{m.league?.name ?? "–"}</td>
                <td className="px-4 py-3">
                  {m.home_player?.name ?? "?"} — {m.away_player?.name ?? "?"}
                </td>
                <td className="px-4 py-3 font-mono">{scoreStr(m.scores)}</td>
                <td className="px-4 py-3">
                  <span
                    className={
                      m.status === "live"
                        ? "text-rose-400 font-medium"
                        : m.status === "finished"
                          ? "text-slate-500"
                          : "text-slate-400"
                    }
                  >
                    {m.status === "live" ? "Live" : m.status === "finished" ? "Завершён" : "Скоро"}
                  </span>
                </td>
                {showProbability && (
                  <>
                    <td className="px-4 py-3 text-slate-400">–</td>
                    <td className="px-4 py-3 text-slate-400">–</td>
                  </>
                )}
                {showEv && (
                  <td className={`px-4 py-3 ${evColor(null)}`}>–</td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
