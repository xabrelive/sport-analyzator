"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getTableTennisPlayerCardPaged, type TableTennisPlayerCard } from "@/lib/api";

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

export default function TableTennisPlayerPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [card, setCard] = useState<TableTennisPlayerCard | null>(null);
  const [upcomingPage, setUpcomingPage] = useState(1);
  const [finishedPage, setFinishedPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisPlayerCardPaged(id, upcomingPage, finishedPage, pageSize)
      .then((res) => {
        if (!cancelled) setCard(res);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, upcomingPage, finishedPage]);

  if (loading) return <div className="p-6 md:p-8"><p className="text-slate-400">Загрузка…</p></div>;
  if (error) return <div className="p-6 md:p-8"><p className="text-rose-400">{error}</p></div>;

  return (
    <div className="p-6 md:p-8 space-y-8">
      <div>
        <Link href="/dashboard/table-tennis/players" className="text-slate-400 hover:text-white text-sm mb-2 inline-block">
          ← Игроки
        </Link>
        <h1 className="font-display text-2xl font-bold text-white">{card?.player?.name || "Игрок"}</h1>
      </div>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Статистика игрока</h2>
        <div className="flex flex-wrap gap-4">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Всего матчей</span><p className="text-xl font-semibold text-white">{card?.stats?.total_matches ?? 0}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Завершено</span><p className="text-xl font-semibold text-white">{card?.stats?.finished_matches ?? 0}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Победы / Поражения</span><p className="text-xl font-semibold text-white">{card?.stats?.wins ?? 0} / {card?.stats?.losses ?? 0}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Winrate</span><p className="text-xl font-semibold text-white">{card?.stats?.win_rate != null ? `${card.stats.win_rate}%` : "—"}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Предстоящие</span><p className="text-xl font-semibold text-white">{card?.stats?.upcoming_matches ?? 0}</p></div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Предстоящие матчи</h2>
        {(!card?.upcoming_matches || card.upcoming_matches.length === 0) ? <p className="text-slate-500">Нет предстоящих матчей.</p> : (
          <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
            <ul className="divide-y divide-slate-700/60">
              {card.upcoming_matches.map((ev) => (
                <li key={String(ev.id)} className="px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="text-white">
                    <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-300">
                      {ev.home_name}
                    </Link>
                    {" — "}
                    <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-300">
                      {ev.away_name}
                    </Link>
                  </span>
                  <span className="text-slate-400">
                    <Link href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`} className="hover:text-emerald-300">
                      {ev.league_name}
                    </Link>
                    {" · "}
                    <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="hover:text-emerald-300">
                      {formatDateTime(ev.time)}
                    </Link>
                  </span>
                  <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">Карточка матча</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <div className="mt-2 flex items-center gap-2">
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={upcomingPage <= 1}
          onClick={() => setUpcomingPage((v) => Math.max(1, v - 1))}
        >
          Назад
        </button>
        <span className="text-slate-400 text-sm">
          Страница {upcomingPage} из{" "}
          {Math.max(
            1,
            Math.ceil(
              (card?.pagination?.upcoming.total ?? 0) /
                (card?.pagination?.upcoming.page_size ?? pageSize)
            )
          )}
        </span>
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={
            upcomingPage >=
            Math.max(
              1,
              Math.ceil(
                (card?.pagination?.upcoming.total ?? 0) /
                  (card?.pagination?.upcoming.page_size ?? pageSize)
              )
            )
          }
          onClick={() => setUpcomingPage((v) => v + 1)}
        >
          Вперёд
        </button>
      </div>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Прошедшие матчи</h2>
        {(!card?.finished_matches || card.finished_matches.length === 0) ? <p className="text-slate-500">Нет прошедших матчей.</p> : (
          <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
            <ul className="divide-y divide-slate-700/60">
              {card.finished_matches.map((ev) => (
                <li key={String(ev.id)} className="px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="text-white">
                    <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.home_id)}`} className="hover:text-emerald-300">
                      {ev.home_name}
                    </Link>
                    {" — "}
                    <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(ev.away_id)}`} className="hover:text-emerald-300">
                      {ev.away_name}
                    </Link>
                    {ev.sets_score ? <span className="text-slate-400 ml-2">({ev.sets_score})</span> : null}
                  </span>
                  <span className="text-slate-400">
                    <Link href={`/dashboard/table-tennis/leagues/${encodeURIComponent(ev.league_id)}`} className="hover:text-emerald-300">
                      {ev.league_name}
                    </Link>
                    {" · "}
                    <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="hover:text-emerald-300">
                      {formatDateTime(ev.time)}
                    </Link>
                  </span>
                  <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(String(ev.id))}`} className="text-emerald-300 hover:text-emerald-200">Карточка матча</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <div className="mt-2 flex items-center gap-2">
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={finishedPage <= 1}
          onClick={() => setFinishedPage((v) => Math.max(1, v - 1))}
        >
          Назад
        </button>
        <span className="text-slate-400 text-sm">
          Страница {finishedPage} из{" "}
          {Math.max(
            1,
            Math.ceil(
              (card?.pagination?.finished.total ?? 0) /
                (card?.pagination?.finished.page_size ?? pageSize)
            )
          )}
        </span>
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={
            finishedPage >=
            Math.max(
              1,
              Math.ceil(
                (card?.pagination?.finished.total ?? 0) /
                  (card?.pagination?.finished.page_size ?? pageSize)
              )
            )
          }
          onClick={() => setFinishedPage((v) => v + 1)}
        >
          Вперёд
        </button>
      </div>
    </div>
  );
}
