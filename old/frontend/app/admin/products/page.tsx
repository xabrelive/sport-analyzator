"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminProducts,
  updateAdminProduct,
  type AdminProduct,
} from "@/lib/api";

export default function AdminProductsPage() {
  const [items, setItems] = useState<AdminProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formSortOrder, setFormSortOrder] = useState(0);
  const [saveLoading, setSaveLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchAdminProducts();
      setItems(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = (p: AdminProduct) => {
    setEditingId(p.id);
    setFormName(p.name);
    setFormEnabled(p.enabled);
    setFormSortOrder(p.sort_order);
  };

  const cancelForm = () => setEditingId(null);

  const handleSave = async () => {
    if (!editingId) return;
    setSaveLoading(true);
    try {
      await updateAdminProduct(editingId, {
        name: formName.trim(),
        enabled: formEnabled,
        sort_order: formSortOrder,
      });
      cancelForm();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaveLoading(false);
    }
  };

  const toggleEnabled = async (p: AdminProduct) => {
    try {
      await updateAdminProduct(p.id, { enabled: !p.enabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <div>
      <h1 className="text-xl font-semibold text-white mb-6">Услуги</h1>
      <p className="text-slate-400 text-sm mb-6">
        Включённые услуги отображаются на странице тарифов. Можно изменить название, порядок и включить или выключить показ.
      </p>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      {(editingId && items.find((p) => p.id === editingId)) && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-6 mb-6">
          <h2 className="text-lg font-medium text-white mb-4">Редактирование услуги</h2>
          <div className="space-y-4 max-w-md">
            <p className="text-slate-400 text-sm">
              Ключ: <span className="text-slate-300 font-mono">{items.find((p) => p.id === editingId)?.key}</span>
            </p>
            <label className="block">
              <span className="text-slate-400 text-sm">Название (на странице тарифов)</span>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              />
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={formEnabled} onChange={(e) => setFormEnabled(e.target.checked)} className="rounded" />
              <span className="text-slate-400 text-sm">Включена (показывать на странице тарифов)</span>
            </label>
            <label className="block">
              <span className="text-slate-400 text-sm">Порядок (меньше — выше)</span>
              <input
                type="number"
                value={formSortOrder}
                onChange={(e) => setFormSortOrder(parseInt(e.target.value, 10) || 0)}
                className="mt-1 w-24 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              />
            </label>
            <div className="flex gap-2">
              <button
                onClick={handleSave}
                disabled={saveLoading || !formName.trim()}
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

      {loading ? (
        <p className="text-slate-400">Загрузка…</p>
      ) : (
        <div className="rounded-xl border border-slate-700/50 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/80 text-slate-300">
              <tr>
                <th className="text-left py-3 px-4">Услуга</th>
                <th className="text-left py-3 px-4">Название</th>
                <th className="text-left py-3 px-4">Включена</th>
                <th className="text-left py-3 px-4">Порядок</th>
                <th className="text-left py-3 px-4">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 px-4 text-slate-500 text-center">
                    Нет услуг. После применения миграции здесь появятся «Подписка на аналитику» и «Подписка на приватный канал».
                  </td>
                </tr>
              ) : (
                items.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/40">
                    <td className="py-3 px-4 text-slate-400 font-mono">{p.key}</td>
                    <td className="py-3 px-4 text-white">{p.name}</td>
                    <td className="py-3 px-4">
                      <button
                        type="button"
                        onClick={() => toggleEnabled(p)}
                        className={`rounded px-2 py-1 text-xs font-medium ${p.enabled ? "bg-emerald-900/50 text-emerald-300" : "bg-slate-700 text-slate-400"}`}
                      >
                        {p.enabled ? "Вкл" : "Выкл"}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-slate-400">{p.sort_order}</td>
                    <td className="py-3 px-4">
                      <button type="button" onClick={() => startEdit(p)} className="text-teal-400 hover:text-teal-300">
                        Изменить
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
