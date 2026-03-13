"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  deleteAdminSubscription,
  getAdminMe,
  getAdminUserSubscriptions,
  patchAdminUser,
  upsertAdminSubscription,
  type AdminSubscription,
} from "@/lib/api";

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params?.id || "";
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [subs, setSubs] = useState<AdminSubscription[]>([]);
  const [serviceKey, setServiceKey] = useState<"analytics" | "analytics_no_ml" | "vip_channel">("analytics");
  const [days, setDays] = useState(30);
  const [comment, setComment] = useState("");
  const [isBlocked, setIsBlocked] = useState(false);
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setError(null);
      await getAdminMe();
      setAllowed(true);
      const s = await getAdminUserSubscriptions(userId);
      setSubs(s.items);
    } catch (e) {
      setAllowed(false);
      setError(e instanceof Error ? e.message : "Нет доступа");
    }
  };

  useEffect(() => {
    if (!userId) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  if (allowed === null) return <div className="p-6 text-slate-400">Загрузка…</div>;
  if (!allowed) return <div className="p-6 text-rose-300">Нет доступа. {error || ""}</div>;

  return (
    <div className="p-4 md:p-6 space-y-6">
      <Link href="/dashboard/admin" className="text-sky-300 hover:text-sky-200 text-sm">
        ← Назад в админку
      </Link>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
        <h1 className="text-xl font-semibold text-white">Пользователь: {userId}</h1>
        <p className="text-sm text-slate-400">Быстрые действия по блокировке/активации и продлению подписок.</p>
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center gap-1 text-sm text-slate-300">
            <input type="checkbox" checked={!isBlocked} onChange={(e) => setIsBlocked(!e.target.checked)} />
            не заблокирован
          </label>
          <label className="flex items-center gap-1 text-sm text-slate-300">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            активен
          </label>
          <button
            type="button"
            onClick={async () => {
              await patchAdminUser(userId, { is_active: isActive, is_blocked: isBlocked });
              await load();
            }}
            className="rounded bg-sky-600 px-3 py-2 text-xs text-white hover:bg-sky-500"
          >
            Сохранить статус
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
        <h2 className="text-lg text-white">Продление подписки</h2>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-sm text-slate-300">
            Услуга
            <select
              value={serviceKey}
              onChange={(e) => setServiceKey(e.target.value as "analytics" | "analytics_no_ml" | "vip_channel")}
              className="mt-1 block rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            >
              <option value="analytics">Аналитика</option>
              <option value="vip_channel">ML (платный) канал</option>
              <option value="analytics_no_ml">NO_ML аналитика</option>
            </select>
          </label>
          <label className="text-sm text-slate-300">
            Дней
            <input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value || 1))}
              className="mt-1 block w-24 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            />
          </label>
          <label className="text-sm text-slate-300">
            Комментарий
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="mt-1 block w-80 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            />
          </label>
          <button
            type="button"
            onClick={async () => {
              await upsertAdminSubscription(userId, { service_key: serviceKey, days, comment });
              setComment("");
              await load();
            }}
            className="rounded bg-sky-600 px-3 py-2 text-sm text-white hover:bg-sky-500"
          >
            Продлить / выдать
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg text-white mb-3">История подписок</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-slate-300">
              <tr>
                <th className="text-left py-2 pr-3">Услуга</th>
                <th className="text-left py-2 pr-3">До</th>
                <th className="text-left py-2 pr-3">Источник</th>
                <th className="text-left py-2 pr-3">Комментарий</th>
                <th className="text-left py-2 pr-3"></th>
              </tr>
            </thead>
            <tbody className="text-slate-200">
              {subs.map((s) => (
                <tr key={s.id} className="border-t border-slate-800">
                  <td className="py-2 pr-3">{s.service_key}</td>
                  <td className="py-2 pr-3">{new Date(s.valid_until).toLocaleDateString("ru-RU")}</td>
                  <td className="py-2 pr-3">{s.source}</td>
                  <td className="py-2 pr-3">{s.comment || "—"}</td>
                  <td className="py-2 pr-3">
                    <button
                      type="button"
                      onClick={async () => {
                        await deleteAdminSubscription(userId, s.id);
                        await load();
                      }}
                      className="rounded border border-rose-700/60 px-2 py-1 text-xs text-rose-300 hover:bg-rose-950/40"
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
              {!subs.length ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-slate-500">
                    Подписок пока нет
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
