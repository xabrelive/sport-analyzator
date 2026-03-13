"use client";

import React, { useMemo, useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchMatch, fetchPlayerStats, fetchMatchAnalytics, fetchStoredRecommendation, fetchLiveRecommendations, type Match, type OddsSnapshot, type PlayerStats, type MatchAnalytics, type LiveRecommendationItem } from "@/lib/api";
import { getCachedMatch, setCachedMatches, isMatchNewerThan } from "@/lib/matchCache";
import { useWebSocket } from "@/hooks/useWebSocket";
import { formatStartTime, formatDateTimeWithYear, setsTotal, getSetsDisplay, formatOddsTime } from "@/lib/format";

const MARKET_ORDER = ["winner", "win", "92_1", "92_2", "92_3", "92_4", "92_5", "92_6", "92_7", "92_8", "92_9", "92_10", "92_11", "92_12", "92_13", "92_14", "92_15", "92_16", "92_17", "92_18", "92_19", "92_20", "92_21", "set_winner", "total", "handicap"];
/**
 * Подписи рынков. Одинаковые в bet365 и BetsAPI.
 * 1–2-й сет: тотал очков и фора по сетам; 3–7-й сет — то же (матчи бывают до 7 сетов, BO3/BO5/BO7).
 */
const MARKET_LABELS: Record<string, string> = {
  winner: "Match Winner 2-Way",
  win: "Match Winner 2-Way",
  "92_1": "Match Winner 2-Way",
  "92_2": "Asian Handicap",
  handicap: "Asian Handicap",
  "92_3": "Over/Under",
  total: "Over/Under",
  "92_4": "Total Points (Match)",
  "92_5": "Total Points (1st Set)",
  "92_6": "Total Points (2nd Set)",
  "92_7": "Asian Handicap (1st Set)",
  "92_8": "Asian Handicap (2nd Set)",
  "92_9": "Home Total Points",
  "92_10": "Home Total Points (1st Set)",
  "92_11": "Home Total Points (2nd Set)",
  "92_12": "Total Points (3rd Set)",
  "92_13": "Total Points (4th Set)",
  "92_14": "Total Points (5th Set)",
  "92_15": "Total Points (6th Set)",
  "92_16": "Total Points (7th Set)",
  "92_17": "Asian Handicap (3rd Set)",
  "92_18": "Asian Handicap (4th Set)",
  "92_19": "Asian Handicap (5th Set)",
  "92_20": "Asian Handicap (6th Set)",
  "92_21": "Asian Handicap (7th Set)",
  set_winner: "Set Winner",
};

function getMarketLabel(market: string): string {
  if (MARKET_LABELS[market]) return MARKET_LABELS[market];
  if (/^92_\d+$/.test(market)) return `Рынок ${market}`;
  return market;
}

/** Минуты без обновления — считаем коэффициент больше не доступным (лайв). */
const STALE_ODDS_MINUTES = 2;
const STALE_ODDS_MS = STALE_ODDS_MINUTES * 60 * 1000;

/** Иконка замочка (недоступный коэффициент). */
function LockIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

const SELECTION_ORDER: Record<string, number> = { home: 0, "1": 0, away: 1, "2": 1, over: 0, under: 1 };

/** Рынки с форой (линия в подписи П1/П2). */
function isHandicapMarket(market: string): boolean {
  if (market === "92_2" || market === "handicap") return true;
  if (/^92_(7|8|17|18|19|20|21)$/.test(market)) return true;
  return false;
}

