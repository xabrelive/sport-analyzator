"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  createAdminPaymentMethod,
  deleteAdminPaymentMethod,
  getAdminInvoices,
  getAdminMe,
  getAdminPaymentMethods,
  getAdminProducts,
  getAdminTelegramBotInfo,
  getAdminUsers,
  patchAdminInvoiceStatus,
  patchAdminPaymentMethod,
  patchAdminProduct,
  patchAdminUser,
  putAdminTelegramBotInfo,
  sendAdminMessage,
  type AdminInvoiceItem,
  type AdminPaymentMethod,
  type AdminProduct,
  type AdminUserListItem,
} from "@/lib/api";

function moneyCompact(v: number): string {
  const rounded = Math.round(v * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
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

export default function AdminPage() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  const [messageTarget, setMessageTarget] = useState<"free_channel" | "vip_channel" | "telegram_user" | "email">("free_channel");
  const [messageText, setMessageText] = useState("");
  const [messageUserId, setMessageUserId] = useState("");
  const [messageEmail, setMessageEmail] = useState("");
  const [messageSubject, setMessageSubject] = useState("Сообщение от PingWin");

  const [newMethodName, setNewMethodName] = useState("");
  const [newMethodType, setNewMethodType] = useState<"custom" | "card" | "crypto">("custom");
  const [newMethodInstructions, setNewMethodInstructions] = useState("");

  const [botInfoMessage, setBotInfoMessage] = useState("");
  const [botInfoSaving, setBotInfoSaving] = useState(false);

  const pageSize = 20;
  const totalPages = useMemo(() => Math.max(1, Math.ceil(usersTotal / pageSize)), [usersTotal]);
  const currentPage = useMemo(() => Math.floor(usersOffset / pageSize) + 1, [usersOffset]);

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

  if (allowed === null) {
    return <div className="p-6 text-slate-400">Загрузка админки…</div>;
  }
  if (!allowed) {
    return <div className="p-6 text-rose-300">Доступ запрещён. {error || ""}</div>;
  }

  return (
    <div className="p-4 md:p-6 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-white">Админка</h1>
        <p className="text-slate-400 mt-1">Управление пользователями, подписками, тарифами, платёжками и рассылками.</p>
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
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

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="text-lg text-white mb-3">Рассылки (каналы / бот / email)</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-300">
            Куда
            <select
              value={messageTarget}
              onChange={(e) => setMessageTarget(e.target.value as "free_channel" | "vip_channel" | "telegram_user" | "email")}
              className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            >
              <option value="free_channel">FREE канал</option>
              <option value="vip_channel">VIP канал</option>
              <option value="telegram_user">Пользователь в Telegram</option>
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
        <button
          type="button"
          disabled={sending || !messageText.trim()}
          onClick={async () => {
            try {
              setSending(true);
              setError(null);
              await sendAdminMessage({
                target: messageTarget,
                text: messageText,
                user_id: messageUserId || undefined,
                email: messageEmail || undefined,
                subject: messageSubject || undefined,
              });
              setMessageText("");
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
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
      </section>
    </div>
  );
}
