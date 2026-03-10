"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getTableTennisMatchCard, type TableTennisMatchCard } from "@/lib/api";

function formatDateTime(ts: number | undefined): string {
  if (ts == null) return "—";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export default function TableTennisMatchCardPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [card, setCard] = useState<TableTennisMatchCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisMatchCard(id)
      .then((res) => !cancelled && setCard(res))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Ошибка загрузки"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) return <div className="p-6 md:p-8"><p className="text-slate-400">Загрузка…</p></div>;
  if (error) return <div className="p-6 md:p-8"><p className="text-rose-400">{error}</p></div>;
  if (!card?.match) return <div className="p-6 md:p-8"><p className="text-slate-400">Матч не найден.</p></div>;

  const m = card.match;
  const setsLine = m.sets
    ? Object.keys(m.sets)
        .sort((a, b) => Number(a) - Number(b))
        .map((k) => {
          const s = m.sets?.[k];
          if (!s || (s.home == null && s.away == null)) return null;
          return `${s.home ?? ""}-${s.away ?? ""}`;
        })
        .filter(Boolean)
        .join(" ")
    : "";

  return (
    <div className="p-6 md:p-8 space-y-8">
      <div>
        <Link href="/dashboard/table-tennis/line" className="text-slate-400 hover:text-white text-sm mb-2 inline-block">← Линия</Link>
        <h1 className="font-display text-2xl font-bold text-white">{m.home_name} — {m.away_name}</h1>
        <p className="text-slate-400 text-sm mt-1">{m.league_name} · {formatDateTime(m.time)}</p>
      </div>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Статистика матча</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Статус</span><p className="text-white font-semibold">{m.status ?? "—"}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Кф П1 / П2 (старт)</span><p className="text-white font-semibold tabular-nums">{m.odds_1 != null ? m.odds_1.toFixed(2) : "—"} / {m.odds_2 != null ? m.odds_2.toFixed(2) : "—"}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Счёт по сетам</span><p className="text-emerald-300 font-semibold tabular-nums">{m.sets_score ?? "—"}</p>{setsLine ? <p className="text-xs text-slate-400">({setsLine})</p> : null}</div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <span className="text-slate-400 text-sm">Прематч‑прогноз</span>
            <p className="text-emerald-300 font-semibold text-sm mt-0.5">
              {card.forecast ?? "—"}
            </p>
            {card.forecast_confidence != null && (
              <p className="text-xs text-slate-400 mt-1">
                Уверенность модели: {card.forecast_confidence.toFixed(0)}%
              </p>
            )}
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Форма игроков (последние завершённые)</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-2">
              <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(m.home_id)}`} className="hover:text-emerald-200">{m.home_name}</Link>
            </p>
            <p className="text-slate-300 text-sm">Матчей: {card.home_stats?.finished_matches ?? 0}</p>
            <p className="text-slate-300 text-sm">Победы/Поражения: {card.home_stats?.wins ?? 0}/{card.home_stats?.losses ?? 0}</p>
            <p className="text-slate-300 text-sm">Winrate: {card.home_stats?.win_rate != null ? `${card.home_stats.win_rate}%` : "—"}</p>
          </div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-2">
              <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(m.away_id)}`} className="hover:text-emerald-200">{m.away_name}</Link>
            </p>
            <p className="text-slate-300 text-sm">Матчей: {card.away_stats?.finished_matches ?? 0}</p>
            <p className="text-slate-300 text-sm">Победы/Поражения: {card.away_stats?.wins ?? 0}/{card.away_stats?.losses ?? 0}</p>
            <p className="text-slate-300 text-sm">Winrate: {card.away_stats?.win_rate != null ? `${card.away_stats.win_rate}%` : "—"}</p>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">
          Аналитика матча
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3 md:col-span-2">
            <span className="text-slate-400 text-sm">Краткое обоснование</span>
            <p className="text-slate-200 text-sm mt-1">
              {card.analytics?.justification ?? "Недостаточно данных для подробной аналитики по этому матчу."}
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <span className="text-slate-400 text-sm">Личные встречи</span>
            {card.analytics?.head_to_head && card.analytics.head_to_head.total > 0 ? (
              <p className="text-slate-200 text-sm mt-1">
                Матчей: {card.analytics.head_to_head.total}
                <br />
                {m.home_name}: {card.analytics.head_to_head.home_wins} побед
                <br />
                {m.away_name}: {card.analytics.head_to_head.away_wins} побед
              </p>
            ) : (
              <p className="text-slate-500 text-sm mt-1">Личных встреч в базе пока нет.</p>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-1">{m.home_name} — ключевые моменты</p>
            {card.analytics?.home_strengths && card.analytics.home_strengths.length > 0 && (
              <>
                <p className="text-emerald-300 text-xs mb-1">Сильные стороны:</p>
                <ul className="list-disc list-inside text-slate-200 text-xs space-y-0.5">
                  {card.analytics.home_strengths.map((s, idx) => (
                    <li key={idx}>{s}</li>
                  ))}
                </ul>
              </>
            )}
            {card.analytics?.home_weaknesses && card.analytics.home_weaknesses.length > 0 && (
              <>
                <p className="text-rose-300 text-xs mt-2 mb-1">Слабые стороны:</p>
                <ul className="list-disc list-inside text-slate-200 text-xs space-y-0.5">
                  {card.analytics.home_weaknesses.map((s, idx) => (
                    <li key={idx}>{s}</li>
                  ))}
                </ul>
              </>
            )}
            {!card.analytics?.home_strengths?.length && !card.analytics?.home_weaknesses?.length && (
              <p className="text-slate-500 text-xs">Недостаточно данных по игроку.</p>
            )}
          </div>

          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-1">{m.away_name} — ключевые моменты</p>
            {card.analytics?.away_strengths && card.analytics.away_strengths.length > 0 && (
              <>
                <p className="text-emerald-300 text-xs mb-1">Сильные стороны:</p>
                <ul className="list-disc list-inside text-slate-200 text-xs space-y-0.5">
                  {card.analytics.away_strengths.map((s, idx) => (
                    <li key={idx}>{s}</li>
                  ))}
                </ul>
              </>
            )}
            {card.analytics?.away_weaknesses && card.analytics.away_weaknesses.length > 0 && (
              <>
                <p className="text-rose-300 text-xs mt-2 mb-1">Слабые стороны:</p>
                <ul className="list-disc list-inside text-slate-200 text-xs space-y-0.5">
                  {card.analytics.away_weaknesses.map((s, idx) => (
                    <li key={idx}>{s}</li>
                  ))}
                </ul>
              </>
            )}
            {!card.analytics?.away_strengths?.length && !card.analytics?.away_weaknesses?.length && (
              <p className="text-slate-500 text-xs">Недостаточно данных по игроку.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

