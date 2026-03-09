"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchAdminPaymentMethods,
  createAdminPaymentMethod,
  updateAdminPaymentMethod,
  deleteAdminPaymentMethod,
  type AdminPaymentMethod,
  type AdminPaymentMethodCreate,
} from "@/lib/api";

export default function AdminPaymentMethodsPage() {
  const [items, setItems] = useState<AdminPaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState<"yookassa" | "custom">("yookassa");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formSortOrder, setFormSortOrder] = useState(0);
  const [formCustomMessage, setFormCustomMessage] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchAdminPaymentMethods();
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

  const startCreate = () => {
    setIsCreating(true);
    setEditingId(null);
    setFormName("");
    setFormType("yookassa");
    setFormEnabled(true);
    setFormSortOrder(items.length);
    setFormCustomMessage("");
  };

  const startEdit = (pm: AdminPaymentMethod) => {
    setEditingId(pm.id);
    setIsCreating(false);
    setFormName(pm.name);
    setFormType(pm.type as "yookassa" | "custom");
    setFormEnabled(pm.enabled);
    setFormSortOrder(pm.sort_order);
    setFormCustomMessage(pm.custom_message || "");
  };

  const cancelForm = () => {
    setEditingId(null);
    setIsCreating(false);
  };

  const handleSaveCreate = async () => {
    if (!formName.trim()) return;
    setSaveLoading(true);
    try {
      await createAdminPaymentMethod({
        name: formName.trim(),
        type: formType,
        enabled: formEnabled,
        sort_order: formSortOrder,
        custom_message: formType === "custom" ? formCustomMessage.trim() || null : null,
      });
      cancelForm();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingId || !formName.trim()) return;
    setSaveLoading(true);
    try {
      await updateAdminPaymentMethod(editingId, {
        name: formName.trim(),
        type: formType,
        enabled: formEnabled,
        sort_order: formSortOrder,
        custom_message: formType === "custom" ? formCustomMessage.trim() || null : null,
      });
      cancelForm();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaveLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Удалить способ оплаты?")) return;
    try {
      await deleteAdminPaymentMethod(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка удаления");
    }
  };

  const toggleEnabled = async (pm: AdminPaymentMethod) => {
    try {
      await updateAdminPaymentMethod(pm.id, { enabled: !pm.enabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    }
  };

  return (
    <div>
      <h1 className="text-xl font-semibold text-white mb-6">Способы оплаты</h1>
      <p className="text-slate-400 text-sm mb-6">
        Включённые способы отображаются на странице тарифов. «ЮKassa» — оплата картой с переходом на страницу оплаты.
        «Кастомный» — при выборе показывается модалка с вашим текстом (реквизиты, безнал и т.д.).
      </p>

      {error && <p className="text-rose-400 text-sm mb-4">{error}</p>}

      {(isCreating || editingId) && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-6 mb-6">
          <h2 className="text-lg font-medium text-white mb-4">{isCreating ? "Новый способ оплаты" : "Редактирование"}</h2>
          <div className="space-y-4 max-w-md">
            <label className="block">
              <span className="text-slate-400 text-sm">Название</span>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Например: Карта (ЮKassa)"
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              />
            </label>
            <label className="block">
              <span className="text-slate-400 text-sm">Тип</span>
              <select
                value={formType}
                onChange={(e) => setFormType(e.target.value as "yookassa" | "custom")}
                className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              >
                <option value="yookassa">ЮKassa (оплата картой)</option>
                <option value="custom">Кастомный (модалка с текстом)</option>
              </select>
            </label>
            {formType === "custom" && (
              <label className="block">
                <span className="text-slate-400 text-sm">Текст в модалке (реквизиты, инструкция)</span>
                <textarea
                  value={formCustomMessage}
                  onChange={(e) => setFormCustomMessage(e.target.value)}
                  rows={5}
                  placeholder="ИП Иванов И.И.&#10;ИНН 1234567890&#10;Р/с 40702810000000000000&#10;Банк ..."
                  className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white font-mono text-sm"
                />
              </label>
            )}
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={formEnabled} onChange={(e) => setFormEnabled(e.target.checked)} className="rounded" />
              <span className="text-slate-400 text-sm">Включён (показывать на странице тарифов)</span>
            </label>
            <label className="block">
              <span className="text-slate-400 text-sm">Порядок (меньше — выше в списке)</span>
              <input
                type="number"
                value={formSortOrder}
                onChange={(e) => setFormSortOrder(parseInt(e.target.value, 10) || 0)}
                className="mt-1 w-24 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              />
            </label>
            <div className="flex gap-2">
              <button
                onClick={isCreating ? handleSaveCreate : handleSaveEdit}
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

      {!isCreating && !editingId && (
        <button
          type="button"
          onClick={startCreate}
          className="mb-6 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600"
        >
          + Добавить способ оплаты
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
                <th className="text-left py-3 px-4">Тип</th>
                <th className="text-left py-3 px-4">Включён</th>
                <th className="text-left py-3 px-4">Порядок</th>
                <th className="text-left py-3 px-4">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 px-4 text-slate-500 text-center">
                    Нет способов оплаты. Добавьте первый — иначе на странице тарифов нечего будет показать.
                  </td>
                </tr>
              ) : (
                items.map((pm) => (
                  <tr key={pm.id} className="hover:bg-slate-800/40">
                    <td className="py-3 px-4 text-white">{pm.name}</td>
                    <td className="py-3 px-4 text-slate-300">{pm.type === "yookassa" ? "ЮKassa" : "Кастомный"}</td>
                    <td className="py-3 px-4">
                      <button
                        type="button"
                        onClick={() => toggleEnabled(pm)}
                        className={`rounded px-2 py-1 text-xs font-medium ${pm.enabled ? "bg-emerald-900/50 text-emerald-300" : "bg-slate-700 text-slate-400"}`}
                      >
                        {pm.enabled ? "Вкл" : "Выкл"}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-slate-400">{pm.sort_order}</td>
                    <td className="py-3 px-4">
                      <button type="button" onClick={() => startEdit(pm)} className="text-teal-400 hover:text-teal-300 mr-3">
                        Изменить
                      </button>
                      <button type="button" onClick={() => handleDelete(pm.id)} className="text-rose-400 hover:text-rose-300">
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
