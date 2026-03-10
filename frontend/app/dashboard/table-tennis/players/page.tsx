"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTableTennisPlayers, type TableTennisPlayersPageResponse } from "@/lib/api";

export default function TableTennisPlayersPage() {
  const [data, setData] = useState<TableTennisPlayersPageResponse | null>(null);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 30;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisPlayers(page, pageSize, query)
      .then((res) => {
        if (!cancelled) setData(res);
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
  }, [page, query]);

  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (loading) {
    return (
      <div className="p-6 md:p-8">
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — игроки
        </h1>
        <p className="text-slate-400">Загрузка…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 md:p-8">
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — игроки
        </h1>
        <p className="text-rose-400">{error}</p>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8">
      <h1 className="font-display text-2xl font-bold text-white mb-2">
        Настольный теннис — игроки
      </h1>
      <p className="text-slate-400 text-sm mb-4">
        Удобный список игроков с поиском и пагинацией.
      </p>

      <div className="mb-4 flex flex-col md:flex-row gap-2">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setPage(1);
              setQuery(searchInput.trim());
            }
          }}
          placeholder="Поиск игрока"
          className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-3 py-2 text-slate-200 w-full md:max-w-md"
        />
        <button
          className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-4 py-2 text-white font-medium"
          onClick={() => {
            setPage(1);
            setQuery(searchInput.trim());
          }}
        >
          Найти
        </button>
      </div>

      {(data?.items?.length ?? 0) === 0 ? (
        <p className="text-slate-500">Игроки не найдены.</p>
      ) : (
        <div className="rounded-lg border border-slate-700 overflow-hidden bg-slate-800/40">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-700/50 text-slate-300 text-left">
                  <th className="px-4 py-3 font-medium">Игрок</th>
                  <th className="px-4 py-3 font-medium text-center">Всего матчей</th>
                  <th className="px-4 py-3 font-medium text-center">Завершено</th>
                  <th className="px-4 py-3 font-medium text-center">Предстоит</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((p) => (
                  <tr key={p.id} className="border-b border-slate-700/60 hover:bg-slate-700/30 transition">
                    <td className="px-4 py-3">
                      <Link
                        href={`/dashboard/table-tennis/players/${encodeURIComponent(p.id)}`}
                        className="text-white hover:text-emerald-300"
                      >
                        {p.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">{p.matches_total}</td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">{p.matches_finished}</td>
                    <td className="px-4 py-3 text-center tabular-nums text-slate-300">{p.matches_upcoming}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={page <= 1}
          onClick={() => setPage((v) => Math.max(1, v - 1))}
        >
          Назад
        </button>
        <span className="text-slate-400 text-sm">
          Страница {page} из {totalPages} · записей {total}
        </span>
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
          disabled={page >= totalPages}
          onClick={() => setPage((v) => Math.min(totalPages, v + 1))}
        >
          Вперёд
        </button>
      </div>
    </div>
  );
}