function selectionLabel(selection: string, market: string, lineValue?: string | null): string {
  const s = selection.toLowerCase();
  const line = lineValue != null && lineValue !== "" ? String(lineValue) : null;
  if (s === "home" || s === "1") return line != null && isHandicapMarket(market) ? `П1 (${Number(line) >= 0 ? "+" : ""}${line})` : "П1";
  if (s === "away" || s === "2") return line != null && isHandicapMarket(market) ? `П2 (${Number(line) >= 0 ? "+" : ""}${line})` : "П2";
  if (s === "over") return line != null ? `ТБ ${line}` : "ТБ";
  if (s === "under") return line != null ? `ТМ ${line}` : "ТМ";
  if (s.startsWith("set_1_home") || s === "set_1_home") return "П1 сет 1";
  if (s.startsWith("set_1_away") || s === "set_1_away") return "П2 сет 1";
  if (s.startsWith("over_")) return `ТБ ${s.replace("over_", "")}`;
  if (s.startsWith("under_")) return `ТМ ${s.replace("under_", "")}`;
  if (s.startsWith("home_") && s.includes("-")) return `П1 (${s.replace("home_", "")})`;
  if (s.startsWith("away_") && s.includes("+")) return `П2 (${s.replace("away_", "+")})`;
  if (s.startsWith("home_")) return `П1 ${s.replace("home_", "")}`;
  if (s.startsWith("away_")) return `П2 ${s.replace("away_", "")}`;
  return selection;
}

