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
  getAdminMlV2Status,
  getAdminMlSyncAudit,
  getAdminMlStats,
  getAdminMlNoMlStats,
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
  postAdminMlOddsBackfillBg,
  postAdminMlFullRebuild,
  postAdminMlResetProgress,
  postAdminMlLoadArchive,
  postAdminMlPlayerStats,
  postAdminMlRetrain,
  postAdminMlRequestFullSync,
  postAdminForecastsClearAll,
  postAdminForecastsClearMl,
  postAdminForecastsClearNn,
  postAdminForecastsClearNoMl,
  postAdminMlSync,
  postAdminMlSyncLeagues,
  postAdminMlSyncPlayers,
  postAdminMlV2BackfillMatchSets,
  putAdminApplyNnEnv,
  putAdminApplyNnEnvAndRestart,
  putAdminTelegramBotInfo,
  putAdminTelegramDispatchConfig,
  sendAdminMessage,
  type AdminInvoiceItem,
  type AdminMlDashboard,
  type AdminMlProgress,
  type AdminMlV2Status,
  type AdminMlNoMlStats,
  type AdminMlSyncAudit,
  type AdminMlStats,
  type AdminPaymentMethod,
  type AdminProduct,
  type AdminUserListItem,
} from "@/lib/api";

function moneyCompact(v: number): string {
  const rounded = Math.round(v * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function formatTs(ts?: number | null): string {
  if (!ts || !Number.isFinite(ts) || ts <= 0) return "—";
  return new Date(ts * 1000).toLocaleString();
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

function HintBadge({ text }: { text: string }) {
  return (
    <span className="relative inline-flex items-center group align-middle">
      <button
        type="button"
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-400 bg-slate-800 text-[10px] text-slate-100 cursor-help"
        aria-label="Показать подсказку"
      >
        ?
      </button>
      <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-1 hidden w-72 -translate-x-1/2 rounded border border-slate-600 bg-slate-950/95 px-2 py-1 text-[11px] leading-snug text-slate-200 shadow-xl group-hover:block group-focus-within:block">
        {text}
      </span>
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
        const src = String(it.source || "paid");
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
        <span className="text-slate-100">Источники (`source`):</span> <code>paid</code>, <code>no_ml</code> или <code>nn</code>.
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
        <code>stream_fetch_limit</code> (&gt;=1), <code>stream_source</code> (<code>no_ml</code> | <code>paid</code> | <code>nn</code>).
      </p>
      <p>
        <span className="text-slate-100">Внеочередная отправка:</span> если матч/прогноз появился позже чем за{" "}
        <code>min_lead_minutes</code> до старта, он отправляется сразу (вне интервала).
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
  const [mlV2Status, setMlV2Status] = useState<AdminMlV2Status | null>(null);
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
  const [mlAudit, setMlAudit] = useState<AdminMlSyncAudit | null>(null);
  const [mlAuditResult, setMlAuditResult] = useState<string | null>(null);
  const [mlVerify, setMlVerify] = useState<{
    main: { matches: number; players: number; leagues: number };
    ml: { matches: number; players: number; leagues: number };
    diff: { matches: number; players: number; leagues: number };
    ok: boolean;
    message: string;
  } | null>(null);
  const [mlProgress, setMlProgress] = useState<AdminMlProgress | null>(null);
  const [archiveLoadDateFrom, setArchiveLoadDateFrom] = useState("");
  const [archiveLoadDateTo, setArchiveLoadDateTo] = useState("");
  const [archiveLoadLoading, setArchiveLoadLoading] = useState(false);
  const [archiveLoadResult, setArchiveLoadResult] = useState<string | null>(null);
  const [mlNoMlStats, setMlNoMlStats] = useState<AdminMlNoMlStats | null>(null);
  const [matchSetsBackfillLoading, setMatchSetsBackfillLoading] = useState(false);
  const [matchSetsBackfillResult, setMatchSetsBackfillResult] = useState<string | null>(null);
  const [nnEditorCopied, setNnEditorCopied] = useState<string | null>(null);
  const [nnApplyLoading, setNnApplyLoading] = useState(false);
  const [nnApplyRestartLoading, setNnApplyRestartLoading] = useState(false);
  const [nnEditorDraft, setNnEditorDraft] = useState({
    ml_v2_enable_nn: "true",
    betsapi_table_tennis_nn_allow_hard_confidence_fallback: "false",
    betsapi_table_tennis_forecast_tolerance_minutes: "5",
    betsapi_table_tennis_forecast_window_min_minutes_before: "1",
    betsapi_table_tennis_forecast_ml_max_minutes_before: "60",
    betsapi_table_tennis_nn_forecast_interval_sec: "60",
    betsapi_table_tennis_nn_min_confidence_to_publish: "62",
    betsapi_table_tennis_nn_min_match_confidence_pct: "66",
    betsapi_table_tennis_nn_min_set1_confidence_pct: "67",
    ml_v2_nn_hidden_layers: "128,64",
    ml_v2_nn_learning_rate: "0.001",
    ml_v2_nn_alpha: "0.0001",
    ml_v2_nn_batch_size: "256",
    ml_v2_nn_max_iter: "120",
  });

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
        getAdminMlProgress().then(setMlProgress).catch(() => setMlProgress(null)),
        getAdminMlV2Status().then(setMlV2Status).catch(() => setMlV2Status(null)),
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
    const cfg = mlV2Status?.v2_config;
    if (!cfg) return;
    setNnEditorDraft({
      ml_v2_enable_nn: String(Boolean(cfg.ml_v2_enable_nn)),
      betsapi_table_tennis_nn_allow_hard_confidence_fallback: String(Boolean(cfg.betsapi_table_tennis_nn_allow_hard_confidence_fallback)),
      betsapi_table_tennis_forecast_tolerance_minutes: String(cfg.betsapi_table_tennis_forecast_tolerance_minutes ?? 5),
      betsapi_table_tennis_forecast_window_min_minutes_before: String(cfg.betsapi_table_tennis_forecast_window_min_minutes_before ?? 1),
      betsapi_table_tennis_forecast_ml_max_minutes_before: String(cfg.betsapi_table_tennis_forecast_ml_max_minutes_before ?? 60),
      betsapi_table_tennis_nn_forecast_interval_sec: String(cfg.betsapi_table_tennis_nn_forecast_interval_sec ?? 60),
      betsapi_table_tennis_nn_min_confidence_to_publish: String(cfg.betsapi_table_tennis_nn_min_confidence_to_publish ?? 0),
      betsapi_table_tennis_nn_min_match_confidence_pct: String(cfg.betsapi_table_tennis_nn_min_match_confidence_pct ?? 0),
      betsapi_table_tennis_nn_min_set1_confidence_pct: String(cfg.betsapi_table_tennis_nn_min_set1_confidence_pct ?? 0),
      ml_v2_nn_hidden_layers: String(cfg.ml_v2_nn_hidden_layers ?? "128,64"),
      ml_v2_nn_learning_rate: String(cfg.ml_v2_nn_learning_rate ?? 0.001),
      ml_v2_nn_alpha: String(cfg.ml_v2_nn_alpha ?? 0.0001),
      ml_v2_nn_batch_size: String(cfg.ml_v2_nn_batch_size ?? 256),
      ml_v2_nn_max_iter: String(cfg.ml_v2_nn_max_iter ?? 120),
    });
  }, [mlV2Status]);

  useEffect(() => {
    if (!allowed) return;
    const poll = async () => {
      const [progress, v2] = await Promise.all([
        getAdminMlProgress().catch(() => null),
        getAdminMlV2Status().catch(() => null),
      ]);
      if (progress) setMlProgress(progress);
      if (v2) setMlV2Status(v2);
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
      title={
        tab === "users"
          ? "Управление пользователями"
          : tab === "products"
            ? "Настройка тарифов"
            : tab === "methods"
              ? "Настройка способов оплаты"
              : tab === "invoices"
                ? "Модерация инвойсов"
                : tab === "ml"
                  ? "ML синхронизация и обучение"
                  : tab === "bot_info"
                    ? "Текст бота «Получить информацию»"
                    : tab === "schedules"
                      ? "Расписание каналов и источников"
                      : "Ручные рассылки"
      }
      className={`w-full rounded px-3 py-2 text-left text-sm border ${
        activeTab === tab
          ? "border-sky-500/50 bg-sky-500/20 text-sky-100"
          : "border-slate-700 text-slate-300 hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );

  const nnEnvValues: Record<string, string> = {
    ML_V2_ENABLE_NN: nnEditorDraft.ml_v2_enable_nn.trim() || "true",
    BETSAPI_TABLE_TENNIS_NN_ALLOW_HARD_CONFIDENCE_FALLBACK:
      nnEditorDraft.betsapi_table_tennis_nn_allow_hard_confidence_fallback.trim() || "false",
    BETSAPI_TABLE_TENNIS_FORECAST_TOLERANCE_MINUTES: nnEditorDraft.betsapi_table_tennis_forecast_tolerance_minutes.trim() || "5",
    BETSAPI_TABLE_TENNIS_FORECAST_WINDOW_MIN_MINUTES_BEFORE: nnEditorDraft.betsapi_table_tennis_forecast_window_min_minutes_before.trim() || "1",
    BETSAPI_TABLE_TENNIS_FORECAST_ML_MAX_MINUTES_BEFORE: nnEditorDraft.betsapi_table_tennis_forecast_ml_max_minutes_before.trim() || "60",
    BETSAPI_TABLE_TENNIS_NN_FORECAST_INTERVAL_SEC: nnEditorDraft.betsapi_table_tennis_nn_forecast_interval_sec.trim() || "60",
    BETSAPI_TABLE_TENNIS_NN_MIN_CONFIDENCE_TO_PUBLISH: nnEditorDraft.betsapi_table_tennis_nn_min_confidence_to_publish.trim() || "62",
    BETSAPI_TABLE_TENNIS_NN_MIN_MATCH_CONFIDENCE_PCT: nnEditorDraft.betsapi_table_tennis_nn_min_match_confidence_pct.trim() || "66",
    BETSAPI_TABLE_TENNIS_NN_MIN_SET1_CONFIDENCE_PCT: nnEditorDraft.betsapi_table_tennis_nn_min_set1_confidence_pct.trim() || "67",
    ML_V2_NN_HIDDEN_LAYERS: nnEditorDraft.ml_v2_nn_hidden_layers.trim() || "128,64",
    ML_V2_NN_LEARNING_RATE: nnEditorDraft.ml_v2_nn_learning_rate.trim() || "0.001",
    ML_V2_NN_ALPHA: nnEditorDraft.ml_v2_nn_alpha.trim() || "0.0001",
    ML_V2_NN_BATCH_SIZE: nnEditorDraft.ml_v2_nn_batch_size.trim() || "256",
    ML_V2_NN_MAX_ITER: nnEditorDraft.ml_v2_nn_max_iter.trim() || "120",
  };
  const nnEnvBlock = Object.entries(nnEnvValues)
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");

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
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Пользователи <HintBadge text="Поиск, просмотр и управление статусом пользователей." /></h2>
        <div className="flex flex-wrap gap-2 mb-3">
          <input
            value={usersQ}
            onChange={(e) => setUsersQ(e.target.value)}
            placeholder="Поиск по email / username / notification email"
            title="Поиск по email, telegram username и notification email."
            className="w-full md:w-96 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
          <button
            type="button"
            onClick={() => {
              setUsersOffset(0);
              void loadUsers();
            }}
            className="rounded bg-sky-600 px-3 py-2 text-sm text-white hover:bg-sky-500"
            title="Применить фильтр поиска и перезагрузить список."
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
            title="Предыдущая страница."
          >
            Назад
          </button>
          <button
            type="button"
            disabled={usersOffset + pageSize >= usersTotal}
            onClick={() => setUsersOffset((v) => v + pageSize)}
            className="disabled:opacity-40"
            title="Следующая страница."
          >
            Вперёд
          </button>
        </div>
      </section>

      <section className={`${activeTab === "products" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Тарифы (биллинг) <HintBadge text="Редактирование цен RUB/USD и доступности тарифов." /></h2>
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
                title="Цена тарифа в рублях."
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
                title="Цена тарифа в долларах."
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
                  title="Включить/выключить тариф на витрине."
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
                title="Сохранить изменения тарифа."
              >
                Сохранить
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className={`${activeTab === "methods" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Платёжки <HintBadge text="Методы оплаты и инструкции, которые видит пользователь при создании инвойса." /></h2>
        <div className="grid gap-2 md:grid-cols-[1fr_140px_1fr_auto] mb-4">
          <input value={newMethodName} onChange={(e) => setNewMethodName(e.target.value)} placeholder="Название (например: Безналичная оплата)" title="Название способа оплаты, видимое пользователю." className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
          <select value={newMethodType} onChange={(e) => setNewMethodType(e.target.value as "custom" | "card" | "crypto")} title="Технический тип метода оплаты." className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
            <option value="custom">custom</option>
            <option value="card">card</option>
            <option value="crypto">crypto</option>
          </select>
          <textarea value={newMethodInstructions} onChange={(e) => setNewMethodInstructions(e.target.value)} placeholder="Сообщение для пользователя: как и куда оплатить (можно @telegram, t.me/..., https://...)" title="Инструкция к оплате, показывается в модалке инвойса." rows={2} className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
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
            title="Добавить новый способ оплаты."
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
                  title="Включить/выключить способ оплаты."
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
                title="Сохранить состояние и текст инструкции."
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
                title="Удалить способ оплаты из системы."
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
                title="Редактирование текста инструкции по оплате."
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
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Инвойсы <HintBadge text="Ручная модерация статусов инвойсов: оплатить/отклонить." /></h2>
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
                        title="Подтвердить оплату инвойса и выдать подписку."
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
                        title="Отклонить инвойс."
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
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">ML v2 (ClickHouse) <HintBadge text="Синхронизация и переобучение ML v2 в ClickHouse (GPU retrain)." /></h2>
        {mlV2Status && (
          <div className={`rounded-lg border p-3 mb-4 text-sm ${mlV2Status.clickhouse_ok ? "border-emerald-700/50 bg-emerald-950/20" : "border-rose-700/50 bg-rose-950/20"}`}>
            <p className="font-medium text-slate-200">ML v2 статус ({mlV2Status.engine})</p>
            <p className="text-xs text-slate-300 mt-1">
              ClickHouse: {mlV2Status.clickhouse_ok ? "OK" : `ошибка (${mlV2Status.clickhouse_error || "unknown"})`} · очередь: {mlV2Status.queue_size ?? 0}
            </p>
            <p className="text-xs text-slate-300 mt-1">
              matches: {(mlV2Status.tables?.matches ?? 0).toLocaleString()} / main finished: {(mlV2Status.main_finished ?? 0).toLocaleString()} / delta: {(mlV2Status.delta_main_minus_ch_matches ?? 0) >= 0 ? `+${mlV2Status.delta_main_minus_ch_matches}` : mlV2Status.delta_main_minus_ch_matches}
            </p>
            <p className="text-xs text-slate-300 mt-1">
              retrain: {formatTs(Number(mlV2Status.meta?.ml_v2_last_retrain_at_ts || 0))}, device={String(mlV2Status.meta?.ml_v2_last_retrain_device || "—")}, model={formatTs(Number(mlV2Status.meta?.ml_v2_last_model_created_at_ts || 0))}
            </p>
            <p className="text-xs text-slate-300 mt-1">
              KPI: match={(Number(mlV2Status.kpi?.match_hit_rate || 0) * 100).toFixed(2)}%, set1={(Number(mlV2Status.kpi?.set1_hit_rate || 0) * 100).toFixed(2)}%, sample={Number(mlV2Status.kpi?.sample_size || 0).toLocaleString()}
            </p>
          </div>
        )}
        <div className="rounded-lg border border-slate-700 bg-slate-900/80 p-3 mb-4 text-sm text-slate-300 space-y-2">
          <p className="font-medium text-slate-200">Два источника заполнения (v2):</p>
          <ol className="list-decimal list-inside space-y-1 text-xs">
            <li><strong>ml_sync_loop</strong> (контейнер <code className="text-slate-400">ml_sync</code>, каждые 10 минут) — finished main→ClickHouse: матчи, сеты, Elo/history и rebuild features.</li>
            <li><strong>ml_worker</strong> (отдельный контейнер) — обрабатывает очередь задач. Убедитесь, что <code className="text-slate-400">docker compose up ml_worker</code> запущен.</li>
          </ol>
          <p className="font-medium text-slate-200 mt-2">Ручные действия (v2):</p>
          <ol className="list-decimal list-inside space-y-1 text-xs">
            <li><strong>Все матчи</strong> — догонка finished матчей из main в ClickHouse.</li>
            <li><strong>Backfill фичей</strong> — rebuild таблицы <code className="text-slate-400">ml.match_features</code>.</li>
            <li><strong>Переобучить модели</strong> — LightGBM v2 на GPU через <code className="text-slate-400">ml_worker</code>.</li>
            <li><strong>Full rebuild</strong> — sync + features + retrain + KPI.</li>
          </ol>
          <p className="text-xs text-slate-500 mt-2">Очередь ml_worker: {mlV2Status?.queue_size ?? 0} задач</p>
          {mlV2Status && (
            <div className="mt-2 rounded border border-slate-700/70 bg-slate-950/40 p-2 text-xs text-slate-300">
              <p>Последняя синхронизация v2: {formatTs(Number(mlV2Status.meta?.ml_v2_last_sync_at_ts || 0))}</p>
              <p>Последний запрос retrain: {formatTs(Number(mlV2Status.meta?.ml_v2_last_retrain_requested_at_ts || 0))}</p>
              <p>
                Main finished / CH matches: {(mlV2Status.main_finished ?? 0).toLocaleString()} / {(mlV2Status.tables?.matches ?? 0).toLocaleString()} (delta: {(mlV2Status.delta_main_minus_ch_matches ?? 0) >= 0 ? `+${mlV2Status.delta_main_minus_ch_matches}` : mlV2Status.delta_main_minus_ch_matches})
              </p>
              <p>
                CH features / CH matches: {(mlV2Status.tables?.match_features ?? 0).toLocaleString()} / {(mlV2Status.tables?.matches ?? 0).toLocaleString()} (gap: {(mlV2Status.delta_ch_matches_minus_features ?? 0) >= 0 ? `+${mlV2Status.delta_ch_matches_minus_features}` : mlV2Status.delta_ch_matches_minus_features})
              </p>
              <p>
                CH match_sets(uniq match_id) / CH matches: {(mlV2Status.tables?.match_sets_uniq_matches ?? 0).toLocaleString()} / {(mlV2Status.tables?.matches ?? 0).toLocaleString()} (gap: {(mlV2Status.delta_ch_matches_minus_match_sets ?? 0) >= 0 ? `+${mlV2Status.delta_ch_matches_minus_match_sets}` : mlV2Status.delta_ch_matches_minus_match_sets}, {Number(mlV2Status.match_sets_gap_pct ?? 0).toFixed(2)}%)
              </p>
              <p>
                CH: features={(mlV2Status.tables?.match_features ?? 0).toLocaleString()}, sets={(mlV2Status.tables?.match_sets ?? 0).toLocaleString()}, player_match_stats={(mlV2Status.tables?.player_match_stats ?? 0).toLocaleString()}, elo={(mlV2Status.tables?.player_elo_history ?? 0).toLocaleString()}
              </p>
              <p>
                Последнее обучение: {formatTs(Number(mlV2Status.meta?.ml_v2_last_retrain_at_ts || 0))}
                {Number(mlV2Status.meta?.ml_v2_last_retrain_trained || 0) === 1 ? " (успешно)" : " (без обучения/пропуск)"}
              </p>
              <p>Последняя созданная модель: {formatTs(Number(mlV2Status.meta?.ml_v2_last_model_created_at_ts || 0))}</p>
              <p>Данных во входе обучения: {(Number(mlV2Status.meta?.ml_v2_last_retrain_rows || 0)).toLocaleString()}</p>
              <p>KPI: match={(Number(mlV2Status.kpi?.match_hit_rate || 0) * 100).toFixed(2)}%, set1={(Number(mlV2Status.kpi?.set1_hit_rate || 0) * 100).toFixed(2)}%, sample={Number(mlV2Status.kpi?.sample_size || 0).toLocaleString()}</p>
              {mlV2Status.v2_config && (
                <div className="mt-2 pt-2 border-t border-slate-600/50 space-y-2">
                  <p className="text-slate-200 font-medium">Конфигурация расчета</p>
                  <div className="grid gap-2 lg:grid-cols-2">
                    <div className="rounded border border-slate-700/70 bg-slate-900/50 p-2">
                      <p className="text-slate-200 font-medium">ML v2</p>
                      <p>experience_regimes: {String(mlV2Status.v2_config.ml_v2_use_experience_regimes)}</p>
                      <p>confidence_filter_min_pct: {mlV2Status.v2_config.betsapi_table_tennis_v2_confidence_filter_min_pct || 0}</p>
                      <p>league_upset_cap: {mlV2Status.v2_config.ml_v2_train_max_league_upset_rate}</p>
                    </div>
                    <div className="rounded border border-fuchsia-700/50 bg-fuchsia-950/20 p-2">
                      <p className="text-fuchsia-200 font-medium">NN</p>
                      <p>enabled: {String(Boolean(mlV2Status.v2_config.ml_v2_enable_nn))}</p>
                      <p>interval_sec: {mlV2Status.v2_config.betsapi_table_tennis_nn_forecast_interval_sec ?? 60}</p>
                      <p>publish_min_pct: {mlV2Status.v2_config.betsapi_table_tennis_nn_min_confidence_to_publish ?? 0}</p>
                      <p>match_min_pct: {mlV2Status.v2_config.betsapi_table_tennis_nn_min_match_confidence_pct ?? 0}</p>
                      <p>set1_min_pct: {mlV2Status.v2_config.betsapi_table_tennis_nn_min_set1_confidence_pct ?? 0}</p>
                      <p>allow_hard_fallback: {String(Boolean(mlV2Status.v2_config.betsapi_table_tennis_nn_allow_hard_confidence_fallback))}</p>
                      <p>layers: {mlV2Status.v2_config.ml_v2_nn_hidden_layers ?? "—"}</p>
                      <p>learning_rate: {mlV2Status.v2_config.ml_v2_nn_learning_rate ?? 0}</p>
                      <p>alpha: {mlV2Status.v2_config.ml_v2_nn_alpha ?? 0}</p>
                      <p>batch_size: {mlV2Status.v2_config.ml_v2_nn_batch_size ?? 0}</p>
                      <p>max_iter: {mlV2Status.v2_config.ml_v2_nn_max_iter ?? 0}</p>
                    </div>
                  </div>
                  <div className="rounded border border-fuchsia-700/40 bg-fuchsia-950/10 p-3 space-y-2">
                    <p className="text-fuchsia-200 font-medium">Редактор NN настроек (.env)</p>
                    <p className="text-slate-400">
                      Измените значения ниже, затем скопируйте блок и вставьте в <code className="bg-slate-800 px-1 rounded">.env</code>. После изменения перезапустите контейнеры.
                    </p>
                    <div className="grid gap-2 md:grid-cols-2">
                      <label>
                        <span className="text-slate-300">ML_V2_ENABLE_NN</span>
                        <select
                          value={nnEditorDraft.ml_v2_enable_nn}
                          onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_enable_nn: e.target.value }))}
                          className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white"
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_NN_ALLOW_HARD_CONFIDENCE_FALLBACK</span>
                        <select
                          value={nnEditorDraft.betsapi_table_tennis_nn_allow_hard_confidence_fallback}
                          onChange={(e) =>
                            setNnEditorDraft((p) => ({
                              ...p,
                              betsapi_table_tennis_nn_allow_hard_confidence_fallback: e.target.value,
                            }))
                          }
                          className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white"
                        >
                          <option value="false">false</option>
                          <option value="true">true</option>
                        </select>
                      </label>
                      <label>
                        <span className="text-slate-300">ML_V2_NN_HIDDEN_LAYERS</span>
                        <input value={nnEditorDraft.ml_v2_nn_hidden_layers} onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_nn_hidden_layers: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">ML_V2_NN_LEARNING_RATE</span>
                        <input value={nnEditorDraft.ml_v2_nn_learning_rate} onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_nn_learning_rate: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">ML_V2_NN_ALPHA</span>
                        <input value={nnEditorDraft.ml_v2_nn_alpha} onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_nn_alpha: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">ML_V2_NN_BATCH_SIZE</span>
                        <input value={nnEditorDraft.ml_v2_nn_batch_size} onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_nn_batch_size: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">ML_V2_NN_MAX_ITER</span>
                        <input value={nnEditorDraft.ml_v2_nn_max_iter} onChange={(e) => setNnEditorDraft((p) => ({ ...p, ml_v2_nn_max_iter: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_NN_FORECAST_INTERVAL_SEC</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_nn_forecast_interval_sec} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_nn_forecast_interval_sec: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_NN_MIN_CONFIDENCE_TO_PUBLISH</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_nn_min_confidence_to_publish} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_nn_min_confidence_to_publish: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_NN_MIN_MATCH_CONFIDENCE_PCT</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_nn_min_match_confidence_pct} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_nn_min_match_confidence_pct: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_NN_MIN_SET1_CONFIDENCE_PCT</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_nn_min_set1_confidence_pct} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_nn_min_set1_confidence_pct: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_FORECAST_WINDOW_MIN_MINUTES_BEFORE</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_forecast_window_min_minutes_before} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_forecast_window_min_minutes_before: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_FORECAST_ML_MAX_MINUTES_BEFORE</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_forecast_ml_max_minutes_before} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_forecast_ml_max_minutes_before: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                      <label>
                        <span className="text-slate-300">BETSAPI_TABLE_TENNIS_FORECAST_TOLERANCE_MINUTES</span>
                        <input value={nnEditorDraft.betsapi_table_tennis_forecast_tolerance_minutes} onChange={(e) => setNnEditorDraft((p) => ({ ...p, betsapi_table_tennis_forecast_tolerance_minutes: e.target.value }))} className="mt-1 w-full rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-white" />
                      </label>
                    </div>
                    <textarea
                      value={nnEnvBlock}
                      readOnly
                      rows={14}
                      className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-200"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={nnApplyLoading}
                        onClick={async () => {
                          try {
                            setNnApplyLoading(true);
                            const r = await putAdminApplyNnEnv(nnEnvValues);
                            setNnEditorCopied(`${r.message} (${r.updated} изменено, ${r.appended} добавлено)`);
                          } catch (e) {
                            setNnEditorCopied(e instanceof Error ? e.message : "Ошибка применения .env");
                          } finally {
                            setNnApplyLoading(false);
                          }
                        }}
                        className="rounded border border-emerald-600/70 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-950/30 disabled:opacity-50"
                      >
                        {nnApplyLoading ? "Применение..." : "Применить в .env автоматически"}
                      </button>
                      <button
                        type="button"
                        disabled={nnApplyRestartLoading}
                        onClick={async () => {
                          if (!confirm("Применить NN настройки в .env и перезапустить backend + tt_workers?")) return;
                          try {
                            setNnApplyRestartLoading(true);
                            const r = await putAdminApplyNnEnvAndRestart(nnEnvValues);
                            setNnEditorCopied(`${r.message} (${r.updated} изменено, ${r.appended} добавлено)`);
                          } catch (e) {
                            setNnEditorCopied(e instanceof Error ? e.message : "Ошибка применения/перезапуска");
                          } finally {
                            setNnApplyRestartLoading(false);
                          }
                        }}
                        className="rounded border border-amber-600/70 px-2 py-1 text-xs text-amber-200 hover:bg-amber-950/30 disabled:opacity-50"
                      >
                        {nnApplyRestartLoading ? "Применение + рестарт..." : "Применить и перезапустить backend+tt_workers"}
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(nnEnvBlock);
                            setNnEditorCopied("Блок .env скопирован");
                          } catch {
                            setNnEditorCopied("Не удалось скопировать автоматически");
                          }
                        }}
                        className="rounded border border-fuchsia-600/70 px-2 py-1 text-xs text-fuchsia-200 hover:bg-fuchsia-950/40"
                      >
                        Скопировать блок .env
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const cfg = mlV2Status.v2_config;
                          if (!cfg) return;
                          setNnEditorDraft({
                            ml_v2_enable_nn: String(Boolean(cfg.ml_v2_enable_nn)),
                            betsapi_table_tennis_nn_allow_hard_confidence_fallback: String(
                              Boolean(cfg.betsapi_table_tennis_nn_allow_hard_confidence_fallback)
                            ),
                            betsapi_table_tennis_forecast_tolerance_minutes: String(cfg.betsapi_table_tennis_forecast_tolerance_minutes ?? 5),
                            betsapi_table_tennis_forecast_window_min_minutes_before: String(cfg.betsapi_table_tennis_forecast_window_min_minutes_before ?? 1),
                            betsapi_table_tennis_forecast_ml_max_minutes_before: String(cfg.betsapi_table_tennis_forecast_ml_max_minutes_before ?? 60),
                            betsapi_table_tennis_nn_forecast_interval_sec: String(cfg.betsapi_table_tennis_nn_forecast_interval_sec ?? 60),
                            betsapi_table_tennis_nn_min_confidence_to_publish: String(cfg.betsapi_table_tennis_nn_min_confidence_to_publish ?? 0),
                            betsapi_table_tennis_nn_min_match_confidence_pct: String(cfg.betsapi_table_tennis_nn_min_match_confidence_pct ?? 0),
                            betsapi_table_tennis_nn_min_set1_confidence_pct: String(cfg.betsapi_table_tennis_nn_min_set1_confidence_pct ?? 0),
                            ml_v2_nn_hidden_layers: String(cfg.ml_v2_nn_hidden_layers ?? "128,64"),
                            ml_v2_nn_learning_rate: String(cfg.ml_v2_nn_learning_rate ?? 0.001),
                            ml_v2_nn_alpha: String(cfg.ml_v2_nn_alpha ?? 0.0001),
                            ml_v2_nn_batch_size: String(cfg.ml_v2_nn_batch_size ?? 256),
                            ml_v2_nn_max_iter: String(cfg.ml_v2_nn_max_iter ?? 120),
                          });
                          setNnEditorCopied("Черновик сброшен к текущим значениям");
                        }}
                        className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-300 hover:bg-slate-900/60"
                      >
                        Сбросить к текущим
                      </button>
                      {nnEditorCopied && <span className="text-xs text-slate-400">{nnEditorCopied}</span>}
                    </div>
                  </div>
                  {mlV2Status.v2_meta && (mlV2Status.v2_meta as { experience_regimes?: boolean; bucket_train_counts?: Record<number, number> }).experience_regimes ? (
                    <p className="text-slate-400">
                      bucket counts: {JSON.stringify((mlV2Status.v2_meta as { bucket_train_counts?: Record<number, number> }).bucket_train_counts ?? {})}
                    </p>
                  ) : null}
                </div>
              )}
        </div>
          )}
        </div>
        {mlV2Status && (mlV2Status.delta_main_minus_ch_matches ?? 0) > 0 && (
          <div className="rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200 mb-4">
            <strong>ML v2 не синхронизирована с main.</strong> Нажмите «Все матчи» для догонки finished матчей в ClickHouse.
          </div>
        )}
        {mlV2Status && (mlV2Status.delta_ch_matches_minus_features ?? 0) > 0 && (
          <div className="rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200 mb-4">
            <strong>Не все фичи построены.</strong> Нажмите «Backfill фичей» для догонки пропущенных матчей (исторические gaps тоже закрываются).
          </div>
        )}
        {mlV2Status && (mlV2Status.match_sets_gap_alert === true) && (
          <div className="rounded-lg border border-amber-600/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-200 mb-4">
            <p className="mb-2">
              <strong>Есть разрыв по сетовой детализации.</strong> В <code className="bg-amber-900/50 px-1 rounded">ml.match_sets</code> не хватает {Math.max(0, mlV2Status.delta_ch_matches_minus_match_sets ?? 0).toLocaleString()} матчей ({Number(mlV2Status.match_sets_gap_pct ?? 0).toFixed(2)}% от <code className="bg-amber-900/50 px-1 rounded">ml.matches</code>). Данные подтягиваются из main DB (live_sets_score, live_score).
            </p>
            {matchSetsBackfillResult != null && <p className="mb-2 text-amber-100">{matchSetsBackfillResult}</p>}
            <button
              type="button"
              disabled={matchSetsBackfillLoading}
              onClick={async () => {
                try {
                  setMatchSetsBackfillLoading(true);
                  setMatchSetsBackfillResult(null);
                  const r = await postAdminMlV2BackfillMatchSets(10000);
                  setMatchSetsBackfillResult(`Готово: заполнено матчей ${r.filled.toLocaleString()}, сетов вставлено ${r.sets_inserted.toLocaleString()}, осталось без сетов: ${r.remaining.toLocaleString()}. Нажмите «Обновить» для актуального статуса.`);
                  const v2 = await getAdminMlV2Status().catch(() => null);
                  if (v2) setMlV2Status(v2);
                } catch (e) {
                  setMatchSetsBackfillResult(e instanceof Error ? e.message : "Ошибка backfill");
                } finally {
                  setMatchSetsBackfillLoading(false);
                }
              }}
              className="rounded bg-amber-700 px-3 py-1.5 text-sm text-white hover:bg-amber-600 disabled:opacity-50"
              title="Дозаполнить ml.match_sets из основной БД (до 10 000 матчей за раз). При необходимости нажмите несколько раз или запустите sync/backfill в воркере."
            >
              {matchSetsBackfillLoading ? "Backfill match_sets…" : "Запустить backfill match_sets"}
            </button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {mlV2Status && (
            <span className="text-slate-300 text-sm">
              Матчей CH: {(mlV2Status.tables?.matches ?? 0).toLocaleString()}, с фичами: {(mlV2Status.tables?.match_features ?? 0).toLocaleString()}
              , player_match_stats: {(mlV2Status.tables?.player_match_stats ?? 0).toLocaleString()}
              , elo_history: {(mlV2Status.tables?.player_elo_history ?? 0).toLocaleString()}
            </span>
          )}
          {false && <button
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
          </button>}
          {false && <button
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
          </button>}
          <button
            type="button"
            onClick={async () => {
              try {
                const [progress, v2] = await Promise.all([
                  getAdminMlProgress().catch(() => null),
                  getAdminMlV2Status().catch(() => null),
                ]);
                if (progress) setMlProgress(progress);
                if (v2) setMlV2Status(v2);
              } catch {
                // ignore
              }
            }}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800"
            title="Обновить v2 статус и прогресс."
          >
            Обновить
          </button>
          {false && <button
            type="button"
            onClick={() => getAdminMlVerify().then(setMlVerify).catch(() => setMlVerify(null))}
            className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800"
            title="Сравнить main и ML: сколько матчей/игроков/лиг не хватает в ML."
          >
            Проверить main→ML
          </button>}
          {false && <button
            type="button"
            onClick={async () => {
              try {
                setMlAuditResult(null);
                const r = await getAdminMlSyncAudit({ sample_limit: 5000, missing_preview: 20 });
                setMlAudit(r);
                setMlAuditResult(
                  r.recent_missing_count > 0
                    ? `Сверка: найдено пропусков в последних ${r.recent_sample_checked.toLocaleString()} матчах: ${r.recent_missing_count}`
                    : `Сверка: пропусков не найдено (последние ${r.recent_sample_checked.toLocaleString()} матчей).`
                );
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-indigo-600/70 px-2 py-1 text-xs text-indigo-300 hover:bg-indigo-950/40"
            title="Ручная полная сверка main↔ML с проверкой последних матчей."
          >
            Полная сверка ML
          </button>}
          {false && <button
            type="button"
            onClick={async () => {
              try {
                const r = await postAdminMlRequestFullSync();
                setMlAuditResult(r.message || "Флаг full sync установлен.");
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-fuchsia-600/70 px-2 py-1 text-xs text-fuchsia-300 hover:bg-fuchsia-950/40"
            title="Поставить флаг: следующий цикл ml_sync_loop выполнит полный sync."
          >
            Запросить full sync
          </button>}
          {false && <button
            type="button"
            onClick={async () => {
              if (!confirm("Удалить все прогнозы V2, статистику каналов (free/vip/no_ml) и сбросить денормализованные поля? Прогнозы будут заново рассчитаны в следующих циклах.")) return;
              try {
                const r = await postAdminForecastsClearAll();
                setMlAuditResult(r.message || "Готово. " + JSON.stringify(r.deleted ?? {}));
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-red-600/70 px-2 py-1 text-xs text-red-300 hover:bg-red-950/40"
            title="Удалить все прогнозы и статистику во всех каналах. Механизм расчёта пересчитает и покажет заново."
          >
            Удалить все прогнозы и статистику
          </button>}
          {false && <button
            type="button"
            disabled={mlProgress?.odds_backfill?.status === "running"}
            onClick={async () => {
              try {
                const r = await postAdminMlOddsBackfillBg({ limit: 5000, batches: 100, pause_ms: 600 });
                setMlAuditResult(r.message || "Фоновая догрузка odds добавлена в очередь.");
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-cyan-600/70 px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-950/40 disabled:opacity-50"
            title="Фоновая догрузка коэффициентов odds батчами с курсором и fallback через BetsAPI."
          >
            {mlProgress?.odds_backfill?.status === "running" ? "Догрузка odds…" : "Фоновая догрузка odds"}
          </button>}
          <button
            type="button"
            onClick={async () => {
              try {
                await postAdminMlResetProgress();
                const [progress, v2] = await Promise.all([
                  getAdminMlProgress().catch(() => null),
                  getAdminMlV2Status().catch(() => null),
                ]);
                if (progress) setMlProgress(progress);
                if (v2) setMlV2Status(v2);
              } catch {
                // ignore
              }
            }}
            className="rounded border border-amber-600/60 px-2 py-1 text-xs text-amber-300 hover:bg-amber-950/40"
            title="Сбросить зависший прогресс (retrain/sync в статусе running)."
          >
            Сбросить прогресс
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!confirm("Очистить только ML прогнозы и ML статистику? no_ml не будет затронут.")) return;
              try {
                const r = await postAdminForecastsClearMl();
                setMlAuditResult(r.message || `Готово: ${JSON.stringify(r.deleted ?? {})}`);
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-rose-700/70 px-2 py-1 text-xs text-rose-300 hover:bg-rose-950/40"
            title="Удалить только ML прогнозы и ML статистику (paid/free/vip/bot_signals)."
          >
            Очистить ML статистику
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!confirm("Очистить только no_ml прогнозы и no_ml статистику? ML не будет затронут.")) return;
              try {
                const r = await postAdminForecastsClearNoMl();
                setMlAuditResult(r.message || `Готово: ${JSON.stringify(r.deleted ?? {})}`);
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-fuchsia-700/70 px-2 py-1 text-xs text-fuchsia-300 hover:bg-fuchsia-950/40"
            title="Удалить только no_ml прогнозы и no_ml статистику."
          >
            Очистить no-ML статистику
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!confirm("Очистить только NN прогнозы и NN статистику? ML/no_ml не будут затронуты.")) return;
              try {
                const r = await postAdminForecastsClearNn();
                setMlAuditResult(r.message || `Готово: ${JSON.stringify(r.deleted ?? {})}`);
              } catch (e) {
                setMlAuditResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded border border-violet-700/70 px-2 py-1 text-xs text-violet-300 hover:bg-violet-950/40"
            title="Удалить только nn прогнозы и nn статистику."
          >
            Очистить NN статистику
          </button>
          {mlSyncPlayersResult && <span className="text-xs text-slate-400">{mlSyncPlayersResult}</span>}
          {mlAuditResult && <span className="text-xs text-slate-400">{mlAuditResult}</span>}
        </div>
        <div className="rounded-lg border border-amber-700/50 bg-amber-950/20 p-4 mb-4">
          <h3 className="font-semibold text-amber-200 mb-2">Загрузить результаты матчей</h3>
          <p className="text-xs text-slate-400 mb-3">
            Загрузка завершённых матчей из архива BetsAPI в main DB. Укажите дату или диапазон дат (YYYY-MM-DD).
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-slate-300">
              С
              <input
                type="date"
                value={archiveLoadDateFrom}
                onChange={(e) => setArchiveLoadDateFrom(e.target.value)}
                className="ml-2 rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-white"
              />
            </label>
            <label className="text-sm text-slate-300">
              По
              <input
                type="date"
                value={archiveLoadDateTo}
                onChange={(e) => setArchiveLoadDateTo(e.target.value)}
                className="ml-2 rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-sm text-white"
              />
            </label>
            <button
              type="button"
              disabled={archiveLoadLoading || !archiveLoadDateFrom.trim()}
              onClick={async () => {
                const from = archiveLoadDateFrom.trim();
                if (!from) return;
                const to = archiveLoadDateTo.trim() || from;
                const dateFromYmd = from.replace(/-/g, "");
                const dateToYmd = to.replace(/-/g, "");
                setArchiveLoadLoading(true);
                setArchiveLoadResult(null);
                try {
                  const r = await postAdminMlLoadArchive({ date_from: dateFromYmd, date_to: dateToYmd });
                  if (!r.ok) setArchiveLoadResult("Ошибка");
                  else {
                    setArchiveLoadResult(`Добавлено: ${r.inserted ?? 0}, обновлено: ${r.updated ?? 0}, пропущено: ${r.skipped ?? 0}`);
                    await getAdminMlVerify().then(setMlVerify).catch(() => {});
                  }
                } catch (e) {
                  setArchiveLoadResult(e instanceof Error ? e.message : "Ошибка");
                } finally {
                  setArchiveLoadLoading(false);
                }
              }}
              className="rounded bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
            >
              {archiveLoadLoading ? "Загрузка…" : "Загрузить"}
            </button>
            {archiveLoadResult && (
              <span className="text-sm text-slate-300">{archiveLoadResult}</span>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-violet-700/50 bg-violet-950/20 p-4 mb-4">
          <h3 className="font-semibold text-violet-200 mb-2">Статистика Аналитики без ML</h3>
          <p className="text-xs text-slate-400 mb-3">
            Угадано / не угадано по каналу no_ml; серии подряд не угадано; лиги с % &lt; 50% и где ошибок больше чем угадываний.
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <button
              type="button"
              onClick={async () => {
                try {
                  const data = await getAdminMlNoMlStats();
                  setMlNoMlStats(data);
                } catch {
                  setMlNoMlStats(null);
                }
              }}
              className="rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
            >
              Обновить
            </button>
          </div>
          {mlNoMlStats && (
            <div className="text-sm">
              <p className="text-slate-300 mb-2">
                Всего: <span className="text-emerald-400 font-medium">{mlNoMlStats.total_hit}</span> угадано,{" "}
                <span className="text-rose-400 font-medium">{mlNoMlStats.total_miss}</span> не угадано
                {mlNoMlStats.total_hit + mlNoMlStats.total_miss > 0 && (
                  <span className="text-slate-400 ml-1">
                    ({((mlNoMlStats.total_hit / (mlNoMlStats.total_hit + mlNoMlStats.total_miss)) * 100).toFixed(1)}% попаданий)
                  </span>
                )}
              </p>
              {mlNoMlStats.streaks && (
                <p className="text-slate-300 mb-2">
                  Серии: макс. не угадано подряд{" "}
                  <span className="text-rose-400 font-medium">{mlNoMlStats.streaks.max_streak_miss}</span>
                  {mlNoMlStats.streaks.current_streak_miss > 0 && (
                    <>
                      , текущая серия не угадано{" "}
                      <span className="text-rose-400 font-medium">{mlNoMlStats.streaks.current_streak_miss}</span>
                    </>
                  )}
                  {mlNoMlStats.streaks.max_streak_hit > 0 && (
                    <>
                      {" "}
                      · макс. угадано подряд <span className="text-emerald-400 font-medium">{mlNoMlStats.streaks.max_streak_hit}</span>
                    </>
                  )}
                </p>
              )}
              {mlNoMlStats.leagues_bad.length > 0 ? (
                <div className="mb-4">
                  <p className="text-amber-200 font-medium mb-2">
                    Лиги, где ошибок больше чем угадываний ({mlNoMlStats.leagues_bad.length}):
                  </p>
                  <div className="overflow-x-auto rounded border border-slate-700">
                    <table className="w-full text-xs">
            <thead>
                        <tr className="border-b border-slate-700 bg-slate-800/60 text-slate-300 text-left">
                          <th className="px-2 py-1.5 font-medium">Лига</th>
                          <th className="px-2 py-1.5 font-medium text-right">Угадано</th>
                          <th className="px-2 py-1.5 font-medium text-right">Не угадано</th>
                          <th className="px-2 py-1.5 font-medium text-right">% попаданий</th>
              </tr>
            </thead>
            <tbody>
                        {mlNoMlStats.leagues_bad.map((l) => (
                          <tr key={l.league_id} className="border-b border-slate-700/60">
                            <td className="px-2 py-1.5 text-slate-200">{l.league_name || l.league_id}</td>
                            <td className="px-2 py-1.5 text-right text-emerald-400">{l.hit}</td>
                            <td className="px-2 py-1.5 text-right text-rose-400">{l.miss}</td>
                            <td className="px-2 py-1.5 text-right text-slate-400">{l.hit_rate_pct != null ? `${l.hit_rate_pct}%` : "—"}</td>
                          </tr>
                        ))}
            </tbody>
          </table>
        </div>
                </div>
              ) : (
                <p className="text-slate-400 mb-4">
                  {mlNoMlStats.by_league.length === 0
                    ? "Нет данных по каналу no_ml (hit/miss)."
                    : "Нет лиг, где ошибок больше чем угадываний."}
                </p>
              )}
              {mlNoMlStats.leagues_weak && mlNoMlStats.leagues_weak.length > 0 && (
                <div className="mb-4">
                  <p className="text-amber-200/90 font-medium mb-2">
                    Лиги с низким % попаданий (&lt;50%, минимум 5 исходов) — кандидаты на исключение или инверт:
                  </p>
                  <div className="overflow-x-auto rounded border border-slate-700">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-700 bg-slate-800/60 text-slate-300 text-left">
                          <th className="px-2 py-1.5 font-medium">Лига</th>
                          <th className="px-2 py-1.5 font-medium text-right">Угадано</th>
                          <th className="px-2 py-1.5 font-medium text-right">Не угадано</th>
                          <th className="px-2 py-1.5 font-medium text-right">%</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mlNoMlStats.leagues_weak.map((l) => (
                          <tr key={l.league_id} className="border-b border-slate-700/60">
                            <td className="px-2 py-1.5 text-slate-200">{l.league_name || l.league_id}</td>
                            <td className="px-2 py-1.5 text-right text-emerald-400">{l.hit}</td>
                            <td className="px-2 py-1.5 text-right text-rose-400">{l.miss}</td>
                            <td className="px-2 py-1.5 text-right text-amber-300">{l.hit_rate_pct != null ? `${l.hit_rate_pct}%` : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              <div className="rounded border border-slate-600 bg-slate-900/50 p-3 text-xs text-slate-400">
                <p className="font-medium text-slate-300 mb-1">Как повысить % угадывания no_ML:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li><strong>Инверт</strong> — для лиги выдаём противоположный выбор (П1→П2, П2→П1). В <code className="bg-slate-800 px-1 rounded">.env</code>: <code className="bg-slate-800 px-1 rounded">BETSAPI_TABLE_TENNIS_NO_ML_INVERT_PICK_LEAGUE_NAMES=Czech Liga Pro,Другая лига</code></li>
                  <li><strong>Исключение</strong> — для лиги не выдаём прогноз вообще. В <code className="bg-slate-800 px-1 rounded">.env</code>: <code className="bg-slate-800 px-1 rounded">BETSAPI_TABLE_TENNIS_NO_ML_EXCLUDE_LEAGUE_NAMES=Название лиги 1,Название лиги 2</code></li>
                  <li>Значения — подстрока в названии лиги, через запятую. После изменения перезапустите tt_workers.</li>
                </ul>
              </div>
            </div>
          )}
        </div>
        <MlProgressBar op="full_rebuild" label="Full rebuild (всё за раз)" progress={mlProgress?.full_rebuild ?? null} />
        <MlProgressBar op="sync" label="Синхронизация" progress={mlProgress?.sync ?? null} />
        <MlProgressBar op="backfill" label="Backfill фичей" progress={mlProgress?.backfill ?? null} />
        {false && <MlProgressBar op="odds_backfill" label="Догрузка odds (фон)" progress={mlProgress?.odds_backfill ?? null} />}
        {false && <MlProgressBar op="player_stats" label="Player stats (daily, style, elo_history)" progress={mlProgress?.player_stats ?? null} />}
        {false && <MlProgressBar op="league_performance" label="League performance" progress={mlProgress?.league_performance ?? null} />}
        <MlProgressBar op="retrain" label="Переобучение моделей" progress={mlProgress?.retrain ?? null} />
        <div className="flex flex-wrap gap-4 mb-4">
          <div className="flex flex-wrap items-center gap-3">
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
                    await getAdminMlProgress().then(setMlProgress).catch(() => {});
                    await getAdminMlV2Status().then(setMlV2Status).catch(() => {});
                  }
                } catch (e) {
                  setMlSyncResult(e instanceof Error ? e.message : "Ошибка");
                }
              }}
              className="rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              title="Полный цикл v2: sync → rebuild features → retrain → KPI."
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
                    await getAdminMlV2Status().then(setMlV2Status).catch(() => {});
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
                    await getAdminMlV2Status().then(setMlV2Status).catch(() => {});
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
        {false && <div className="flex flex-wrap items-center gap-3 mb-3">
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
                else await getAdminMlV2Status().then(setMlV2Status).catch(() => {});
              } catch (e) {
                setMlBackfillResult(e instanceof Error ? e.message : "Ошибка");
              }
            }}
            className="rounded bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {mlProgress?.backfill?.status === "running" ? "Расчёт…" : "Backfill фичей"}
          </button>
        </div>}
        {mlBackfillResult && <p className="text-sm text-slate-300 mb-3">{mlBackfillResult}</p>}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <button
            type="button"
            disabled={mlProgress?.player_stats?.status === "running"}
            onClick={async () => {
              try {
                const r = await postAdminMlPlayerStats({ limit: 10000 });
                if (!r.ok) setMlBackfillResult(r.error ?? "Ошибка");
                else await getAdminMlV2Status().then(setMlV2Status).catch(() => {});
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
                if (!r.ok) {
                  setMlRetrainResult(r.error ?? "Ошибка");
                } else {
                  setMlRetrainResult(r.message ?? "Задача добавлена в очередь. Переобучение на GPU выполнит ml_worker (5–15 мин).");
                  getAdminMlV2Status().then(setMlV2Status).catch(() => {});
                }
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
        <p className="text-xs text-slate-500 mt-2">
          По кнопке — переобучение на GPU через контейнер ml_worker (очередь каждые 5 сек). Автоматически — раз в 30 мин (ML_RETRAIN_INTERVAL_SEC=1800). Убедитесь, что ml_worker запущен: <code className="bg-slate-800 px-1 rounded">docker compose ps</code>.
        </p>
      </section>

      <section className={`${activeTab === "bot_info" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Сообщение бота «Получить информацию» <HintBadge text="Текст ответа основного Telegram-бота на кнопку получения информации." /></h2>
        <p className="text-slate-400 text-sm mb-2">
          Текст, который видят пользователи в Telegram-боте при нажатии на кнопку «Получить информацию».
        </p>
        <textarea
          value={botInfoMessage}
          onChange={(e) => setBotInfoMessage(e.target.value)}
          rows={6}
          placeholder="Введите сообщение для бота..."
          title="Текст ответа в основном Telegram-боте для кнопки «Получить информацию»."
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
          title="Сохранить текст сообщения бота."
        >
          {botInfoSaving ? "Сохранение…" : "Сохранить"}
        </button>
      </section>

      <section className={`${activeTab === "schedules" ? "block" : "hidden"} rounded-xl border border-slate-800 bg-slate-900/40 p-4`}>
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Настройка расписаний ботов (JSON) <HintBadge text="Настройка, когда и из какого источника отправлять прогнозы в каналы." /></h2>
        <p className="text-slate-400 text-sm mb-2">
          Полностью настраиваемые правила `откуда/сколько/куда`: слоты для FREE и PAID/ML, stream с группировкой для NO_ML, daily summary.
        </p>
        <DispatchConfigHelp />
        <DispatchConfigPreview cfgText={dispatchCfgText} />
        {dispatchCfgObj ? (
          <div className="my-3 grid gap-3 md:grid-cols-2">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p className="mb-2 font-medium text-slate-200 inline-flex items-center gap-2">
                FREE: слоты
                <HintBadge text="Расписание отправок в бесплатный канал. Каждый слот: время (MSK), источник и количество прогнозов." />
              </p>
              <div className="mb-2 grid grid-cols-3 gap-2">
                <label className="flex items-center gap-2" title="Включает/выключает отправки в FREE канал.">
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
                <div className="inline-flex items-center gap-1 text-slate-300">
                  <span>enabled</span>
                  <HintBadge text="Если выключено, FREE-слоты полностью игнорируются." />
                </div>
                <label title="Минимум минут до старта матча, чтобы прогноз можно было отправить.">
                  <span className="inline-flex items-center gap-1">
                    min_lead
                    <HintBadge text="Минимальный запас времени до старта матча (в минутах)." />
                  </span>
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
                <label title="Час в UTC для суточной статистики, пусто — выключено.">
                  <span className="inline-flex items-center gap-1">
                    summary UTC
                    <HintBadge text="Час (0-23) отправки суточной сводки; пусто = выключено." />
                  </span>
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
                      title="Время отправки слота в формате HH:MM (MSK)."
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
                      value={String(slot.source ?? "paid")}
                      title="Источник прогнозов для слота: paid, no_ml или nn."
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
                      <option value="nn">nn</option>
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={Number(slot.count ?? 1)}
                      title="Сколько прогнозов отправлять в этот слот."
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
                      title="Удалить слот расписания."
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
                title="Добавить новый слот в FREE канал."
                onClick={() =>
                  updateDispatchCfg((cfg) => {
                    const free = (cfg.free as Record<string, unknown>) || {};
                    const slots = Array.isArray(free.slots) ? ([...free.slots] as Array<Record<string, unknown>>) : [];
                    slots.push({ time_msk: "11:00", source: "paid", count: 1 });
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
              <p className="mb-2 font-medium text-slate-200 inline-flex items-center gap-2">
                PAID/ML: слоты
                <HintBadge text="Расписание отправок в платный ML-канал. Для каждого слота задайте время, источник и количество." />
              </p>
              <div className="mb-2 grid grid-cols-3 gap-2">
                <label className="flex items-center gap-2" title="Включает/выключает отправки в PAID/ML канал.">
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
                <div className="inline-flex items-center gap-1 text-slate-300">
                  <span>enabled</span>
                  <HintBadge text="Если выключено, PAID/ML-слоты полностью игнорируются." />
                </div>
                <label title="Минимум минут до старта матча, чтобы прогноз можно было отправить.">
                  <span className="inline-flex items-center gap-1">
                    min_lead
                    <HintBadge text="Минимальный запас времени до старта матча (в минутах)." />
                  </span>
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
                <label title="Час в UTC для суточной статистики, пусто — выключено.">
                  <span className="inline-flex items-center gap-1">
                    summary UTC
                    <HintBadge text="Час (0-23) отправки суточной сводки; пусто = выключено." />
                  </span>
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
                      title="Время отправки слота в формате HH:MM (MSK)."
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
                      value={String(slot.source ?? "paid")}
                      title="Источник прогнозов для слота: paid, no_ml или nn."
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
                      <option value="nn">nn</option>
                    </select>
                    <input
                      type="number"
                      min={1}
                      value={Number(slot.count ?? 1)}
                      title="Сколько прогнозов отправлять в этот слот."
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
                      title="Удалить слот расписания."
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
                title="Добавить новый слот в PAID/ML канал."
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
              <p className="mb-2 font-medium text-slate-200 inline-flex items-center gap-2">
                NO_ML: поток с группировкой
                <HintBadge text="Потоковая отправка новых прогнозов в канал no_ml пачками по интервалу." />
              </p>
              <div className="mb-2 grid gap-2 md:grid-cols-4">
                <label className="flex items-center gap-2" title="Включает/выключает весь канал NO_ML.">
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
                <div className="inline-flex items-center gap-1 text-slate-300">
                  <span>enabled</span>
                  <HintBadge text="Полностью выключает или включает отправки в NO_ML канал." />
                </div>
                <label className="flex items-center gap-2" title="Включает потоковую отправку в NO_ML канал.">
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
                <div className="inline-flex items-center gap-1 text-slate-300">
                  <span>stream_enabled</span>
                  <HintBadge text="Если выключено, потоковые отправки не выполняются (даже если enabled=true)." />
                </div>
                <label title="Минимум минут до старта матча, чтобы прогноз можно было отправить.">
                  <span className="inline-flex items-center gap-1">
                    min_lead
                    <HintBadge text="Минимальный запас времени до старта матча (в минутах)." />
                  </span>
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
                <label title="Час в UTC для суточной статистики, пусто — выключено.">
                  <span className="inline-flex items-center gap-1">
                    summary UTC
                    <HintBadge text="Час (0-23) отправки суточной сводки; пусто = выключено." />
                  </span>
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
                <label title="Интервал между потоковыми отправками в минутах (не чаще).">
                  <span className="inline-flex items-center gap-1">
                    interval, мин
                    <HintBadge text="Минимальный интервал между двумя отправками потока." />
                  </span>
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
                <label title="Максимум прогнозов в одной отправке.">
                  <span className="inline-flex items-center gap-1">
                    group_limit
                    <HintBadge text="Максимальное число прогнозов в одном пакете отправки." />
                  </span>
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
                <label title="Сколько кандидатов максимум читать из БД за цикл.">
                  <span className="inline-flex items-center gap-1">
                    fetch_limit
                    <HintBadge text="Верхний лимит чтения кандидатов из БД за один цикл." />
                  </span>
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
                <label title="Источник для потока: no_ml, paid или nn.">
                  <span className="inline-flex items-center gap-1">
                    source
                    <HintBadge text="Источник прогнозов: no_ml, paid или nn." />
                  </span>
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
                    <option value="nn">nn</option>
                  </select>
                </label>
              </div>
            </div>
          </div>
        ) : null}
        <textarea
          value={dispatchCfgText}
          onChange={(e) => setDispatchCfgText(e.target.value)}
          title="Расписание в формате JSON. Можно редактировать вручную."
          rows={12}
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white my-2"
        />
        <button
          type="button"
          title="Подставить базовый пример расписания для 3 каналов."
          onClick={() => {
            setDispatchCfgText(JSON.stringify({
              free: {
                enabled: true,
                slots: [
                  { time_msk: "11:00", source: "paid", count: 1 },
                  { time_msk: "15:00", source: "nn", count: 1 },
                  { time_msk: "17:00", source: "no_ml", count: 1 },
                ],
                min_lead_minutes: 60,
                daily_summary_hour_utc: 21,
              },
              vip: {
                enabled: true,
                slots: [
                  { time_msk: "12:00", source: "paid", count: 3 },
                  { time_msk: "16:00", source: "nn", count: 3 },
                  { time_msk: "19:00", source: "no_ml", count: 3 },
                ],
                min_lead_minutes: 60,
                daily_summary_hour_utc: 23,
              },
              no_ml_channel: {
                enabled: true,
                stream_enabled: true,
                stream_interval_minutes: 30,
                stream_source: "nn",
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
          title="Сохранить расписание в базу данных."
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
        <h2 className="text-lg text-white mb-3 flex items-center gap-2">Рассылки (каналы / бот / email) <HintBadge text="Ручная рассылка в канал, конкретному пользователю, всем пользователям бота или на email." /></h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-300">
            Куда
            <select
              value={messageTarget}
              onChange={(e) => setMessageTarget(e.target.value as "free_channel" | "vip_channel" | "no_ml_channel" | "telegram_user" | "telegram_all_users" | "email")}
              title="Тип получателя: канал, один пользователь, все пользователи бота или email."
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
              <input value={messageUserId} onChange={(e) => setMessageUserId(e.target.value)} title="UUID пользователя для точечной отправки в Telegram." className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
            </label>
          ) : null}
          {messageTarget === "email" ? (
            <>
              <label className="text-sm text-slate-300">
                Email
                <input value={messageEmail} onChange={(e) => setMessageEmail(e.target.value)} title="Email получателя для рассылки." className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
              </label>
              <label className="text-sm text-slate-300">
                Тема
                <input value={messageSubject} onChange={(e) => setMessageSubject(e.target.value)} title="Тема email-сообщения." className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
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
            title="Основной текст рассылки. Поддерживается HTML-формат Telegram на стороне API."
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
          />
        </label>
        <label className="mt-3 block text-sm text-slate-300">
          Картинка (URL, опционально)
          <input
            value={messageImageUrl}
            onChange={(e) => setMessageImageUrl(e.target.value)}
            placeholder="https://..."
            title="Одна ссылка на изображение для отправки вместе с текстом."
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
            title="Несколько ссылок на изображения, по одной в строке."
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
          title="Отправить сообщение по выбранному target."
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
