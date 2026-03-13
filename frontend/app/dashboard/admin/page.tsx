"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  createAdminPaymentMethod,
  deleteAdminPaymentMethod,
  getAdminInvoices,
  getAdminMe,
  getAdminMlDashboard,
  getAdminMlProgress,
  getAdminMlStats,
  getAdminMlVerify,
  getAdminPaymentMethods,
  getAdminProducts,
  getAdminTelegramDispatchConfig,
  getAdminTelegramBotInfo,
  getAdminUsers,
  patchAdminInvoiceStatus,
  patchAdminPaymentMethod,
  patchAdminProduct,
  patchAdminUser,
  postAdminMlBackfillFeatures,
  postAdminMlFullRebuild,
  postAdminMlResetProgress,
  postAdminMlLoadArchive,
  postAdminMlPlayerStats,
  postAdminMlRetrain,
  postAdminMlSync,
  postAdminMlSyncLeagues,
  postAdminMlSyncPlayers,
  putAdminTelegramBotInfo,
  putAdminTelegramDispatchConfig,
  sendAdminMessage,
  type AdminInvoiceItem,
  type AdminMlDashboard,
  type AdminMlProgress,
  type AdminMlStats,
  type AdminPaymentMethod,
  type AdminProduct,
  type AdminUserListItem,
} from "@/lib/api";