/** Для лайва показываем только коэффициенты на старте матча (первый снимок по времени), без привязки к текущему счёту. */
function useLatestOddsByMarket(match: Match) {
  const snapshots = match.odds_snapshots ?? [];
  const isLive = match.status === "live";

  return useMemo(() => {
    const byKey = new Map<string, OddsSnapshot[]>();
    for (const o of snapshots) {
      const key = `${o.market}\t${o.selection}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key)!.push(o);
    }
    const latest: Array<{ market: string; selection: string; snapshot: OddsSnapshot; history: OddsSnapshot[] }> = [];
    for (const [key, list] of byKey.entries()) {
      const [market, selection] = key.split("\t");
      const sorted = [...list].sort((a, b) => {
        const timeA = a.snapshot_time || a.timestamp || "";
        const timeB = b.snapshot_time || b.timestamp || "";
        return new Date(timeA).getTime() - new Date(timeB).getTime();
      });
      const first = sorted[0];
      if (first) latest.push({ market, selection, snapshot: first, history: sorted });
    }
    const byMarket = new Map<string, typeof latest>();
    for (const item of latest) {
      if (!byMarket.has(item.market)) byMarket.set(item.market, []);
      byMarket.get(item.market)!.push(item);
    }
    for (const m of byMarket.values()) {
      m.sort((a, b) => {
        const orderA = SELECTION_ORDER[a.selection.toLowerCase()] ?? 2;
        const orderB = SELECTION_ORDER[b.selection.toLowerCase()] ?? 2;
        if (orderA !== orderB) return orderA - orderB;
        return a.selection.localeCompare(b.selection);
      });
    }
    return { byMarket, currentScore: null };
  }, [snapshots]);
}

function OddsGrid({ match }: { match: Match }) {
  const { byMarket, currentScore } = useLatestOddsByMarket(match);
  const [modal, setModal] = useState<{ market: string; selection: string; history: OddsSnapshot[] } | null>(null);
  const isLive = match.status === "live";
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isLive) return;
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, [isLive]);

  const markets = useMemo(() => {
    const seen = new Set(byMarket.keys());
    const order = MARKET_ORDER.filter((m) => seen.has(m));
    const rest = [...seen].filter((m) => !MARKET_ORDER.includes(m)).sort();
    return [...order, ...rest];
  }, [byMarket]);

  if (markets.length === 0) {
    const isLive = match.status === "live";
    return (
      <p className="text-slate-500 text-sm">
        {isLive ? "Нет коэффициентов" : "Коэффициенты появятся перед началом или в лайве."}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {isLive && (
        <p className="text-slate-400 text-sm">
          Показаны коэффициенты на старте матча (в лайве не обновляются). Нажмите на коэффициент — откроется история снимков.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-500 border-b border-slate-700">
              <th className="text-left py-2 pr-4">Событие</th>
              <th className="text-left py-2 pr-4">Исход</th>
              <th className="text-left py-2 pr-4">Коэф.</th>
              <th className="text-left py-2">Счёт / время</th>
            </tr>
          </thead>
          <tbody>
            {markets.map((market) => {
              const rows = byMarket.get(market) ?? [];
              const marketLabel = getMarketLabel(market);
              return rows.map((item, idx) => {
                const { snapshot, history } = item;
                const scoreStr = snapshot.score_at_snapshot?.trim() || "—";
                const timeStr = formatOddsTime(snapshot.snapshot_time || snapshot.timestamp);
                const lineVal = snapshot.line_value != null ? String(snapshot.line_value) : null;
                const scoreTimeStr =
                  scoreStr !== "—" && timeStr !== "—"
                    ? `при счёте ${scoreStr} · ${timeStr}`
                    : scoreStr !== "—"
                      ? `при счёте ${scoreStr}`
                      : timeStr !== "—"
                        ? timeStr
                        : "—";
                const snapshotTime = snapshot.snapshot_time || snapshot.timestamp;
                const snapshotMs = snapshotTime ? new Date(snapshotTime).getTime() : 0;
                const isStale = isLive && snapshotMs > 0 && now - snapshotMs > STALE_ODDS_MS;
                return (
                  <tr
                    key={`${market}-${item.selection}-${idx}`}
                    className={`border-b border-slate-800 ${isStale ? "opacity-75" : ""}`}
                  >
                    <td className="py-2 pr-4 text-slate-400">{marketLabel}</td>
                    <td className="py-2 pr-4 text-slate-300">{selectionLabel(item.selection, market, lineVal)}</td>
                    <td className="py-2 pr-4">
                      {isStale ? (
                        <span
                          className="inline-flex items-center gap-1.5 font-mono text-slate-500"
                          title="Больше не доступен"
                        >
                          {Number(snapshot.odds).toFixed(2)}
                          <LockIcon className="text-slate-500 shrink-0" />
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setModal({ market, selection: item.selection, history })}
                          className="font-mono text-emerald-400 hover:text-emerald-300 hover:underline"
                        >
                          {Number(snapshot.odds).toFixed(2)}
                        </button>
                      )}
                    </td>
                    <td className="py-2 text-slate-500 text-xs">{scoreTimeStr}</td>
                  </tr>
                );
              });
            })}
          </tbody>
        </table>
      </div>

      {modal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
          onClick={() => setModal(null)}
        >
          <div
            className="rounded-xl border border-slate-600 bg-slate-900 p-6 w-full max-w-lg max-h-[80vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-white mb-2">
              История: {getMarketLabel(modal.market)} — {selectionLabel(modal.selection, modal.market)}
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-2 pr-3">Время</th>
                  <th className="text-left py-2 pr-3">Счёт</th>
                  <th className="text-left py-2 pr-3">Коэф.</th>
                  <th className="text-left py-2">Букмекер</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  // Один ряд на счёт: для каждого score_at_snapshot оставляем только последний по времени снимок (убираем дубли)
                  const ts = (v?: string | null): number => (v ? new Date(v).getTime() : 0);
                  const byScore = new Map<string, OddsSnapshot>();
                  for (const o of modal.history) {
                    const score = (o.score_at_snapshot || "").trim() || "—";
                    const existing = byScore.get(score);
                    const t = ts(o.snapshot_time ?? o.timestamp ?? null);
                    if (!existing || t > ts(existing.snapshot_time ?? existing.timestamp ?? null)) {
                      byScore.set(score, o);
                    }
                  }
                  const deduped = [...byScore.values()].sort((a, b) => {
                    const ta = ts(a.snapshot_time ?? a.timestamp ?? null);
                    const tb = ts(b.snapshot_time ?? b.timestamp ?? null);
                    return tb - ta;
                  });
                  return deduped.map((o, i) => (
                    <tr key={i} className="border-b border-slate-800">
                      <td className="py-2 pr-3 text-slate-400">{formatOddsTime(o.snapshot_time || o.timestamp)}</td>
                      <td className="py-2 pr-3 text-slate-300">{o.score_at_snapshot?.trim() || "—"}</td>
                      <td className="py-2 pr-3 font-mono text-emerald-400">{Number(o.odds).toFixed(2)}</td>
                      <td className="py-2 text-slate-500">{o.bookmaker}</td>
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
            <button
              type="button"
              onClick={() => setModal(null)}
              className="mt-4 w-full rounded-lg border border-slate-600 py-2 text-slate-300 hover:bg-slate-800"
            >
              Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MatchDetailPage() {
  const params = useParams();
  const id = params?.id as string | undefined;
  const [match, setMatch] = useState<Match | null>(() => (id ? getCachedMatch(id) ?? null : null));
  const [statsHome, setStatsHome] = useState<PlayerStats | null>(null);
  const [statsAway, setStatsAway] = useState<PlayerStats | null>(null);
  const [analytics, setAnalytics] = useState<MatchAnalytics | null>(null);
  const [storedRec, setStoredRec] = useState<string | null>(null);
  const [liveRecs, setLiveRecs] = useState<LiveRecommendationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetchMatch = useCallback(() => {
    if (!id) return;
    fetchMatch(id)
      .then((m) => {
        const current = getCachedMatch(id);
        if (!current || isMatchNewerThan(m, current)) {
          setMatch(m);
          setCachedMatches([m]);
        }
      })
      .catch(() => {});
  }, [id]);

  useWebSocket((message) => {
    if (message?.type === "matches_updated" && id && Array.isArray(message.match_ids) && message.match_ids.includes(id)) {
      refetchMatch();
    }
  });

  React.useEffect(() => {
    if (!id) return;
    let cancelled = false;
    Promise.all([
      fetchMatch(id),
      fetchMatchAnalytics(id),
      fetchStoredRecommendation(id),
    ])
      .then(([m, a, rec]) => {
        if (!cancelled) {
          const current = getCachedMatch(id);
          const nextMatch = !current || isMatchNewerThan(m, current) ? m : current;
          setMatch(nextMatch);
          setCachedMatches([nextMatch]);
          setAnalytics(a);
          setStoredRec(rec);
        }
        if (m?.home_player?.id) fetchPlayerStats(m.home_player.id).then((s) => { if (!cancelled) setStatsHome(s); });
        if (m?.away_player?.id) fetchPlayerStats(m.away_player.id).then((s) => { if (!cancelled) setStatsAway(s); });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
  }, [id]);

  React.useEffect(() => {
    if (!id || !match || match.status !== "live") return;
    let cancelled = false;
    fetchLiveRecommendations(id)
      .then((r) => { if (!cancelled) setLiveRecs(r.items); })
      .catch(() => { if (!cancelled) setLiveRecs([]); });
    const t = setInterval(() => {
      fetchLiveRecommendations(id)
        .then((r) => { if (!cancelled) setLiveRecs(r.items); })
        .catch(() => {});
    }, 15000);
    return () => { cancelled = true; clearInterval(t); };
  }, [id, match?.status]);

  if (!id || loading) {
    return (
      <main className="max-w-3xl mx-auto px-4 py-6">
        <p className="text-slate-500">{loading ? "Загрузка..." : "Нет id"}</p>
      </main>
    );
  }
  if (error || !match) {
    return (
      <main className="max-w-3xl mx-auto px-4 py-6">
        <p className="text-rose-400">{error ?? "Матч не найден"}</p>
        <Link href="/line" className="text-slate-400 hover:text-white mt-2 inline-block">
          ← К линии
        </Link>
      </main>
    );
  }

  const isLive = match.status === "live";
  const isFinished = match.status === "finished";
  const isCancelled = match.status === "cancelled";

  return (
    <main className="max-w-3xl mx-auto px-4 py-6">
      <Link href="/line" className="text-slate-400 hover:text-white text-sm mb-4 inline-block">
        ← К линии
      </Link>
      <div className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 space-y-6">
        <div className="flex items-center justify-between gap-4">
          <span className="text-slate-500 text-sm">{match.league?.name ?? "–"}</span>
          {isLive && (
            <span className="flex items-center gap-1 text-rose-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-rose-400 animate-pulse" />
              Live
            </span>
          )}
          {!isLive && !isFinished && !isCancelled && (
            <span className="text-slate-500 text-sm">{formatStartTime(match.start_time)}</span>
          )}
          {isCancelled && (
            <span className="text-amber-400/90 font-medium">Отменён</span>
          )}
          {(isLive || isFinished) && (match.started_at || match.result?.finished_at) && (
            <span className="text-slate-500 text-xs block mt-1">
              {match.started_at && <>Начало: {formatDateTimeWithYear(match.started_at)}</>}
              {match.started_at && match.result?.finished_at && " · "}
              {match.result?.finished_at && <>Окончание: {formatDateTimeWithYear(match.result.finished_at)}</>}
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-slate-500 text-xs uppercase tracking-wider mb-1">Хозяин</div>
            <div className="font-semibold text-white text-lg">
              {match.home_player ? (
                <Link href={`/player/${match.home_player.id}`} className="hover:text-emerald-400 hover:underline">
                  {match.home_player.name}
                </Link>
              ) : (
                "?"
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-slate-500 text-xs uppercase tracking-wider mb-1">Гость</div>
            <div className="font-semibold text-white text-lg">
              {match.away_player ? (
                <Link href={`/player/${match.away_player.id}`} className="hover:text-emerald-400 hover:underline">
                  {match.away_player.name}
                </Link>
              ) : (
                "?"
              )}
            </div>
          </div>
        </div>
        {(isLive || isFinished) && match.scores && match.scores.length > 0 && (
          <div className="border-t border-slate-700 pt-4">
            <div className="text-slate-500 text-xs uppercase tracking-wider mb-2">Счёт по сетам</div>
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline gap-4 flex-wrap">
                <span className="text-slate-400 text-sm">Общий счёт:</span>
                <span className="font-mono text-2xl font-bold text-white">{setsTotal(match)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-300">
                {getSetsDisplay(match.scores, isLive).map((set) => (
                  <span key={set.set_number} className="font-mono text-sm">
                    Сет {set.set_number}: {set.home_score}:{set.away_score}
                    {set.isCurrent && (
                      <span className="ml-1 text-rose-400 text-xs font-medium">(текущий)</span>
                    )}
                    {!set.isCurrent && isLive && (
                      <span className="ml-1 text-slate-500 text-xs">(завершён)</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
            {match.result && (
              <p className="text-slate-400 text-sm mt-2">
                Победитель: {match.result.winner_name ?? match.result.final_score}
              </p>
            )}
          </div>
        )}
        {isCancelled && (
          <div className="border-t border-slate-700 pt-4">
            <p className="text-amber-400/90 font-medium">Матч отменён</p>
          </div>
        )}
        <div className="border-t border-slate-700 pt-4">
          <div className="text-slate-500 text-xs uppercase tracking-wider mb-2">Прогнозы по матчу</div>

          <div className="mb-4 p-3 rounded-lg bg-slate-800/60 border border-slate-700/80">
            <div className="text-slate-400 text-xs uppercase tracking-wider mb-1">Полный прогноз (прематч)</div>
            {storedRec ? (
              <>
                <p className="text-emerald-400/95 text-sm font-medium">{storedRec}</p>
                <p className="text-slate-500 text-xs mt-1">Сохранённый прогноз из таблицы линии/лайва. Не пересчитывается.</p>
              </>
            ) : (
              <p className="text-slate-500 text-sm">Нет сохранённого прогноза (прематч).</p>
            )}
          </div>

          {isLive && (
            <div className="mb-4 p-3 rounded-lg bg-slate-800/40 border border-slate-700/60">
              <div className="text-slate-400 text-xs uppercase tracking-wider mb-1">В моменте (только на будущие сеты, кф ≥ 1.3)</div>
              <p className="text-slate-500 text-xs mb-2">Пересчёт по текущему счёту. Показываем только исходы с коэффициентом ≥ 1.3 и вероятностью ≥ 70%, чтобы успеть поставить на следующий сет.</p>
              {liveRecs.length > 0 ? (
                <ul className="space-y-1.5">
                  {liveRecs.map((r, i) => (
                    <li key={i} className="text-emerald-400/95 text-sm font-medium flex flex-wrap items-center gap-2">
                      <span>• {r.text}</span>
                      <span className="font-mono text-teal-400/90 text-xs">кф {r.odds}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-slate-500 text-sm">Нет прогнозов в моменте: нет коэффициентов ≥ 1.3 на следующий сет или недостаточная вероятность.</p>
              )}
            </div>
          )}

          <div className="text-slate-500 text-xs uppercase tracking-wider mb-2">По игрокам</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-4">
              <h3 className="text-slate-300 font-semibold mb-2">
                {match.home_player ? (
                  <Link href={`/player/${match.home_player.id}`} className="hover:text-emerald-400 hover:underline">
                    {match.home_player.name}
                  </Link>
                ) : (
                  "Хозяин"
                )}
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm mb-3">
                <div>
                  <span className="text-slate-500 text-xs">1-й сет</span>
                  <div className="font-mono text-emerald-400/90">{statsHome ? `${((statsHome.win_first_set_pct ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">2-й сет</span>
                  <div className="font-mono text-emerald-400/90">{statsHome ? `${((statsHome.win_second_set_pct ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">Сетов/матч</span>
                  <div className="font-mono text-white">{statsHome?.avg_sets_per_match ?? "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">Побед</span>
                  <div className="font-mono text-white">{statsHome ? `${((statsHome.win_rate ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
              </div>
              {analytics && (analytics.home_strengths.length > 0 || analytics.home_weaknesses.length > 0) && (
                <div className="border-t border-slate-700 pt-2 mt-2 space-y-2">
                  {analytics.home_strengths.length > 0 && (
                    <div>
                      <span className="text-slate-500 text-xs">Сильные стороны:</span>
                      <ul className="mt-0.5 space-y-0.5 text-xs text-emerald-400/95">
                        {analytics.home_strengths.map((s, i) => (
                          <li key={i}>• {s}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {analytics.home_weaknesses.length > 0 && (
                    <div>
                      <span className="text-slate-500 text-xs">Слабые стороны:</span>
                      <ul className="mt-0.5 space-y-0.5 text-xs text-rose-400/95">
                        {analytics.home_weaknesses.map((w, i) => (
                          <li key={i}>• {w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/40 p-4">
              <h3 className="text-slate-300 font-semibold mb-2">
                {match.away_player ? (
                  <Link href={`/player/${match.away_player.id}`} className="hover:text-emerald-400 hover:underline">
                    {match.away_player.name}
                  </Link>
                ) : (
                  "Гость"
                )}
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-sm mb-3">
                <div>
                  <span className="text-slate-500 text-xs">1-й сет</span>
                  <div className="font-mono text-emerald-400/90">{statsAway ? `${((statsAway.win_first_set_pct ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">2-й сет</span>
                  <div className="font-mono text-emerald-400/90">{statsAway ? `${((statsAway.win_second_set_pct ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">Сетов/матч</span>
                  <div className="font-mono text-white">{statsAway?.avg_sets_per_match ?? "–"}</div>
                </div>
                <div>
                  <span className="text-slate-500 text-xs">Побед</span>
                  <div className="font-mono text-white">{statsAway ? `${((statsAway.win_rate ?? 0) * 100).toFixed(1)}%` : "–"}</div>
                </div>
              </div>
              {analytics && (analytics.away_strengths.length > 0 || analytics.away_weaknesses.length > 0) && (
                <div className="border-t border-slate-700 pt-2 mt-2 space-y-2">
                  {analytics.away_strengths.length > 0 && (
                    <div>
                      <span className="text-slate-500 text-xs">Сильные стороны:</span>
                      <ul className="mt-0.5 space-y-0.5 text-xs text-emerald-400/95">
                        {analytics.away_strengths.map((s, i) => (
                          <li key={i}>• {s}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {analytics.away_weaknesses.length > 0 && (
                    <div>
                      <span className="text-slate-500 text-xs">Слабые стороны:</span>
                      <ul className="mt-0.5 space-y-0.5 text-xs text-rose-400/95">
                        {analytics.away_weaknesses.map((w, i) => (
                          <li key={i}>• {w}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {analytics?.justification && (
            <div className="border-t border-slate-700 pt-4">
              <div className="text-slate-500 text-xs uppercase tracking-wider mb-1">Обоснование аналитики</div>
              <p className="text-slate-400 text-sm">{analytics.justification}</p>
            </div>
          )}
        </div>
        <div className="border-t border-slate-700 pt-4">
          <div className="text-slate-500 text-xs uppercase tracking-wider mb-2">Коэффициенты</div>
          <OddsGrid match={match} />
        </div>
      </div>
    </main>
  );
}
