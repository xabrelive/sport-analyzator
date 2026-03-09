"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchAdminScheduledPost, updateAdminScheduledPost, type ScheduledPost } from "@/lib/api";

export default function AdminScheduledPostEditPage() {
  const params = useParams();
  const id = params?.id as string;
  const [post, setPost] = useState<ScheduledPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formName, setFormName] = useState("");
  const [formTarget, setFormTarget] = useState<"free_channel" | "paid_channel" | "bot_dm">("paid_channel");
  const [formTemplateType, setFormTemplateType] = useState("");
  const [formBody, setFormBody] = useState("");
  const [formSendAt, setFormSendAt] = useState("12:00");
  const [formActive, setFormActive] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const p = await fetchAdminScheduledPost(id);
      setPost(p);
      setFormName(p.name);
      setFormTarget(p.target);
      setFormTemplateType(p.template_type ?? "");
      setFormBody(p.body ?? "");
      setFormSendAt(p.send_at_time_msk);
      setFormActive(p.is_active);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !formName.trim()) return;
    if (!formTemplateType.trim() && !formBody.trim()) {
      setError("Укажите тип шаблона или свой текст");
      return;
    }
    setSaveLoading(true);
    setError(null);
    try {
      const updated = await updateAdminScheduledPost(id, {
        name: formName.trim(),
        target: formTarget,
        template_type: formTemplateType.trim() || null,
        body: formBody.trim() || null,
        send_at_time_msk: formSendAt,
        is_active: formActive,
      });
      setPost(updated);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaveLoading(false);
    }
  };

  if (loading) {
    return <p className="text-slate-400">Загрузка…</p>;
  }

  if (!post) {
    return (
      <div>
        <p className="text-rose-400">Пост не найден.</p>
        <Link href="/admin/scheduled-posts" className="text-teal-400 hover:text-teal-300 text-sm mt-2 inline-block">
          ← К списку постов
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link href="/admin/scheduled-posts" className="text-teal-400 hover:text-teal-300 text-sm mb-4 inline-block">
        ← К списку отложенных постов
      </Link>
      <h1 className="text-xl font-semibold text-white mb-6">Редактирование поста</h1>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      <form onSubmit={handleSave} className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-6 max-w-lg space-y-4">
        <label className="block">
          <span className="text-slate-400 text-sm">Название (для админки)</span>
          <input
            type="text"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
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
          <span className="text-slate-400 text-sm">Тип шаблона</span>
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
            className="mt-1 w-24 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white font-mono"
          />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={formActive} onChange={(e) => setFormActive(e.target.checked)} className="rounded" />
          <span className="text-slate-400 text-sm">Активен</span>
        </label>
        <p className="text-slate-500 text-xs">
          Последняя отправка: {post.last_sent_at ? new Date(post.last_sent_at).toLocaleString("ru") : "—"}
        </p>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saveLoading || !formName.trim() || (!formTemplateType && !formBody.trim())}
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
          >
            {saveLoading ? "Сохранение…" : "Сохранить"}
          </button>
          <Link href="/admin/scheduled-posts" className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
            Отмена
          </Link>
        </div>
      </form>
    </div>
  );
}
