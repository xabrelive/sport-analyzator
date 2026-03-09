"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminScheduledPosts,
  createAdminScheduledPost,
  deleteAdminScheduledPost,
  type ScheduledPost,
  type ScheduledPostCreate,
} from "@/lib/api";

const TARGET_LABELS: Record<string, string> = {
  free_channel: "Бесплатный канал",
  paid_channel: "Платный канал",
  bot_dm: "Бот (в личку)",
};

const TEMPLATE_LABELS: Record<string, string> = {
  daily_stats_12: "Утро 12:00 — общая статистика",
  daily_stats_19_sport: "Вечер 19:00 — по видам спорта",
  "": "Свой текст",
};

export default function AdminScheduledPostsPage() {
  const [items, setItems] = useState<ScheduledPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [formName, setFormName] = useState("");
  const [formTarget, setFormTarget] = useState<"free_channel" | "paid_channel" | "bot_dm">("paid_channel");
  const [formTemplateType, setFormTemplateType] = useState("");
  const [formBody, setFormBody] = useState("");
  const [formSendAt, setFormSendAt] = useState("12:00");
  const [formActive, setFormActive] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminScheduledPosts();
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startCreate = () => {
    setIsCreating(true);
    setFormName("");
    setFormTarget("paid_channel");
    setFormTemplateType("daily_stats_12");
    setFormBody("");
    setFormSendAt("12:00");
    setFormActive(true);
  };

  const cancelForm = () => {
    setIsCreating(false);
  };

  const handleSaveCreate = async () => {
    if (!formName.trim()) return;
    if (!formTemplateType.trim() && !formBody.trim()) {
      setError("Укажите тип шаблона или свой текст");
      return;
    }
    setSaveLoading(true);
    setError(null);
    try {
      await createAdminScheduledPost({
        name: formName.trim(),
        target: formTarget,
        template_type: formTemplateType.trim() || null,
        body: formBody.trim() || null,
        send_at_time_msk: formSendAt,
        is_active: formActive,
      });
      cancelForm();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleDelete = async (p: ScheduledPost) => {
    if (!confirm(`Удалить пост «${p.name}»?`)) return;
    try {
      await deleteAdminScheduledPost(p.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  };

  const toggleActive = async (p: ScheduledPost) => {
    try {
      const { updateAdminScheduledPost } = await import("@/lib/api");
      await updateAdminScheduledPost(p.id, { is_active: !p.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <div>
      <h1 className="text-xl font-semibold text-white mb-6">Отложенные посты в Telegram</h1>
      <p className="text-slate-400 text-sm mb-6">
        Расписание рассылки: бесплатный канал, платный канал или бот (в личку подписчикам). Шаблоны «Утро 12:00» и «Вечер 19:00» подставляют статистику за вчера; можно задать свой текст.
      </p>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      {isCreating && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-6 mb-6">
          <h2 className="text-lg font-medium text-white mb-4">Новый пост</h2>
          <div className="space-y-4 max-w-lg">
            <label className="block">
              <span className="text-slate-400 text-sm">Название (для админки)</span>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Например: Статистика 12:00 платный канал"
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              />
            </label>
            <label className="block">
              <span className="text-slate-400 text-sm">Куда отправлять</span>
              <select
                value={formTarget}
                onChange={(e) => setFormTarget(e.target.value as "free_channel" | "paid_channel" | "bot_dm")}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              >
                <option value="free_channel">Бесплатный канал</option>
                <option value="paid_channel">Платный канал</option>
                <option value="bot_dm">Бот (в личку подписчикам)</option>
              </select>
            </label>
            <label className="block">
              <span className="text-slate-400 text-sm">Тип шаблона (или оставьте пустым и введите свой текст)</span>
              <select
                value={formTemplateType}
                onChange={(e) => setFormTemplateType(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              >
                <option value="">— Свой текст —</option>
                <option value="daily_stats_12">Утро 12:00 — общая статистика за вчера</option>
                <option value="daily_stats_19_sport">Вечер 19:00 — по видам спорта за вчера</option>
              </select>
            </label>
            {!formTemplateType && (
              <label className="block">
                <span className="text-slate-400 text-sm">Текст сообщения (HTML для Telegram)</span>
                <textarea
                  value={formBody}
                  onChange={(e) => setFormBody(e.target.value)}
                  rows={6}
                  placeholder="<b>Заголовок</b>&#10;Текст..."
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white font-mono text-sm"
                />
              </label>
            )}
            <label className="block">
              <span className="text-slate-400 text-sm">Время отправки (МСК), HH:MM</span>
              <input
                type="text"
                value={formSendAt}
                onChange={(e) => setFormSendAt(e.target.value)}
                placeholder="12:00"
                className="mt-1 w-24 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white font-mono"
              />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={formActive} onChange={(e) => setFormActive(e.target.checked)} className="rounded" />
              <span className="text-slate-400 text-sm">Активен (рассылать по расписанию)</span>
            </label>
            <div className="flex gap-2">
              <button
                onClick={handleSaveCreate}
                disabled={saveLoading || !formName.trim() || (!formTemplateType && !formBody.trim())}
                className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
              >
                {saveLoading ? "Сохранение…" : "Сохранить"}
              </button>
              <button type="button" onClick={cancelForm} className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}

      {!isCreating && (
        <button
          type="button"
          onClick={startCreate}
          className="mb-6 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600"
        >
          + Добавить пост
        </button>
      )}

      {loading ? (
        <p className="text-slate-400">Загрузка…</p>
      ) : (
        <div className="rounded-xl border border-slate-700/50 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/80 text-slate-300">
              <tr>
                <th className="text-left py-3 px-4">Название</th>
                <th className="text-left py-3 px-4">Куда</th>
                <th className="text-left py-3 px-4">Шаблон</th>
                <th className="text-left py-3 px-4">Время (МСК)</th>
                <th className="text-left py-3 px-4">Активен</th>
                <th className="text-left py-3 px-4">Последняя отправка</th>
                <th className="text-left py-3 px-4">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 px-4 text-slate-500 text-center">
                    Нет отложенных постов. Добавьте первый — например, «Статистика 12:00» с шаблоном «Утро 12:00».
                  </td>
                </tr>
              ) : (
                items.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/40">
                    <td className="py-3 px-4 text-white">{p.name}</td>
                    <td className="py-3 px-4 text-slate-300">{TARGET_LABELS[p.target] ?? p.target}</td>
                    <td className="py-3 px-4 text-slate-300">{TEMPLATE_LABELS[p.template_type ?? ""] ?? (p.template_type || "Свой текст")}</td>
                    <td className="py-3 px-4 text-slate-300 font-mono">{p.send_at_time_msk}</td>
                    <td className="py-3 px-4">
                      <button
                        type="button"
                        onClick={() => toggleActive(p)}
                        className={`rounded px-2 py-1 text-xs font-medium ${p.is_active ? "bg-emerald-900/50 text-emerald-300" : "bg-slate-700 text-slate-400"}`}
                      >
                        {p.is_active ? "Вкл" : "Выкл"}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-slate-400">
                      {p.last_sent_at ? new Date(p.last_sent_at).toLocaleString("ru") : "—"}
                    </td>
                    <td className="py-3 px-4">
                      <Link href={`/admin/scheduled-posts/${p.id}`} className="text-teal-400 hover:text-teal-300 mr-3">
                        Изменить
                      </Link>
                      <button type="button" onClick={() => handleDelete(p)} className="text-rose-400 hover:text-rose-300">
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