function moneyCompact(v: number): string {
  const rounded = Math.round(v * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function MlProgressBar({
  op,
  label,
  progress,
}: {
  op: keyof AdminMlProgress;
  label: string;
  progress: AdminMlProgress[keyof AdminMlProgress] | null;
}) {
  if (!progress || progress.status === "idle") return null;
  const pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
  const isDone = progress.status === "done";
  const isErr = !!progress.error;
  return (
    <div className="mb-3 rounded-lg border border-slate-700 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="text-slate-300 font-medium">{label}</span>
        <span
          className={
            isErr
              ? "text-rose-400"
              : isDone
                ? "text-emerald-400"
                : "text-sky-400"
          }
        >
          {isErr ? progress.error : progress.message}
        </span>
      </div>
      {progress.status === "running" && (
        <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
          <div
            className="h-full bg-sky-500 transition-all duration-300"
            style={{ width: progress.total > 0 ? `${pct}%` : "30%" }}
          />
        </div>
      )}
      {isDone && progress.result && (
        <p className="text-xs text-slate-400 mt-1">
          {progress.result.synced != null ? `Синхронизировано: ${progress.result.synced}` : null}
          {progress.result.skipped != null ? `, пропущено: ${progress.result.skipped} (уже в ML)` : null}
          {progress.result.features_added != null ? `Добавлено фичей: ${progress.result.features_added}` : null}
          {progress.result.trained && progress.result.rows != null ? `Обучено: ${progress.result.rows} строк` : null}
          {progress.result.path ? ` → ${String(progress.result.path)}` : null}
          {progress.result.daily_stats != null ? `daily_stats: ${progress.result.daily_stats}` : null}
          {progress.result.style != null ? `, style: ${progress.result.style}` : null}
          {progress.result.elo_history != null ? `, elo_history: ${progress.result.elo_history}` : null}
        </p>
      )}
    </div>
  );
}

function LinkifiedText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  const tokenRe = /(https?:\/\/[^\s]+|t\.me\/[A-Za-z0-9_]+|@[A-Za-z0-9_]{3,})/g;
  return (
    <span className="whitespace-pre-wrap break-words">
      {lines.map((line, lineIdx) => (
        <span key={`line-${lineIdx}`}>
          {line.split(tokenRe).map((part, idx) => {
            if (!part) return null;
            if (/^https?:\/\//i.test(part)) {
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={part}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            if (/^t\.me\//i.test(part)) {
              const href = `https://${part}`;
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            if (/^@[A-Za-z0-9_]{3,}$/.test(part)) {
              const handle = part.slice(1);
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={`https://t.me/${handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            return <span key={`${lineIdx}-${idx}`}>{part}</span>;
          })}
          {lineIdx < lines.length - 1 ? "\n" : null}
        </span>
      ))}
    </span>
  );
}

function DispatchConfigPreview({ cfgText }: { cfgText: string }) {
  let cfg: Record<string, unknown> | null = null;
  try {
    cfg = cfgText.trim() ? (JSON.parse(cfgText) as Record<string, unknown>) : null;
  } catch {
    cfg = null;
  }
  if (!cfg) {
    return <p className="text-xs text-amber-300">JSON невалиден — предпросмотр недоступен.</p>;
  }
  const free = (cfg.free as Record<string, unknown> | undefined) || {};
  const vip = (cfg.vip as Record<string, unknown> | undefined) || {};
  const noMl = (cfg.no_ml_channel as Record<string, unknown> | undefined) || {};
  const slotsToText = (slotsRaw: unknown) => {
    const slots = Array.isArray(slotsRaw) ? slotsRaw : [];
    return slots
      .map((s) => {
        const it = (s as Record<string, unknown>) || {};
        const t = String(it.time_msk || "??:??");
        const src = String(it.source || "no_ml");
        const count = Number(it.count || 1);
        return `${t} · ${count} шт · source=${src}`;
      })
      .join(" | ");
  };
  return (
    <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300">
      <p className="font-medium text-slate-200 mb-2">Предпросмотр расписаний</p>
      <p>FREE: {Boolean(free.enabled ?? true) ? (slotsToText(free.slots) || "—") : "выключен"}</p>
      <p>PAID/ML: {Boolean(vip.enabled ?? true) ? (slotsToText(vip.slots) || "—") : "выключен"}</p>
      <p>
        NO_ML stream: {Boolean(noMl.enabled ?? true) ? (Boolean(noMl.stream_enabled ?? false) ? "включен" : "выключен") : "канал выключен"}, interval=
        {String(noMl.stream_interval_minutes ?? "30")}m, group_limit={String(noMl.stream_group_limit ?? "20")}, source=
        {String(noMl.stream_source ?? "no_ml")}
      </p>
      <p>
        Daily summary UTC: free={free.daily_summary_hour_utc == null ? "off" : String(free.daily_summary_hour_utc)}, paid=
        {vip.daily_summary_hour_utc == null ? "off" : String(vip.daily_summary_hour_utc)}, no_ml=
        {noMl.daily_summary_hour_utc == null ? "off" : String(noMl.daily_summary_hour_utc)}
      </p>
    </div>
  );
}

function DispatchConfigHelp() {
  return (
    <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300 space-y-2">
      <p className="font-medium text-slate-200">Подсказка по ключам расписания</p>
      <p>
        <span className="text-slate-100">Источники (`source`):</span> <code>no_ml</code> или <code>paid</code>.
      </p>
      <p>
        <span className="text-slate-100">Формат времени:</span> <code>time_msk</code> в виде <code>HH:MM</code> (MSK, 24ч), пример: <code>11:00</code>.
      </p>
      <p>
        <span className="text-slate-100">Общее:</span> <code>enabled</code> (boolean), <code>min_lead_minutes</code> (number),{" "}
        <code>daily_summary_hour_utc</code> (0-23 или <code>null</code> для выключения).
      </p>
      <p>
        <span className="text-slate-100">FREE / VIP:</span> обязательные ключи в слоте: <code>time_msk</code>, <code>source</code>,{" "}
        <code>count</code>.
      </p>
      <p>
        <span className="text-slate-100">NO_ML stream:</span> <code>stream_enabled</code> (boolean),{" "}
        <code>stream_interval_minutes</code> (&gt;=5), <code>stream_group_limit</code> (&gt;=1),{" "}
        <code>stream_fetch_limit</code> (&gt;=1), <code>stream_source</code> (<code>no_ml</code> | <code>paid</code>).
      </p>
      <p>
        <span className="text-slate-100">Минимально обязательная структура:</span> верхние ключи <code>free</code>, <code>vip</code>,{" "}
        <code>no_ml_channel</code>. Если ключ отсутствует, будут применены дефолты сервиса.
      </p>
    </div>
  );
}

export default function AdminPage() {
  type AdminTab =
    | "users"
    | "products"
    | "methods"
    | "invoices"
    | "ml"
    | "bot_info"
    | "schedules"
    | "messages";

  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AdminTab>("users");

  const [users, setUsers] = useState<AdminUserListItem[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersQ, setUsersQ] = useState("");
  const [usersOffset, setUsersOffset] = useState(0);

  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [methods, setMethods] = useState<AdminPaymentMethod[]>([]);
  const [invoices, setInvoices] = useState<AdminInvoiceItem[]>([]);
  const [invoicesTotal, setInvoicesTotal] = useState(0);
  const [invoicesStatus, setInvoicesStatus] = useState<"" | "pending" | "paid" | "cancelled">("pending");

  const [sending, setSending] = useState(false);
  const [messageTarget, setMessageTarget] = useState<"free_channel" | "vip_channel" | "no_ml_channel" | "telegram_user" | "telegram_all_users" | "email">("free_channel");
  const [messageText, setMessageText] = useState("");
  const [messageUserId, setMessageUserId] = useState("");
  const [messageEmail, setMessageEmail] = useState("");
  const [messageSubject, setMessageSubject] = useState("Сообщение от PingWin");
  const [messageImageUrl, setMessageImageUrl] = useState("");
  const [messageImageUrls, setMessageImageUrls] = useState("");
  const [messageResult, setMessageResult] = useState<string>("");

  const [newMethodName, setNewMethodName] = useState("");
  const [newMethodType, setNewMethodType] = useState<"custom" | "card" | "crypto">("custom");
  const [newMethodInstructions, setNewMethodInstructions] = useState("");

  const [botInfoMessage, setBotInfoMessage] = useState("");
  const [botInfoSaving, setBotInfoSaving] = useState(false);
  const [dispatchCfgText, setDispatchCfgText] = useState("");
  const [dispatchCfgSaving, setDispatchCfgSaving] = useState(false);

  const [mlStats, setMlStats] = useState<AdminMlStats | null>(null);
  const [mlDashboard, setMlDashboard] = useState<AdminMlDashboard | null>(null);
  const [mlSyncLimit, setMlSyncLimit] = useState(5000);
  const [mlSyncDaysBack, setMlSyncDaysBack] = useState(0);
  const [mlSyncFull, setMlSyncFull] = useState(true);
  const [mlSyncResult, setMlSyncResult] = useState<string | null>(null);
  const [mlBackfillLimit, setMlBackfillLimit] = useState(10000);
  const [mlBackfillResult, setMlBackfillResult] = useState<string | null>(null);
  const [mlRetrainMinRows, setMlRetrainMinRows] = useState(100);
  const [mlRetrainResult, setMlRetrainResult] = useState<string | null>(null);
  const [mlSyncPlayersLoading, setMlSyncPlayersLoading] = useState(false);
  const [mlSyncPlayersResult, setMlSyncPlayersResult] = useState<string | null>(null);
  const [mlVerify, setMlVerify] = useState<{
    main: { matches: number; players: number; leagues: number };
    ml: { matches: number; players: number; leagues: number };
    diff: { matches: number; players: number; leagues: number };
    ok: boolean;
    message: string;
  } | null>(null);
  const [mlProgress, setMlProgress] = useState<AdminMlProgress | null>(null);

  const pageSize = 20;
  const totalPages = useMemo(() => Math.max(1, Math.ceil(usersTotal / pageSize)), [usersTotal]);
  const currentPage = useMemo(() => Math.floor(usersOffset / pageSize) + 1, [usersOffset]);

  const dispatchCfgObj = useMemo<Record<string, unknown> | null>(() => {
    try {
      return dispatchCfgText.trim() ? (JSON.parse(dispatchCfgText) as Record<string, unknown>) : {};
    } catch {
      return null;
    }
  }, [dispatchCfgText]);

  const updateDispatchCfg = (updater: (cfg: Record<string, unknown>) => void) => {
    const base = dispatchCfgObj && typeof dispatchCfgObj === "object" ? dispatchCfgObj : {};
    const clone = JSON.parse(JSON.stringify(base)) as Record<string, unknown>;
    updater(clone);
    setDispatchCfgText(JSON.stringify(clone, null, 2));
  };

  const loadUsers = async () => {
    const data = await getAdminUsers({ q: usersQ, offset: usersOffset, limit: pageSize });
    setUsers(data.items);
    setUsersTotal(data.total);
  };

  const loadAll = async () => {
    try {
      setError(null);
      await getAdminMe();
      setAllowed(true);
      await Promise.all([
        loadUsers(),
        getAdminProducts().then(setProducts),
        getAdminPaymentMethods().then(setMethods),
        getAdminInvoices({ status: invoicesStatus, limit: 50, offset: 0 }).then((r) => {
          setInvoices(r.items);
          setInvoicesTotal(r.total);
        }),
        getAdminTelegramBotInfo().then((r) => setBotInfoMessage(r.message || "")),
        getAdminTelegramDispatchConfig().then((r) => setDispatchCfgText(JSON.stringify(r.config || {}, null, 2))),
        getAdminMlStats().then(setMlStats).catch(() => setMlStats(null)),
        getAdminMlDashboard().then(setMlDashboard).catch(() => setMlDashboard(null)),
      ]);
    } catch (e) {
      setAllowed(false);
      setError(e instanceof Error ? e.message : "Нет доступа");
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (allowed) void loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usersOffset]);

  useEffect(() => {
    if (!allowed) return;
    void getAdminInvoices({ status: invoicesStatus, limit: 50, offset: 0 }).then((r) => {
      setInvoices(r.items);
      setInvoicesTotal(r.total);
    });
  }, [allowed, invoicesStatus]);

  useEffect(() => {
    if (typeof window !== "undefined" && window.location.hash === "#admin-ml") {
      document.getElementById("admin-ml")?.scrollIntoView({ behavior: "smooth" });
    }
  }, [allowed]);

  useEffect(() => {
    if (!allowed) return;
    const poll = async () => {
      const [dashboard, stats] = await Promise.all([
        getAdminMlDashboard().catch(() => null),
        getAdminMlStats().catch(() => null),
      ]);
      if (dashboard) {
        setMlDashboard(dashboard);
        setMlProgress(dashboard.progress);
      }
      if (stats) setMlStats(stats);
    };
    poll();
    const id = setInterval(poll, 2500);
    return () => clearInterval(id);
  }, [allowed]);

  if (allowed === null) {
    return <div className="p-6 text-slate-400">Загрузка админки…</div>;
  }
  if (!allowed) {
    return <div className="p-6 text-rose-300">Доступ запрещён. {error || ""}</div>;
  }

  const tabBtn = (tab: AdminTab, label: string) => (
    <button
      type="button"
      onClick={() => setActiveTab(tab)}
      className={`w-full rounded px-3 py-2 text-left text-sm border ${
        activeTab === tab
          ? "border-sky-500/50 bg-sky-500/20 text-sky-100"
          : "border-slate-700 text-slate-300 hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="p-4 md:p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-white">Админка</h1>
        <p className="text-slate-400 mt-1">Управление пользователями, подписками, тарифами, платежами и рассылками.</p>
      </div>
      <div className="grid gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="h-fit rounded-xl border border-slate-800 bg-slate-900/40 p-3 space-y-2 md:sticky md:top-4">
          {tabBtn("users", "Пользователи")}
          {tabBtn("products", "Тарифы")}
          {tabBtn("methods", "Платежки")}
          {tabBtn("invoices", "Инвойсы")}
          {tabBtn("ml", "ML")}
          {tabBtn("bot_info", "Бот: инфо")}
          {tabBtn("schedules", "Боты: расписания")}
          {tabBtn("messages", "Рассылки")}
        </aside>
        <div className="space-y-8">

      <section className={`${activeTab === "users" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Пользователи</h2>
        <div className="flex flex-wrap gap-2 mb-3">
          <input
            value={usersQ}
            onChange={(e) => setUsersQ(e.target.value)}
            placeholder="Поиск по email / username / notification email"
            className="w-full md:w-96 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
          <button
            type="button"
            onClick={() => {
              setUsersOffset(0);
              void loadUsers();
            }}
            className="rounded bg-sky-600 px-3 py-2 text-sm text-white hover:bg-sky-500"
          >
            Найти
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-slate-300">
              <tr>
                <th className="text-left py-2 pr-3">Email</th>
                <th className="text-left py-2 pr-3">Telegram</th>
                <th className="text-left py-2 pr-3">Статус</th>
                <th className="text-left py-2 pr-3">Права</th>
                <th className="text-left py-2 pr-3"></th>
              </tr>
            </thead>
            <tbody className="text-slate-200">
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-800">
                  <td className="py-2 pr-3">{u.email}</td>
                  <td className="py-2 pr-3">{u.telegram_username ? `@${u.telegram_username}` : u.telegram_id || "—"}</td>
                  <td className="py-2 pr-3">
                    {!u.is_active ? "деактивирован" : u.is_blocked ? "заблокирован" : "активен"}
                  </td>
                  <td className="py-2 pr-3">{u.is_superadmin ? "superadmin" : "user"}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <Link className="text-sky-300 hover:text-sky-200" href={`/dashboard/admin/users/${u.id}`}>
                        Открыть
                      </Link>
                      <button
                        type="button"
                        onClick={async () => {
                          await patchAdminUser(u.id, { is_blocked: !u.is_blocked });
                          await loadUsers();
                        }}
                        className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
                      >
                        {u.is_blocked ? "Разблок" : "Блок"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center gap-3 text-sm text-slate-400">
          <span>Стр. {currentPage}/{totalPages}</span>
          <button
            type="button"
            disabled={usersOffset === 0}
            onClick={() => setUsersOffset((v) => Math.max(0, v - pageSize))}
            className="disabled:opacity-40"
          >
            Назад
          </button>
          <button
            type="button"
            disabled={usersOffset + pageSize >= usersTotal}
            onClick={() => setUsersOffset((v) => v + pageSize)}
            className="disabled:opacity-40"
          >
            Вперёд
          </button>
        </div>
      </section>

      <section className={`${activeTab === "products" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Тарифы (биллинг)</h2>
        <div className="space-y-2">
          {products.map((p) => (
            <div key={p.id} className="flex flex-wrap items-center gap-2 rounded border border-slate-800 p-2">
              <span className="min-w-44 text-slate-300">
                {p.name} — {moneyCompact(p.price_rub)} RUB / {moneyCompact(p.price_usd)} USD
              </span>
              <span className="text-slate-500 text-xs">{p.code}</span>
              <span className="text-[11px] text-slate-500">RUB</span>
              <input
                type="number"
                value={p.price_rub}
                onChange={(e) => {
                  const val = Number(e.target.value || 0);
                  setProducts((prev) => prev.map((x) => (x.id === p.id ? { ...x, price_rub: val } : x)));
                }}
                className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
              />
              <span className="text-[11px] text-slate-500">USD</span>
              <input
                type="number"
                step="0.01"
                value={p.price_usd}
                onChange={(e) => {
                  const val = Number(e.target.value || 0);
                  setProducts((prev) => prev.map((x) => (x.id === p.id ? { ...x, price_usd: val } : x)));
                }}
                className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
              />
              <label className="flex items-center gap-1 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={p.enabled}
                  onChange={(e) => setProducts((prev) => prev.map((x) => (x.id === p.id ? { ...x, enabled: e.target.checked } : x)))}
                />
                активен
              </label>
              <button
                type="button"
                onClick={async () => {
                  await patchAdminProduct(p.id, { price_rub: p.price_rub, price_usd: p.price_usd, enabled: p.enabled });
                  await getAdminProducts().then(setProducts);
                }}
                className="rounded bg-sky-600 px-2 py-1 text-xs text-white hover:bg-sky-500"
              >
                Сохранить
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className={`${activeTab === "methods" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Платёжки</h2>
        <div className="grid gap-2 md:grid-cols-[1fr_140px_1fr_auto] mb-4">
          <input value={newMethodName} onChange={(e) => setNewMethodName(e.target.value)} placeholder="Название (например: Безналичная оплата)" className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
          <select value={newMethodType} onChange={(e) => setNewMethodType(e.target.value as "custom" | "card" | "crypto")} className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
            <option value="custom">custom</option>
            <option value="card">card</option>
            <option value="crypto">crypto</option>
          </select>
          <textarea value={newMethodInstructions} onChange={(e) => setNewMethodInstructions(e.target.value)} placeholder="Сообщение для пользователя: как и куда оплатить (можно @telegram, t.me/..., https://...)" rows={2} className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
          <button
            type="button"
            onClick={async () => {
              if (!newMethodName.trim()) return;
              await createAdminPaymentMethod({
                name: newMethodName.trim(),
                method_type: newMethodType,
                instructions: newMethodInstructions.trim() || null,
              });
              setNewMethodName("");
              setNewMethodInstructions("");
              await getAdminPaymentMethods().then(setMethods);
            }}
            className="rounded bg-sky-600 px-3 py-2 text-sm text-white hover:bg-sky-500"
          >
            Добавить
          </button>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Этот текст увидит пользователь в модалке создания инвойса. Ссылки и @username будут кликабельными.
        </p>
        <div className="space-y-2">
          {methods.map((m) => (
            <div key={m.id} className="rounded border border-slate-800 p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-44 text-slate-200">{m.name}</span>
              <span className="text-xs text-slate-500">{m.method_type}</span>
              <label className="flex items-center gap-1 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={m.enabled}
                  onChange={(e) => setMethods((prev) => prev.map((x) => (x.id === m.id ? { ...x, enabled: e.target.checked } : x)))}
                />
                включен
              </label>
              <button
                type="button"
                onClick={async () => {
                  await patchAdminPaymentMethod(m.id, {
                    enabled: m.enabled,
                    instructions: m.instructions ?? "",
                  });
                  await getAdminPaymentMethods().then(setMethods);
                }}
                className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
              >
                Сохранить
              </button>
              <button
                type="button"
                onClick={async () => {
                  await deleteAdminPaymentMethod(m.id);
                  await getAdminPaymentMethods().then(setMethods);
                }}
                className="rounded border border-rose-700/60 px-2 py-1 text-xs text-rose-300 hover:bg-rose-950/40"
              >
                Удалить
              </button>
              </div>
              <textarea
                value={m.instructions || ""}
                onChange={(e) =>
                  setMethods((prev) =>
                    prev.map((x) => (x.id === m.id ? { ...x, instructions: e.target.value } : x))
                  )
                }
                rows={3}
                placeholder="Сообщение для пользователя по оплате"
                className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white"
              />
              {m.instructions ? (
                <div className="text-xs text-slate-400">
                  <span className="text-slate-500">Предпросмотр: </span>
                  <LinkifiedText text={m.instructions} />
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className={`${activeTab === "invoices" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Инвойсы</h2>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {[
            { id: "pending", label: "Ожидают" },
            { id: "paid", label: "Оплачены" },
            { id: "cancelled", label: "Отклонены" },
            { id: "", label: "Все" },
          ].map((s) => (
            <button
              key={s.id || "all"}
              type="button"
              onClick={() => setInvoicesStatus(s.id as "" | "pending" | "paid" | "cancelled")}
              className={`rounded px-2.5 py-1 text-xs border ${
                invoicesStatus === s.id
                  ? "border-sky-500/50 bg-sky-500/20 text-sky-100"
                  : "border-slate-700 text-slate-300 hover:bg-slate-800"
              }`}
            >
              {s.label}
            </button>
          ))}
          <span className="text-xs text-slate-500">Всего: {invoicesTotal}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-slate-300">
              <tr>
                <th className="text-left py-2 pr-3">Дата</th>
                <th className="text-left py-2 pr-3">Пользователь</th>
                <th className="text-left py-2 pr-3">Сумма</th>
                <th className="text-left py-2 pr-3">Статус</th>
                <th className="text-left py-2 pr-3">Действия</th>
              </tr>
            </thead>
            <tbody className="text-slate-200">
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-t border-slate-800">
                  <td className="py-2 pr-3">{inv.created_at ? new Date(inv.created_at).toLocaleString("ru-RU") : "—"}</td>
                  <td className="py-2 pr-3">{inv.user_email}</td>
                  <td className="py-2 pr-3">{inv.amount_rub.toFixed(2)} RUB</td>
                  <td className="py-2 pr-3">
                    {inv.status === "paid" ? "оплачен" : inv.status === "cancelled" ? "отклонён" : "ожидает"}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={inv.status === "paid"}
                        onClick={async () => {
                          await patchAdminInvoiceStatus(inv.id, true);
                          const r = await getAdminInvoices({ status: invoicesStatus, limit: 50, offset: 0 });
                          setInvoices(r.items);
                          setInvoicesTotal(r.total);
                        }}
                        className="rounded border border-emerald-700/60 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-40"
                      >
                        Оплачен
                      </button>
                      <button
                        type="button"
                        disabled={inv.status === "cancelled"}
                        onClick={async () => {
                          await patchAdminInvoiceStatus(inv.id, false);
                          const r = await getAdminInvoices({ status: invoicesStatus, limit: 50, offset: 0 });
                          setInvoices(r.items);
                          setInvoicesTotal(r.total);
                        }}
                        className="rounded border border-rose-700/60 px-2 py-1 text-xs text-rose-300 hover:bg-rose-950/40 disabled:opacity-40"
                      >
                        Отклонить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={`${activeTab === "ml" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">ML-база (pingwin_ml)</h2>
        <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-3 mb-4 text-sm text-slate-300 space-y-2">
          <p className="font-medium text-slate-200">Два источника заполнения:</p>
          <ol className="list-decimal list-inside space-y-1 text-xs">
            <li><strong>ml_sync_loop</strong> (в tt_workers, каждые ~60 сек) — лиги, игроки, матчи main→ML, duration, features, player_daily_stats, player_style, player_elo_history, league_performance.</li>
            <li><strong>ml_worker</strong> (отдельный контейнер) — обрабатывает очередь задач. Убедитесь, что <code className="text-slate-400">docker compose up ml_worker</code> запущен.</li>
          </ol>
          <p className="font-medium text-slate-200 mt-2">Ручные действия:</p>
          <ol className="list-decimal list-inside space-y-1 text-xs">
            <li><strong>Синхр. лиг / игроков</strong> — выполняется сразу (не в очереди).</li>
            <li><strong>«Все матчи»</strong> — полная синхронизация main→ML (идёт в очередь ml_worker). После reset — обязательно запустите.</li>
            <li><strong>Backfill фичей</strong> — Elo, форма, H2H для матчей без фичей.</li>
            <li><strong>Player stats</strong> — player_daily_stats, player_style, player_elo_history.</li>
            <li><strong>Переобучить</strong> — XGBoost (min_rows 500).</li>
          </ol>
          <p className="text-xs text-slate-500 mt-2">Очередь ml_worker: {mlDashboard?.queue_size ?? 0} задач</p>
        </div>
        {mlDashboard && !mlDashboard.sync_ok && mlDashboard.diff.matches > 0 && (
          <div className="rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200 mb-4">
            <strong>ML-база не синхронизирована.</strong> Нажмите «Все матчи» для полной загрузки main→ML. Убедитесь, что ml_worker запущен.
          </div>
        )}
        {mlDashboard && (
          <div className="grid gap-4 mb-4 md:grid-cols-2">
            <div className={`rounded-lg border px-3 py-2 text-sm ${mlDashboard.sync_ok ? "border-emerald-700/50 bg-emerald-950/30" : "border-amber-700/50 bg-amber-950/30"}`}>
              <p className="font-medium text-slate-200 mb-2">Сравнение main → ML</p>
              <table className="text-xs w-full">
                <thead>
                  <tr className="text-slate-400">
                    <th className="text-left">Таблица</th>
                    <th className="text-right">Main</th>
                    <th className="text-right">ML</th>
                    <th className="text-right">Разница</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  <tr><td className="py-0.5">Матчи</td><td className="text-right">{mlDashboard.main.matches.toLocaleString()}</td><td className="text-right">{mlDashboard.tables.matches?.toLocaleString() ?? 0}</td><td className={`text-right ${mlDashboard.diff.matches > 0 ? "text-amber-400" : ""}`}>{mlDashboard.diff.matches >= 0 ? `+${mlDashboard.diff.matches}` : mlDashboard.diff.matches}</td></tr>
                  <tr><td className="py-0.5">Игроки</td><td className="text-right">{mlDashboard.main.players.toLocaleString()}</td><td className="text-right">{mlDashboard.tables.players?.toLocaleString() ?? 0}</td><td className={`text-right ${mlDashboard.diff.players > 0 ? "text-amber-400" : ""}`}>{mlDashboard.diff.players >= 0 ? `+${mlDashboard.diff.players}` : mlDashboard.diff.players}</td></tr>
                  <tr><td className="py-0.5">Лиги</td><td className="text-right">{mlDashboard.main.leagues.toLocaleString()}</td><td className="text-right">{mlDashboard.tables.leagues?.toLocaleString() ?? 0}</td><td className={`text-right ${mlDashboard.diff.leagues > 0 ? "text-amber-400" : ""}`}>{mlDashboard.diff.leagues >= 0 ? `+${mlDashboard.diff.leagues}` : mlDashboard.diff.leagues}</td></tr>
                </tbody>
              </table>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm">
              <p className="font-medium text-slate-200 mb-2">Наполнение таблиц</p>
              <table className="text-xs w-full">
                <thead>
                  <tr className="text-slate-400">
                    <th className="text-left">Таблица</th>
                    <th className="text-right">Записей</th>
                    <th className="text-right">Заполнено</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  {["matches", "match_features", "match_sets", "odds", "players", "player_ratings", "player_daily_stats", "player_style", "player_elo_history", "suspicious_matches", "league_performance"].map((t) => (
                    <tr key={t}>
                      <td className="py-0.5">{t}</td>
                      <td className="text-right">{(mlDashboard.tables[t] ?? 0).toLocaleString()}</td>
                      <td className="text-right">
                        {t === "match_features" || t === "odds" || t === "player_ratings" || t === "player_style"
                          ? `${mlDashboard.fill_pct[t] ?? 0}%`
                          : t === "player_daily_stats" || t === "player_elo_history"
                            ? (mlDashboard.fill_pct[t] ?? 0).toLocaleString()
                            : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {mlStats && (
            <span className="text-slate-300 text-sm">
              Матчей: {mlStats.matches.toLocaleString()}, с фичами: {mlStats.match_features.toLocaleString()}
              {mlStats.players != null ? `, игроков: ${mlStats.players.toLocaleString()}` : ""}
              {mlStats.leagues != null ? `, лиг: ${mlStats.leagues.toLocaleString()}` : ""}
            </span>
          )}
          <button
            type="button"
            onClick={async () => {
              try {
                setMlSyncPlayersResult(null);
                const r = await postAdminMlSyncLeagues();
                setMlSyncPlayersResult(`Лиги: ${r.total}, добавлено: ${r.added}`);
              } catch (e) {
                setMlSyncPlayersResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800"
            title="Скопировать справочник лиг из основной БД в ML. Выполняется сразу (не в очереди)."
          >
            Синхр. лиг
          </button>
          <button
            type="button"
            disabled={mlSyncPlayersLoading}
            onClick={async () => {
              try {
                setMlSyncPlayersLoading(true);
                setMlSyncPlayersResult(null);
                const r = await postAdminMlSyncPlayers();
                setMlSyncPlayersResult(`Игроков: ${r.total}, добавлено: ${r.added}`);
              } catch (e) {
                setMlSyncPlayersResult(e instanceof Error ? e.message : "Ошибка");
              } finally {
                setMlSyncPlayersLoading(false);
              }
            }}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 disabled:opacity-50"
            title="Скопировать всех игроков из основной БД в ML. Выполняется сразу."
          >
            {mlSyncPlayersLoading ? "Синхр. игроков…" : "Синхр. игроков"}
          </button>
          <button
            type="button"
            onClick={async () => {
              try {
                const [stats, dashboard] = await Promise.all([
                  getAdminMlStats().catch(() => null),
                  getAdminMlDashboard().catch(() => null),
                ]);
                if (stats) setMlStats(stats);
                if (dashboard) {
                  setMlDashboard(dashboard);
                  setMlProgress(dashboard.progress);
                }
                setMlVerify(await getAdminMlVerify().catch(() => null));
              } catch {
                // ignore
              }
            }}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800"
            title="Обновить счётчики, таблицы и сравнение main→ML."
          >
            Обновить
          </button>
          <button
            type="button"
            onClick={() => getAdminMlVerify().then(setMlVerify).catch(() => setMlVerify(null))}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800"
            title="Сравнить main и ML: сколько матчей/игроков/лиг не хватает в ML."
          >
            Проверить main→ML
          </button>
          <button
            type="button"
            onClick={async () => {
              try {
                await postAdminMlResetProgress();
                const d = await getAdminMlDashboard().catch(() => null);
                if (d) {
                  setMlDashboard(d);
                  setMlProgress(d.progress);
                }
              } catch {
                // ignore
              }
            }}
            className="rounded border border-amber-600/60 px-2 py-1 text-xs text-amber-300 hover:bg-amber-950/40"
            title="Сбросить зависший прогресс (retrain/sync в статусе running)."
          >
            Сбросить прогресс
          </button>
          {mlSyncPlayersResult && <span className="text-xs text-slate-400">{mlSyncPlayersResult}</span>}
        </div>
        {mlVerify && (
        <div className={`rounded-lg border px-3 py-2 text-sm mb-3 ${mlVerify.ok ? "border-emerald-700/50 bg-emerald-950/30 text-emerald-200" : "border-amber-700/50 bg-amber-950/30 text-amber-200"}`}>
          <p className="font-medium">{mlVerify.message}</p>
          <table className="text-xs mt-1 text-slate-300">
            <thead>
              <tr>
                <th className="text-left pr-4">Сущность</th>
                <th className="text-left pr-4">Main DB</th>
                <th className="text-left pr-4">ML DB</th>
                <th className="text-left">Разница</th>
              </tr>
            </thead>
            <tbody>
              <tr><td className="pr-4">Матчи</td><td className="pr-4">{mlVerify.main.matches.toLocaleString()}</td><td className="pr-4">{mlVerify.ml.matches.toLocaleString()}</td><td>{mlVerify.diff.matches >= 0 ? `+${mlVerify.diff.matches}` : mlVerify.diff.matches}</td></tr>
              <tr><td className="pr-4">Игроки</td><td className="pr-4">{mlVerify.main.players.toLocaleString()}</td><td className="pr-4">{mlVerify.ml.players.toLocaleString()}</td><td>{mlVerify.diff.players >= 0 ? `+${mlVerify.diff.players}` : mlVerify.diff.players}</td></tr>
              <tr><td className="pr-4">Лиги</td><td className="pr-4">{mlVerify.main.leagues.toLocaleString()}</td><td className="pr-4">{mlVerify.ml.leagues.toLocaleString()}</td><td>{mlVerify.diff.leagues >= 0 ? `+${mlVerify.diff.leagues}` : mlVerify.diff.leagues}</td></tr>
            </tbody>
          </table>
        </div>
        )}
        <MlProgressBar op="full_rebuild" label="Full rebuild (всё за раз)" progress={mlProgress?.full_rebuild ?? null} />
        <MlProgressBar op="sync" label="Синхронизация" progress={mlProgress?.sync ?? null} />
        <MlProgressBar op="backfill" label="Backfill фичей" progress={mlProgress?.backfill ?? null} />
        <MlProgressBar op="player_stats" label="Player stats (daily, style, elo_history)" progress={mlProgress?.player_stats ?? null} />
        <MlProgressBar op="league_performance" label="League performance" progress={mlProgress?.league_performance ?? null} />
        <MlProgressBar op="retrain" label="Переобучение моделей" progress={mlProgress?.retrain ?? null} />
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={async () => {
                try {
                  setMlSyncResult(null);
                  const r = await postAdminMlLoadArchive({ days: 90 });
                  if (!r.ok) setMlSyncResult("Ошибка");
                  else {
                    setMlSyncResult(`Архив: добавлено ${r.inserted ?? 0}, обновлено ${r.updated ?? 0}`);
                    await getAdminMlVerify().then(setMlVerify).catch(() => {});
                  }
                } catch (e) {
                  setMlSyncResult(e instanceof Error ? e.message : "Ошибка");
                }
              }}
              className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500"
              title="Загрузить завершённые матчи из архива BetsAPI в main DB. Нужно при пустых таблицах."
            >
              Load archive
            </button>
            <button
              type="button"
              disabled={(mlProgress?.full_rebuild?.status ?? mlProgress?.sync?.status) === "running"}
              onClick={async () => {
                try {
                  setMlSyncResult(null);
                  const r = await postAdminMlFullRebuild({
                    sync_limit: 100000,
                    backfill_limit: 150000,
                    player_stats_limit: 100000,
                    league_limit: 100000,
                    min_rows: 500,
                  });
                  if (!r.ok) setMlSyncResult(r.error ?? "Ошибка");
                  else {
                    setMlSyncResult("Full rebuild в очереди (3–10 мин)");
                    await getAdminMlStats().then(setMlStats).catch(() => {});
                    await getAdminMlDashboard().then(setMlDashboard).catch(() => {});
                  }
                } catch (e) {
                  setMlSyncResult(e instanceof Error ? e.message : "Ошибка");
                }
              }}
              className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              title="Полный цикл: sync → backfill → player_stats → league_performance → retrain. Рекомендуется после reset."
            >
              {(mlProgress?.full_rebuild?.status ?? "") === "running" ? "Full rebuild…" : "Full rebuild"}
            </button>
            <button
              type="button"
              disabled={mlProgress?.sync?.status === "running"}
              onClick={async () => {
                try {
                  setMlSyncResult(null);
                  const r = await postAdminMlSync({ limit: 50000, days_back: 0, full: true });
                  if (!r.ok) setMlSyncResult(r.error ?? "Ошибка");
                  else {
                    setMlSyncResult("Задача добавлена в очередь");
                    await getAdminMlStats().then(setMlStats).catch(() => {});
                  }
                } catch (e) {
                  setMlSyncResult(e instanceof Error ? e.message : "Ошибка");
                }
              }}
              className="rounded bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
              title="Синхронизировать весь архив матчей из основной БД в ML. Используйте при первом запуске или после долгого простоя."
            >
              {mlProgress?.sync?.status === "running" ? "Синхронизация…" : "Все матчи"}
            </button>
            <span className="text-xs text-slate-500">или настройте параметры ниже:</span>
          </div>
          <div className="flex flex-wrap items-center gap-2 w-full">
            <label className="text-sm text-slate-300" title="Максимум матчей за один запуск. При полной синхронизации — размер батча.">
              limit
              <input
                type="number"
                value={mlSyncLimit}
                onChange={(e) => setMlSyncLimit(Number(e.target.value) || 5000)}
                min={100}
                max={50000}
                className="ml-1 w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
              />
            </label>
            <label className="text-sm text-slate-300" title="Брать матчи за последние N дней. 0 = весь архив без ограничения.">
              days_back (0=весь архив)
              <input
                type="number"
                value={mlSyncDaysBack}
                onChange={(e) => setMlSyncDaysBack(Number(e.target.value) || 0)}
                min={0}
                max={36500}
                className="ml-1 w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
              />
            </label>
            <label className="flex items-center gap-1 text-sm text-slate-300" title="Полная синхронизация: батчами до исчерпания. Без галочки — один батч (limit матчей).">
              <input type="checkbox" checked={mlSyncFull} onChange={(e) => setMlSyncFull(e.target.checked)} />
              полная синхронизация
            </label>
            <button
              type="button"
              disabled={mlProgress?.sync?.status === "running"}
              onClick={async () => {
                try {
                  setMlSyncResult(null);
                  const r = await postAdminMlSync({
                    limit: mlSyncLimit,
                    days_back: mlSyncDaysBack,
                    full: mlSyncFull,
                  });
                  if (!r.ok) setMlSyncResult(r.error ?? "Ошибка");
                  else {
                    setMlSyncResult("Задача добавлена в очередь");
                    await getAdminMlStats().then(setMlStats).catch(() => {});
                  }
                } catch (e) {
                  setMlSyncResult(e instanceof Error ? e.message : "Ошибка");
                }
              }}
              className="rounded bg-sky-600/80 px-3 py-2 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {mlProgress?.sync?.status === "running" ? "Синхронизация…" : "Синхронизировать"}
            </button>
          </div>
        </div>
        {mlSyncResult && <p className="text-sm text-slate-300 mb-3">{mlSyncResult}</p>}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <label className="text-sm text-slate-300" title="Рассчитать фичи (Elo, форма, усталость, H2H) для матчей, у которых их ещё нет. Limit — макс. матчей за запуск.">
            Backfill фичей limit
            <input
              type="number"
              value={mlBackfillLimit}
              onChange={(e) => setMlBackfillLimit(Number(e.target.value) || 5000)}
              min={100}
              max={50000}
              className="ml-1 w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
            />
          </label>
          <button
            type="button"
            disabled={mlProgress?.backfill?.status === "running"}
            onClick={async () => {
              try {
                setMlBackfillResult(null);
                const r = await postAdminMlBackfillFeatures({ limit: mlBackfillLimit });
                if (!r.ok) setMlBackfillResult(r.error ?? "Ошибка");
                else await getAdminMlStats().then(setMlStats).catch(() => {});
              } catch (e) {
                setMlBackfillResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {mlProgress?.backfill?.status === "running" ? "Расчёт…" : "Backfill фичей"}
          </button>
        </div>
        {mlBackfillResult && <p className="text-sm text-slate-300 mb-3">{mlBackfillResult}</p>}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <button
            type="button"
            disabled={mlProgress?.player_stats?.status === "running"}
            onClick={async () => {
              try {
                const r = await postAdminMlPlayerStats({ limit: 10000 });
                if (!r.ok) setMlBackfillResult(r.error ?? "Ошибка");
                else await getAdminMlDashboard().then(setMlDashboard).catch(() => {});
              } catch (e) {
                setMlBackfillResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded bg-violet-600 px-3 py-2 text-sm text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {mlProgress?.player_stats?.status === "running" ? "Player stats…" : "Backfill player stats"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-slate-300" title="Минимум строк в обучающей выборке. Если данных меньше — модели не переобучатся.">
            min_rows
            <input
              type="number"
              value={mlRetrainMinRows}
              onChange={(e) => setMlRetrainMinRows(Number(e.target.value) || 100)}
              min={50}
              max={10000}
              className="ml-1 w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white"
            />
          </label>
          <button
            type="button"
            disabled={mlProgress?.retrain?.status === "running"}
            onClick={async () => {
              try {
                setMlRetrainResult(null);
                const r = await postAdminMlRetrain({ min_rows: mlRetrainMinRows });
                if (!r.ok) setMlRetrainResult(r.error ?? "Ошибка");
              } catch (e) {
                setMlRetrainResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded bg-amber-600 px-3 py-2 text-sm text-white hover:bg-amber-500 disabled:opacity-50"
          >
            {mlProgress?.retrain?.status === "running" ? "Обучение…" : "Переобучить модели"}
          </button>
        </div>
        {mlRetrainResult && <p className="text-sm text-slate-300 mt-2">{mlRetrainResult}</p>}
      </section>

      <section className={`${activeTab === "bot_info" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Сообщение бота «Получить информацию»</h2>
        <p className="text-slate-400 text-sm mb-2">
          Текст, который видят пользователи в Telegram-боте при нажатии на кнопку «Получить информацию».
        </p>
        <textarea
          value={botInfoMessage}
          onChange={(e) => setBotInfoMessage(e.target.value)}
          rows={6}
          placeholder="Введите сообщение для бота..."
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white mb-2"
        />
        <button
          type="button"
          disabled={botInfoSaving}
          onClick={async () => {
            try {
              setBotInfoSaving(true);
              await putAdminTelegramBotInfo(botInfoMessage);
            } catch (e) {
              setError(e instanceof Error ? e.message : "Ошибка сохранения");
            } finally {
              setBotInfoSaving(false);
            }
          }}
          className="rounded bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {botInfoSaving ? "Сохранение…" : "Сохранить"}
        </button>
      </section>

      <section className={`${activeTab === "schedules" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Настройка расписаний ботов (JSON)</h2>
        <p className="text-slate-400 text-sm mb-2">
          Полностью настраиваемые правила `откуда/сколько/куда`: слоты для FREE и PAID/ML, stream с группировкой для NO_ML, daily summary.
        </p>
        <DispatchConfigHelp />
        <DispatchConfigPreview cfgText={dispatchCfgText} />
        {dispatchCfgObj ? (
          <div className="my-3 grid gap-3 md:grid-cols-2">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p className="mb-2 font-medium text-slate-200">FREE: слоты</p>
              <div className="mb-2 grid grid-cols-3 gap-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean((dispatchCfgObj.free as Record<string, unknown> | undefined)?.enabled ?? true)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const free = (cfg.free as Record<string, unknown>) || {};
                        free.enabled = e.target.checked;
                        cfg.free = free;
                      })
                    }
                  />
                  enabled
                </label>
                <label>
                  min_lead
                  <input
                    type="number"
                    min={0}
                    value={Number((dispatchCfgObj.free as Record<string, unknown> | undefined)?.min_lead_minutes ?? 60)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const free = (cfg.free as Record<string, unknown>) || {};
                        free.min_lead_minutes = Number(e.target.value || 0);
                        cfg.free = free;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  summary UTC
                  <input
                    type="number"
                    min={0}
                    max={23}
                    value={(dispatchCfgObj.free as Record<string, unknown> | undefined)?.daily_summary_hour_utc === null ? "" : String((dispatchCfgObj.free as Record<string, unknown> | undefined)?.daily_summary_hour_utc ?? "")}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const free = (cfg.free as Record<string, unknown>) || {};
                        free.daily_summary_hour_utc = e.target.value === "" ? null : Number(e.target.value);
                        cfg.free = free;
                      })
                    }
                    placeholder="пусто = выкл"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
              </div>
              {Array.isArray((dispatchCfgObj.free as Record<string, unknown> | undefined)?.slots) ? (
                ((dispatchCfgObj.free as Record<string, unknown>).slots as Array<Record<string, unknown>>).map((slot, idx) => (
                  <div key={`free-slot-${idx}`} className="mb-2 grid grid-cols-4 gap-2">
                    <input
                      value={String(slot.time_msk ?? "")}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const free = (cfg.free as Record<string, unknown>) || {};
                          const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), time_msk: e.target.value };
                          free.slots = slots;
                          cfg.free = free;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    />
                    <select
                      value={String(slot.source ?? "no_ml")}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const free = (cfg.free as Record<string, unknown>) || {};
                          const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), source: e.target.value };
                          free.slots = slots;
                          cfg.free = free;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    >
                      <option value="no_ml">no_ml</option>
                      <option value="paid">paid</option>
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={Number(slot.count ?? 1)}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const free = (cfg.free as Record<string, unknown>) || {};
                          const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), count: Number(e.target.value || 1) };
                          free.slots = slots;
                          cfg.free = free;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        updateDispatchCfg((cfg) => {
                          const free = (cfg.free as Record<string, unknown>) || {};
                          const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                          slots.splice(idx, 1);
                          free.slots = slots;
                          cfg.free = free;
                        })
                      }
                      className="rounded border border-rose-700 px-2 py-1 text-rose-300 hover:bg-rose-950/30"
                    >
                      удалить
                    </button>
                  </div>
                ))
              ) : null}
              <button
                type="button"
                onClick={() =>
                  updateDispatchCfg((cfg) => {
                    const free = (cfg.free as Record<string, unknown>) || {};
                    const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                    slots.push({ time_msk: "11:00", source: "no_ml", count: 1 });
                    free.slots = slots;
                    cfg.free = free;
                  })
                }
                className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                + добавить слот
              </button>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p className="mb-2 font-medium text-slate-200">PAID/ML: слоты</p>
              <div className="mb-2 grid grid-cols-3 gap-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean((dispatchCfgObj.vip as Record<string, unknown> | undefined)?.enabled ?? true)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const vip = (cfg.vip as Record<string, unknown>) || {};
                        vip.enabled = e.target.checked;
                        cfg.vip = vip;
                      })
                    }
                  />
                  enabled
                </label>
                <label>
                  min_lead
                  <input
                    type="number"
                    min={0}
                    value={Number((dispatchCfgObj.vip as Record<string, unknown> | undefined)?.min_lead_minutes ?? 60)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const vip = (cfg.vip as Record<string, unknown>) || {};
                        vip.min_lead_minutes = Number(e.target.value || 0);
                        cfg.vip = vip;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  summary UTC
                  <input
                    type="number"
                    min={0}
                    max={23}
                    value={(dispatchCfgObj.vip as Record<string, unknown> | undefined)?.daily_summary_hour_utc === null ? "" : String((dispatchCfgObj.vip as Record<string, unknown> | undefined)?.daily_summary_hour_utc ?? "")}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const vip = (cfg.vip as Record<string, unknown>) || {};
                        vip.daily_summary_hour_utc = e.target.value === "" ? null : Number(e.target.value);
                        cfg.vip = vip;
                      })
                    }
                    placeholder="пусто = выкл"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
              </div>
              {Array.isArray((dispatchCfgObj.vip as Record<string, unknown> | undefined)?.slots) ? (
                ((dispatchCfgObj.vip as Record<string, unknown>).slots as Array<Record<string, unknown>>).map((slot, idx) => (
                  <div key={`vip-slot-${idx}`} className="mb-2 grid grid-cols-4 gap-2">
                    <input
                      value={String(slot.time_msk ?? "")}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const vip = (cfg.vip as Record<string, unknown>) || {};
                          const slots = Array.isArray(vip.slots) ? ([...vip.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), time_msk: e.target.value };
                          vip.slots = slots;
                          cfg.vip = vip;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    />
                    <select
                      value={String(slot.source ?? "no_ml")}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const vip = (cfg.vip as Record<string, unknown>) || {};
                          const slots = Array.isArray(vip.slots) ? ([...vip.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), source: e.target.value };
                          vip.slots = slots;
                          cfg.vip = vip;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    >
                      <option value="no_ml">no_ml</option>
                      <option value="paid">paid</option>
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={Number(slot.count ?? 1)}
                      onChange={(e) =>
                        updateDispatchCfg((cfg) => {
                          const vip = (cfg.vip as Record<string, unknown>) || {};
                          const slots = Array.isArray(vip.slots) ? ([...vip.slots] as Array<Record<string, unknown>>) : [];
                          slots[idx] = { ...(slots[idx] || {}), count: Number(e.target.value || 1) };
                          vip.slots = slots;
                          cfg.vip = vip;
                        })
                      }
                      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        updateDispatchCfg((cfg) => {
                          const vip = (cfg.vip as Record<string, unknown>) || {};
                          const slots = Array.isArray(vip.slots) ? ([...vip.slots] as Array<Record<string, unknown>>) : [];
                          slots.splice(idx, 1);
                          vip.slots = slots;
                          cfg.vip = vip;
                        })
                      }
                      className="rounded border border-rose-700 px-2 py-1 text-rose-300 hover:bg-rose-950/30"
                    >
                      удалить
                    </button>
                  </div>
                ))
              ) : null}
              <button
                type="button"
                onClick={() =>
                  updateDispatchCfg((cfg) => {
                    const vip = (cfg.vip as Record<string, unknown>) || {};
                    const slots = Array.isArray(vip.slots) ? ([...vip.slots] as Array<Record<string, unknown>>) : [];
                    slots.push({ time_msk: "12:00", source: "paid", count: 1 });
                    vip.slots = slots;
                    cfg.vip = vip;
                  })
                }
                className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                + добавить слот
              </button>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300 md:col-span-2">
              <p className="mb-2 font-medium text-slate-200">NO_ML: поток с группировкой</p>
              <div className="mb-2 grid gap-2 md:grid-cols-4">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.enabled ?? true)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.enabled = e.target.checked;
                        cfg.no_ml_channel = no;
                      })
                    }
                  />
                  enabled
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.stream_enabled ?? false)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.stream_enabled = e.target.checked;
                        cfg.no_ml_channel = no;
                      })
                    }
                  />
                  stream_enabled
                </label>
                <label>
                  min_lead
                  <input
                    type="number"
                    min={0}
                    value={Number((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.min_lead_minutes ?? 60)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.min_lead_minutes = Number(e.target.value || 0);
                        cfg.no_ml_channel = no;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  summary UTC
                  <input
                    type="number"
                    min={0}
                    max={23}
                    value={(dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.daily_summary_hour_utc === null ? "" : String((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.daily_summary_hour_utc ?? "")}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.daily_summary_hour_utc = e.target.value === "" ? null : Number(e.target.value);
                        cfg.no_ml_channel = no;
                      })
                    }
                    placeholder="пусто = выкл"
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
              </div>
              <div className="grid gap-2 md:grid-cols-4">
                <label>
                  interval, мин
                  <input
                    type="number"
                    min={5}
                    value={Number((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.stream_interval_minutes ?? 30)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.stream_interval_minutes = Number(e.target.value || 30);
                        cfg.no_ml_channel = no;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  group_limit
                  <input
                    type="number"
                    min={1}
                    value={Number((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.stream_group_limit ?? 20)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.stream_group_limit = Number(e.target.value || 20);
                        cfg.no_ml_channel = no;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  fetch_limit
                  <input
                    type="number"
                    min={1}
                    value={Number((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.stream_fetch_limit ?? 500)}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.stream_fetch_limit = Number(e.target.value || 500);
                        cfg.no_ml_channel = no;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label>
                  source
                  <select
                    value={String((dispatchCfgObj.no_ml_channel as Record<string, unknown> | undefined)?.stream_source ?? "no_ml")}
                    onChange={(e) =>
                      updateDispatchCfg((cfg) => {
                        const no = (cfg.no_ml_channel as Record<string, unknown>) || {};
                        no.stream_source = e.target.value;
                        cfg.no_ml_channel = no;
                      })
                    }
                    className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white"
                  >
                    <option value="no_ml">no_ml</option>
                    <option value="paid">paid</option>
                  </select>
                </label>
              </div>
            </div>
          </div>
        ) : null}
        <textarea
          value={dispatchCfgText}
          onChange={(e) => setDispatchCfgText(e.target.value)}
          rows={12}
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white my-2"
        />
        <button
          type="button"
          onClick={() => {
            setDispatchCfgText(JSON.stringify({
              free: {
                enabled: true,
                slots: [
                  { time_msk: "11:00", source: "no_ml", count: 1 },
                  { time_msk: "15:00", source: "no_ml", count: 1 },
                  { time_msk: "17:00", source: "no_ml", count: 1 },
                ],
                min_lead_minutes: 60,
                daily_summary_hour_utc: 21,
              },
              vip: {
                enabled: true,
                slots: [
                  { time_msk: "12:00", source: "no_ml", count: 3 },
                  { time_msk: "16:00", source: "no_ml", count: 3 },
                  { time_msk: "19:00", source: "no_ml", count: 3 },
                ],
                min_lead_minutes: 60,
                daily_summary_hour_utc: 23,
              },
              no_ml_channel: {
                enabled: true,
                stream_enabled: true,
                stream_interval_minutes: 30,
                stream_source: "no_ml",
                stream_group_limit: 20,
                stream_fetch_limit: 500,
                min_lead_minutes: 60,
                daily_summary_hour_utc: 22,
              },
            }, null, 2));
          }}
          className="mr-2 rounded border border-slate-600 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
        >
          Подставить шаблон (3 канала)
        </button>
        <button
          type="button"
          disabled={dispatchCfgSaving}
          onClick={async () => {
            try {
              setDispatchCfgSaving(true);
              const parsed = JSON.parse(dispatchCfgText || "{}") as Record<string, unknown>;
              await putAdminTelegramDispatchConfig(parsed);
            } catch (e) {
              setError(e instanceof Error ? e.message : "Ошибка сохранения расписания");
            } finally {
              setDispatchCfgSaving(false);
            }
          }}
          className="rounded bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-500 disabled:opacity-50"
        >
          {dispatchCfgSaving ? "Сохранение…" : "Сохранить расписание"}
        </button>
      </section>

      <section className={`${activeTab === "messages" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3">Рассылки (каналы / бот / email)</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-300">
            Куда
            <select
              value={messageTarget}
              onChange={(e) => setMessageTarget(e.target.value as "free_channel" | "vip_channel" | "no_ml_channel" | "telegram_user" | "telegram_all_users" | "email")}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            >
              <option value="free_channel">FREE канал</option>
              <option value="vip_channel">ML (платный) канал</option>
              <option value="no_ml_channel">NO_ML канал</option>
              <option value="telegram_user">Пользователь в Telegram</option>
              <option value="telegram_all_users">Все пользователи Telegram-бота</option>
              <option value="email">Email</option>
            </select>
          </label>
          {messageTarget === "telegram_user" ? (
            <label className="text-sm text-slate-300">
              user_id
              <input value={messageUserId} onChange={(e) => setMessageUserId(e.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
            </label>
          ) : null}
          {messageTarget === "email" ? (
            <>
              <label className="text-sm text-slate-300">
                Email
                <input value={messageEmail} onChange={(e) => setMessageEmail(e.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
              </label>
              <label className="text-sm text-slate-300">
                Тема
                <input value={messageSubject} onChange={(e) => setMessageSubject(e.target.value)} className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
              </label>
            </>
          ) : null}
        </div>
        <label className="mt-3 block text-sm text-slate-300">
          Текст
          <textarea
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            rows={5}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
        </label>
        <label className="mt-3 block text-sm text-slate-300">
          Картинка (URL, опционально)
          <input
            value={messageImageUrl}
            onChange={(e) => setMessageImageUrl(e.target.value)}
            placeholder="https://..."
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
        </label>
        <label className="mt-3 block text-sm text-slate-300">
          Несколько картинок (по одной ссылке в строке, опционально)
          <textarea
            value={messageImageUrls}
            onChange={(e) => setMessageImageUrls(e.target.value)}
            rows={3}
            placeholder={"https://...\nhttps://..."}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
        </label>
        <button
          type="button"
          disabled={sending || !messageText.trim()}
          onClick={async () => {
            try {
              setSending(true);
              setError(null);
              setMessageResult("");
              const res = await sendAdminMessage({
                target: messageTarget,
                text: messageText,
                user_id: messageUserId || undefined,
                email: messageEmail || undefined,
                subject: messageSubject || undefined,
                image_url: messageImageUrl.trim() || undefined,
                image_urls: messageImageUrls
                  .split(/\r?\n/)
                  .map((x) => x.trim())
                  .filter(Boolean),
              });
              if (messageTarget === "telegram_all_users") {
                setMessageResult(`Отправлено: ${res.sent ?? 0} из ${res.total ?? 0}`);
              } else {
                setMessageResult("Сообщение отправлено");
              }
              setMessageText("");
              setMessageImageUrl("");
              setMessageImageUrls("");
            } catch (e) {
              setError(e instanceof Error ? e.message : "Ошибка отправки");
            } finally {
              setSending(false);
            }
          }}
          className="mt-3 rounded bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {sending ? "Отправка..." : "Отправить"}
        </button>
        {messageResult ? <p className="mt-2 text-sm text-emerald-300">{messageResult}</p> : null}
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
      </section>
        </div>
      </div>
    </div>
  );
}
