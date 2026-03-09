"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchAdminUsers, patchAdminUser, type AdminUserListItem } from "@/lib/api";

const PAGE_SIZE = 20;

export default function AdminUsersPage() {
  const [items, setItems] = useState<AdminUserListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [blockingId, setBlockingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminUsers({ offset, limit: PAGE_SIZE, q: q || undefined });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [offset, q]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setQ(searchInput.trim());
    setOffset(0);
  };

  const toggleBlock = async (u: AdminUserListItem) => {
    setError(null);
    setBlockingId(u.id);
    try {
      await patchAdminUser(u.id, { is_blocked: !u.is_blocked });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setBlockingId(null);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <h1 className="text-xl font-semibold text-white mb-6">Пользователи</h1>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Email или Telegram username"
          className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 w-64"
        />
        <button type="submit" className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">
          Поиск
        </button>
      </form>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      {loading ? (
        <p className="text-slate-400">Загрузка…</p>
      ) : (
        <>
          <div className="rounded-xl border border-slate-700/50 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-800/80 text-slate-300">
                <tr>
                  <th className="text-left py-3 px-4">Email</th>
                  <th className="text-left py-3 px-4">Telegram</th>
                  <th className="text-left py-3 px-4">Триал до</th>
                  <th className="text-left py-3 px-4">Админ</th>
                  <th className="text-left py-3 px-4">Блок</th>
                  <th className="text-left py-3 px-4">Последний вход</th>
                  <th className="text-left py-3 px-4">Создан</th>
                  <th className="text-left py-3 px-4"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                {items.map((u) => (
                  <tr key={u.id} className={`hover:bg-slate-800/40 ${u.is_blocked ? "opacity-75" : ""}`}>
                    <td className="py-3 px-4 text-white">{u.email || "—"}</td>
                    <td className="py-3 px-4 text-slate-300">
                      {u.telegram_username ? `@${u.telegram_username}` : u.telegram_id || "—"}
                    </td>
                    <td className="py-3 px-4 text-slate-300">{u.trial_until ? new Date(u.trial_until).toLocaleDateString("ru") : "—"}</td>
                    <td className="py-3 px-4">{u.is_admin ? "Да" : "—"}</td>
                    <td className="py-3 px-4">
                      <button
                        type="button"
                        onClick={() => toggleBlock(u)}
                        disabled={blockingId === u.id}
                        className={`rounded px-2 py-1 text-xs font-medium disabled:opacity-50 ${
                          u.is_blocked ? "bg-rose-900/50 text-rose-300 hover:bg-rose-800/50" : "bg-slate-700 text-slate-300 hover:bg-slate-600"
                        }`}
                      >
                        {blockingId === u.id ? "…" : u.is_blocked ? "Разблокировать" : "Заблокировать"}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-slate-400">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString("ru") : "—"}
                    </td>
                    <td className="py-3 px-4 text-slate-400">{u.created_at ? new Date(u.created_at).toLocaleString("ru") : "—"}</td>
                    <td className="py-3 px-4">
                      <Link href={`/admin/users/${u.id}`} className="text-teal-400 hover:text-teal-300">
                        Открыть
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {total > PAGE_SIZE && (
            <div className="flex items-center gap-4 mt-4 text-slate-400 text-sm">
              <span>
                {total} всего, стр. {currentPage} из {totalPages}
              </span>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                className="text-teal-400 hover:text-teal-300 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Назад
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                className="text-teal-400 hover:text-teal-300 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Вперёд
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
