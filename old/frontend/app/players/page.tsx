"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchPlayers, type Player } from "@/lib/api";
import { PlayerAvatar } from "@/components/PlayerAvatar";

const PAGE_SIZE = 24;

export default function PlayersPage() {
  const [items, setItems] = useState<Player[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchPlayers({
        search: search.trim() || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setItems(list);
      setTotal(list.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [search, page]);

  useEffect(() => {
    load();
  }, [load]);

  const onSearch = () => {
    setPage(0);
    load();
  };

  const hasMore = total >= PAGE_SIZE;
  const hasPrev = page > 0;

  return (
    <main className="max-w-5xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-white mb-1">Игроки</h1>
      <p className="text-slate-500 text-sm mb-6">
        Поиск по имени. Клик по карточке — переход в профиль и статистику.
      </p>

      <div className="flex flex-wrap gap-2 mb-6">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          placeholder="Поиск по имени..."
          className="rounded-lg border border-slate-600 bg-slate-800 text-white px-3 py-2 text-sm w-64 placeholder-slate-500"
          aria-label="Поиск игроков"
        />
        <button
          type="button"
          onClick={onSearch}
          className="rounded-lg bg-teal-600 hover:bg-teal-500 text-white px-4 py-2 text-sm font-medium"
        >
          Найти
        </button>
      </div>

      {error && <p className="text-rose-400 mb-4">{error}</p>}

      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : items.length === 0 ? (
        <p className="text-slate-500 py-12 text-center">Никого не найдено</p>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
            {items.map((p) => (
              <Link
                key={p.id}
                href={`/player/${p.id}`}
                className="flex flex-col items-center rounded-xl border border-slate-700/80 bg-slate-900/40 p-4 hover:border-teal-500/40 hover:bg-slate-800/60 transition-colors"
              >
                <PlayerAvatar player={p} size="lg" className="mb-3" />
                <span className="text-white font-medium text-center line-clamp-2">
                  {p.name}
                </span>
                {p.country ? (
                  <span className="text-slate-500 text-xs mt-0.5">{p.country}</span>
                ) : null}
              </Link>
            ))}
          </div>

          <div className="flex justify-center gap-2 mt-6">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={!hasPrev}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
            >
              Назад
            </button>
            <span className="text-slate-500 text-sm py-1.5">
              Страница {page + 1}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => p + 1)}
              disabled={!hasMore}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-800"
            >
              Вперёд
            </button>
          </div>
        </>
      )}
    </main>
  );
}
