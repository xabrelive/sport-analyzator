"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminUser,
  fetchSports,
  patchAdminUser,
  grantSubscriptionAdmin,
  type AdminUserDetail,
  type SportOption,
} from "@/lib/api";

function addDays(d: Date, days: number): string {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out.toISOString().slice(0, 10);
}

export default function AdminUserDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [sports, setSports] = useState<SportOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [trialUntil, setTrialUntil] = useState("");
  const [trialGrantSubs, setTrialGrantSubs] = useState(false);
  const [trialAddDays, setTrialAddDays] = useState(7);
  const [trialAddLoading, setTrialAddLoading] = useState(false);
  const [trialClearLoading, setTrialClearLoading] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [isBlocked, setIsBlocked] = useState(false);
  const [patchLoading, setPatchLoading] = useState(false);
  const [patchSuccess, setPatchSuccess] = useState(false);

  const [grantAccessType, setGrantAccessType] = useState<"tg_analytics" | "signals">("tg_analytics");
  const [grantScope, setGrantScope] = useState<"one_sport" | "all">("one_sport");
  const [grantSportKey, setGrantSportKey] = useState("");
  const [grantDays, setGrantDays] = useState(30);
  const [grantComment, setGrantComment] = useState("");
  const [grantLoading, setGrantLoading] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [u, s] = await Promise.all([fetchAdminUser(id), fetchSports()]);
      setUser(u);
      setSports(s);
      setTrialUntil(u.trial_until ? u.trial_until.slice(0, 10) : "");
      setIsAdmin(u.is_admin);
      setIsBlocked(u.is_blocked ?? false);
      if (s.length && !grantSportKey) setGrantSportKey(s[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const handlePatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setPatchLoading(true);
    setPatchSuccess(false);
    try {
      await patchAdminUser(id, {
        trial_until: trialUntil || null,
        grant_subscriptions_until_trial: trialGrantSubs,
        is_admin: isAdmin,
        is_blocked: isBlocked,
      });
      setPatchSuccess(true);
      setUser((prev) =>
        prev
          ? {
              ...prev,
              trial_until: trialUntil || null,
              is_admin: isAdmin,
              is_blocked: isBlocked,
            }
          : null,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setPatchLoading(false);
    }
  };

  const handleTrialAddDays = async () => {
    if (!id || trialAddDays < 1) return;
    setTrialAddLoading(true);
    setError(null);
    try {
      await patchAdminUser(id, {
        trial_add_days: trialAddDays,
        grant_subscriptions_until_trial: trialGrantSubs,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка продления триала");
    } finally {
      setTrialAddLoading(false);
    }
  };

  const handleTrialClear = async () => {
    if (!id) return;
    if (!confirm("Выключить триал для этого пользователя?")) return;
    setTrialClearLoading(true);
    setError(null);
    try {
      await patchAdminUser(id, { trial_clear: true });
      setTrialUntil("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setTrialClearLoading(false);
    }
  };

  const handleGrant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setGrantLoading(true);
    setGrantError(null);
    try {
      const validUntil = addDays(new Date(), grantDays);
      await grantSubscriptionAdmin({
        user_id: id,
        access_type: grantAccessType,
        scope: grantScope,
        sport_key: grantScope === "one_sport" ? grantSportKey || null : null,
        valid_until: validUntil,
        comment: grantComment.trim() || null,
      });
      setGrantComment("");
      await load();
    } catch (e) {
      setGrantError(e instanceof Error ? e.message : "Ошибка выдачи подписки");
    } finally {
      setGrantLoading(false);
    }
  };

  if (loading || !user) {
    return (
      <div>
        <Link href="/admin/users" className="text-teal-400 hover:text-teal-300 text-sm mb-4 inline-block">
          ← Пользователи
        </Link>
        {loading ? <p className="text-slate-400">Загрузка…</p> : error ? <p className="text-rose-400">{error}</p> : null}
      </div>
    );
  }

  return (
    <div>
      <Link href="/admin/users" className="text-teal-400 hover:text-teal-300 text-sm mb-4 inline-block">
        ← Пользователи
      </Link>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Профиль</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm">
          <dt className="text-slate-400">Email</dt>
          <dd className="text-white">{user.email || "—"}</dd>
          <dt className="text-slate-400">Telegram</dt>
          <dd className="text-white">{user.telegram_username ? `@${user.telegram_username}` : user.telegram_id || "—"}</dd>
          <dt className="text-slate-400">Последний вход</dt>
          <dd className="text-slate-300">{user.last_login_at ? new Date(user.last_login_at).toLocaleString("ru") : "—"}</dd>
          <dt className="text-slate-400">Создан</dt>
          <dd className="text-slate-300">{user.created_at ? new Date(user.created_at).toLocaleString("ru") : "—"}</dd>
          {user.is_blocked && (
            <>
              <dt className="text-slate-400">Статус</dt>
              <dd className="text-rose-400">Заблокирован</dd>
            </>
          )}
        </dl>

        <form onSubmit={handlePatch} className="mt-6 space-y-6">
          <div>
            <h3 className="text-sm font-medium text-slate-300 mb-3">Триал</h3>
            <p className="text-slate-400 text-xs mb-3">
              Укажите дату окончания триала или продлите на N дней. Действие «выдать подписки» создаёт аналитику и сигналы до даты триала (с суммированием).
            </p>
            <div className="flex flex-wrap gap-4 items-end">
              <label className="flex flex-col gap-1">
                <span className="text-slate-400 text-sm">Триал до</span>
                <input
                  type="date"
                  value={trialUntil}
                  onChange={(e) => setTrialUntil(e.target.value)}
                  className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white"
                />
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={trialGrantSubs}
                  onChange={(e) => setTrialGrantSubs(e.target.checked)}
                  className="rounded"
                />
                <span className="text-slate-400 text-sm whitespace-nowrap">Выдать подписки до даты триала</span>
              </label>
              <button type="submit" disabled={patchLoading} className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-50">
                {patchLoading ? "Сохранение…" : "Сохранить дату"}
              </button>
              <div className="flex items-center gap-2">
                <span className="text-slate-400 text-sm">Продлить на</span>
                <input
                  type="number"
                  min={1}
                  value={trialAddDays}
                  onChange={(e) => setTrialAddDays(parseInt(e.target.value, 10) || 7)}
                  className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white w-16"
                />
                <span className="text-slate-400 text-sm">дней</span>
                <button
                  type="button"
                  onClick={handleTrialAddDays}
                  disabled={trialAddLoading}
                  className="rounded-lg bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-600 disabled:opacity-50"
                >
                  {trialAddLoading ? "…" : "Продлить"}
                </button>
              </div>
              <button
                type="button"
                onClick={handleTrialClear}
                disabled={trialClearLoading || !user?.trial_until}
                className="rounded-lg bg-slate-700 px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {trialClearLoading ? "…" : "Выключить триал"}
              </button>
            </div>
            {user?.trial_until && (
              <p className="text-slate-500 text-xs mt-2">Сейчас триал до {new Date(user.trial_until).toLocaleDateString("ru")}</p>
            )}
          </div>
          <div>
            <h3 className="text-sm font-medium text-slate-300 mb-2">Права</h3>
            <div className="flex flex-wrap gap-4 items-center">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} className="rounded" />
                <span className="text-slate-400 text-sm">Админ</span>
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={isBlocked} onChange={(e) => setIsBlocked(e.target.checked)} className="rounded" />
                <span className="text-slate-400 text-sm">Заблокирован</span>
              </label>
              <button type="submit" disabled={patchLoading} className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 disabled:opacity-50">
                {patchLoading ? "Сохранение…" : "Сохранить"}
              </button>
            </div>
          </div>
          {patchSuccess && <span className="text-emerald-400 text-sm">Сохранено</span>}
        </form>
      </div>

      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Выдать подписку</h2>
        <form onSubmit={handleGrant} className="space-y-4">
          <div className="flex flex-wrap gap-4 items-center">
            <label className="flex items-center gap-2">
              <span className="text-slate-400 text-sm w-24">Тип</span>
              <select
                value={grantAccessType}
                onChange={(e) => setGrantAccessType(e.target.value as "tg_analytics" | "signals")}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white"
              >
                <option value="tg_analytics">Аналитика</option>
                <option value="signals">Сигналы</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              <span className="text-slate-400 text-sm w-24">Охват</span>
              <select
                value={grantScope}
                onChange={(e) => setGrantScope(e.target.value as "one_sport" | "all")}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white"
              >
                <option value="one_sport">Один вид</option>
                <option value="all">Все</option>
              </select>
            </label>
            {grantScope === "one_sport" && (
              <label className="flex items-center gap-2">
                <span className="text-slate-400 text-sm w-24">Вид спорта</span>
                <select
                  value={grantSportKey}
                  onChange={(e) => setGrantSportKey(e.target.value)}
                  className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white min-w-[120px]"
                >
                  {sports.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="flex items-center gap-2">
              <span className="text-slate-400 text-sm w-24">Дней</span>
              <input
                type="number"
                min={1}
                value={grantDays}
                onChange={(e) => setGrantDays(parseInt(e.target.value, 10) || 30)}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white w-20"
              />
            </label>
            <div className="w-full">
              <label className="block text-slate-400 text-sm mb-1">Комментарий (при выдаче через админку)</label>
              <textarea
                value={grantComment}
                onChange={(e) => setGrantComment(e.target.value)}
                placeholder="Например: оплата по счёту №123, безнал"
                rows={2}
                className="w-full max-w-md rounded border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-white placeholder-slate-500"
              />
            </div>
            <button type="submit" disabled={grantLoading} className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50">
              {grantLoading ? "Выдача…" : "Выдать подписку"}
            </button>
          </div>
          {grantError && <p className="text-rose-400 text-sm">{grantError}</p>}
        </form>
      </div>

      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Подписки</h2>
        {user.subscriptions.length === 0 ? (
          <p className="text-slate-400 text-sm">Нет активных подписок</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-left">
                  <th className="py-2 pr-4">Тип</th>
                  <th className="py-2 pr-4">Охват</th>
                  <th className="py-2 pr-4">Вид спорта</th>
                  <th className="py-2 pr-4">Действует до</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {user.subscriptions.map((s) => (
                  <tr key={s.id}>
                    <td className="py-2 pr-4">{s.access_type}</td>
                    <td className="py-2 pr-4">{s.scope}</td>
                    <td className="py-2 pr-4">{s.sport_key || "—"}</td>
                    <td className="py-2 pr-4">{new Date(s.valid_until).toLocaleDateString("ru")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">История пополнений</h2>
        <p className="text-slate-400 text-sm mb-4">Счета (оплаты) и выдачи подписок через поддержку.</p>
        {(user.invoices?.length ?? 0) === 0 && (user.subscription_grant_logs?.length ?? 0) === 0 ? (
          <p className="text-slate-500 text-sm">Нет записей</p>
        ) : (
          <div className="space-y-4">
            {user.invoices && user.invoices.length > 0 && (
              <div>
                <h3 className="text-slate-300 text-sm font-medium mb-2">Счета</h3>
                <ul className="space-y-2 text-sm">
                  {user.invoices.map((i) => (
                    <li key={i.id} className="flex flex-wrap items-center gap-2 text-slate-300">
                      <span>{i.amount} {i.currency}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${i.status === "paid" ? "bg-emerald-900/50 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                        {i.status === "paid" ? "Оплачен" : i.status}
                      </span>
                      <span className="text-slate-500">{i.created_at ? new Date(i.created_at).toLocaleString("ru") : ""}</span>
                      {i.paid_at && <span className="text-slate-500">оплачен {new Date(i.paid_at).toLocaleString("ru")}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {user.subscription_grant_logs && user.subscription_grant_logs.length > 0 && (
              <div>
                <h3 className="text-slate-300 text-sm font-medium mb-2">Выдачи через поддержку</h3>
                <ul className="space-y-2 text-sm">
                  {user.subscription_grant_logs.map((g) => (
                    <li key={g.id} className="text-slate-300">
                      {g.access_type === "tg_analytics" ? "Аналитика" : "Сигналы"} · до {new Date(g.valid_until).toLocaleDateString("ru")}
                      {g.scope === "one_sport" && g.sport_key && ` · ${g.sport_key}`}
                      {g.comment && <span className="text-slate-500 ml-2">— {g.comment}</span>}
                      <span className="text-slate-500 text-xs ml-2">{g.created_at ? new Date(g.created_at).toLocaleString("ru") : ""}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
