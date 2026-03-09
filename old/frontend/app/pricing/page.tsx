"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import {
  createCheckout,
  fetchPaymentMethods,
  fetchProducts,
  fetchSports,
  fetchMeAccess,
  type SportOption,
  type AccessSummaryResponse,
  type PaymentMethodPublic,
  type ProductPublic,
} from "@/lib/api";

const ANALYTICS_ONE_SPORT = [
  { id: "1sport-1d", name: "1 день", days: 1, price: 299, desc: "Полная аналитика по одному виду спорта" },
  { id: "1sport-7d", name: "7 дней", days: 7, price: 1990, desc: "Неделя доступа" },
  { id: "1sport-30d", name: "30 дней", days: 30, price: 5990, desc: "Месяц, выгоднее" },
] as const;

const VIP_ONE_SPORT = [
  { id: "vip-1d", name: "1 день", days: 1, priceFull: 299, priceWithAnalytics: 150 },
  { id: "vip-7d", name: "7 дней", days: 7, priceFull: 1990, priceWithAnalytics: 995 },
  { id: "vip-30d", name: "30 дней", days: 30, priceFull: 5990, priceWithAnalytics: 2995 },
] as const;

type AnalyticsTariff = (typeof ANALYTICS_ONE_SPORT)[number];
type VipTariff = (typeof VIP_ONE_SPORT)[number];
type SelectedTariff = { type: "analytics"; tariff: AnalyticsTariff } | { type: "vip"; tariff: VipTariff };

function getValidUntil(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function formatDate(s: string): string {
  return new Date(s).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
}

function PricingContent() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const [sports, setSports] = useState<SportOption[]>([]);
  const [access, setAccess] = useState<AccessSummaryResponse | null>(null);
  const [selected, setSelected] = useState<SelectedTariff | null>(null);
  const [sportKey, setSportKey] = useState<string>("table_tennis");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethodPublic[]>([]);
  const [paymentStep, setPaymentStep] = useState<"form" | "payment_choice" | "custom_message">("form");
  const [customPaymentMethod, setCustomPaymentMethod] = useState<PaymentMethodPublic | null>(null);
  const [products, setProducts] = useState<ProductPublic[]>([]);
  const [productsLoaded, setProductsLoaded] = useState(false);
  const searchParams = useSearchParams();
  const paidSuccess = searchParams.get("paid") === "1";

  useEffect(() => {
    fetchSports().then(setSports).catch(() => setSports([{ id: "table_tennis", name: "Настольный теннис" }]));
  }, []);

  useEffect(() => {
    fetchProducts()
      .then((list) => { setProducts(list); setProductsLoaded(true); })
      .catch(() => { setProducts([]); setProductsLoaded(true); });
  }, []);

  useEffect(() => {
    if (selected) {
      fetchPaymentMethods()
        .then(setPaymentMethods)
        .catch(() => setPaymentMethods([]));
      setPaymentStep("form");
      setCustomPaymentMethod(null);
    }
  }, [selected]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchMeAccess().then(setAccess).catch(() => setAccess(null));
    } else {
      setAccess(null);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (paidSuccess && isAuthenticated) {
      fetchMeAccess().then(setAccess).catch(() => {});
    }
  }, [paidSuccess, isAuthenticated]);

  const hasAnalytics = access?.tg_analytics?.has ?? false;
  const showAnalyticsProduct = products.some((p) => p.key === "tg_analytics");
  const showVipProduct = products.some((p) => p.key === "signals");

  const handleChooseAnalytics = useCallback(
    (t: AnalyticsTariff) => {
      if (!isAuthenticated) {
        router.push("/login?returnUrl=/pricing");
        return;
      }
      setSelected({ type: "analytics", tariff: t });
      setError(null);
    },
    [isAuthenticated, router],
  );

  const handleChooseVip = useCallback(
    (t: VipTariff) => {
      if (!isAuthenticated) {
        router.push("/login?returnUrl=/pricing");
        return;
      }
      setSelected({ type: "vip", tariff: t });
      setError(null);
    },
    [isAuthenticated, router],
  );

  const handleSubmit = useCallback(async () => {
    if (!selected || !sportKey) return;
    setLoading(true);
    setError(null);
    try {
      const days = selected.type === "analytics" ? selected.tariff.days : selected.tariff.days;
      const items = [
        {
          access_type: selected.type === "analytics" ? ("tg_analytics" as const) : ("signals" as const),
          scope: "one_sport" as const,
          sport_key: sportKey,
          days,
        },
      ];
      const result = await createCheckout(items);
      if (result.confirmation_url) {
        window.location.href = result.confirmation_url;
        return;
      }
      setError(result.error || "Не удалось создать платёж");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка подключения");
    } finally {
      setLoading(false);
    }
  }, [selected, sportKey, router]);

  const handleCloseModal = useCallback(() => {
    if (!loading) {
      setSelected(null);
      setPaymentStep("form");
      setCustomPaymentMethod(null);
    }
  }, [loading]);

  const onPayClick = useCallback(() => {
    if (paymentMethods.length === 0) {
      setError("Нет доступных способов оплаты. Обратитесь к администратору.");
      return;
    }
    if (paymentMethods.length === 1 && paymentMethods[0].type === "yookassa") {
      handleSubmit();
      return;
    }
    setPaymentStep("payment_choice");
    setError(null);
  }, [paymentMethods, handleSubmit]);

  const onSelectPaymentMethod = useCallback(
    (pm: PaymentMethodPublic) => {
      if (pm.type === "yookassa") {
        handleSubmit();
        return;
      }
      setCustomPaymentMethod(pm);
      setPaymentStep("custom_message");
    },
    [handleSubmit],
  );

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-2">Тарифы</h1>

      {paidSuccess && (
        <div className="rounded-xl border border-emerald-600/60 bg-emerald-900/30 p-4 mb-6 text-emerald-200 text-sm">
          Оплата прошла успешно. Подписка активирована. Обновите страницу, если доступ ещё не отобразился.
        </div>
      )}

      {/* Disclaimer */}
      <div className="rounded-xl border border-slate-600 bg-slate-800/60 p-4 mb-8">
        <p className="text-slate-300 text-sm leading-relaxed">
          <strong className="text-white">Важно:</strong> мы не продаём ставки и не гарантируем результат.
          Мы предоставляем аналитику и информационные материалы. Все решения о ставках вы принимаете на свой страх и риск.
        </p>
      </div>

      {/* Аналитика — обязательно к покупке для полного доступа */}
      {showAnalyticsProduct && (
      <section id="analytics" className="scroll-mt-4 mb-10">
        <h2 className="text-lg font-semibold text-white mb-1">Полная аналитика</h2>
        <p className="text-slate-500 text-sm mb-4">
          Линия, лайв, углублённая аналитика по матчам. Один вид спорта на выбор.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {ANALYTICS_ONE_SPORT.map((t) => (
            <div
              key={t.id}
              className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5 flex flex-col"
            >
              <p className="font-medium text-white">{t.name}</p>
              <p className="text-slate-400 text-sm mt-1">{t.desc}</p>
              <p className="mt-4 text-2xl font-bold text-teal-400">{t.price} ₽</p>
              <button
                type="button"
                onClick={() => handleChooseAnalytics(t)}
                className="mt-4 w-full rounded-lg bg-teal-500 py-2.5 text-sm font-medium text-white hover:bg-teal-400 transition-colors"
              >
                Выбрать
              </button>
            </div>
          ))}
        </div>
      </section>
      )}

      {/* VIP-канал: сигналы и экспрессы */}
      {showVipProduct && (
      <section id="vip" className="scroll-mt-4 mb-10">
        <h2 className="text-lg font-semibold text-white mb-1">VIP-канал</h2>
        <p className="text-slate-500 text-sm mb-4">
          Доступ в закрытый канал с сигналами и экспрессами. Один вид спорта. При подписке на аналитику — скидка 50%.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {VIP_ONE_SPORT.map((t) => {
            const useDiscount = hasAnalytics;
            const price = useDiscount ? t.priceWithAnalytics : t.priceFull;
            return (
              <div
                key={t.id}
                className="rounded-xl border border-amber-800/60 bg-slate-900/60 p-5 flex flex-col"
              >
                <p className="font-medium text-white">{t.name}</p>
                <p className="text-slate-400 text-sm mt-1">VIP-канал, 1 вид спорта</p>
                <div className="mt-4">
                  <span className="text-2xl font-bold text-amber-400">{price} ₽</span>
                  {hasAnalytics ? (
                    <span className="ml-2 text-emerald-400 text-sm">−50%</span>
                  ) : (
                    <p className="text-slate-500 text-xs mt-1">с аналитикой: {t.priceWithAnalytics} ₽</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleChooseVip(t)}
                  className="mt-4 w-full rounded-lg bg-amber-500/90 py-2.5 text-sm font-medium text-white hover:bg-amber-400 transition-colors"
                >
                  Выбрать
                </button>
              </div>
            );
          })}
        </div>
      </section>
      )}

      {!showAnalyticsProduct && !showVipProduct && productsLoaded && (
        <p className="text-slate-500 text-sm mb-8">
          Сейчас нет доступных тарифов. Обратитесь к администратору.
        </p>
      )}

      {/* Бесплатно: 1 ТГ + 1 почта */}
      <p className="text-slate-500 text-sm mb-8">
        Один Telegram и одна почта для уведомлений можно подключить бесплатно в{" "}
        <Link href="/me" prefetch={false} className="text-teal-400 hover:underline">личном кабинете</Link>.
        Уведомления в личку приходят только при активной подписке на аналитику и на сигналы.
      </p>

      {/* Модалка */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70" onClick={handleCloseModal}>
          <div
            className="rounded-2xl border border-slate-600 bg-slate-900 p-6 w-full max-w-md shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-white mb-2">
              {selected.type === "analytics" ? "Подписка на аналитику" : "Подписка на VIP-канал"}
            </h3>
            <p className="text-slate-400 text-sm mb-1">
              {selected.type === "analytics"
                ? `${selected.tariff.name} · ${selected.tariff.price} ₽`
                : `${selected.tariff.name} · ${hasAnalytics ? selected.tariff.priceWithAnalytics : selected.tariff.priceFull} ₽`}
            </p>
            <p className="text-slate-500 text-xs mb-4">
              Доступ до {formatDate(getValidUntil(selected.type === "analytics" ? selected.tariff.days : selected.tariff.days))}.
            </p>
            <div className="mb-4">
              <label className="block text-slate-400 text-sm mb-1">Вид спорта</label>
              <select
                value={sportKey}
                onChange={(e) => setSportKey(e.target.value)}
                className="w-full rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white"
              >
                {sports.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <p className="text-slate-500 text-xs mb-2">
              Мы предоставляем аналитику. Решения о ставках — на ваш страх и риск.
            </p>
            {error && <p className="text-rose-400 text-sm mb-2">{error}</p>}

            {paymentStep === "form" && (
              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={onPayClick}
                  disabled={loading}
                  className={`flex-1 rounded-lg py-2.5 text-sm font-medium text-white disabled:opacity-50 ${
                    selected.type === "analytics"
                      ? "bg-teal-500 hover:bg-teal-400"
                      : "bg-amber-500/90 hover:bg-amber-400"
                  }`}
                >
                  {loading ? "Переход к оплате…" : "Оплатить"}
                </button>
                <button
                  type="button"
                  onClick={handleCloseModal}
                  disabled={loading}
                  className="rounded-lg border border-slate-600 py-2.5 px-4 text-slate-300 hover:bg-slate-800 disabled:opacity-50 text-sm"
                >
                  Отмена
                </button>
              </div>
            )}

            {paymentStep === "payment_choice" && (
              <div className="mt-4">
                <p className="text-slate-400 text-sm mb-3">Выберите способ оплаты:</p>
                <div className="space-y-2 mb-4">
                  {paymentMethods.map((pm) => (
                    <button
                      key={pm.id}
                      type="button"
                      onClick={() => onSelectPaymentMethod(pm)}
                      disabled={loading}
                      className="w-full rounded-lg border border-slate-600 bg-slate-800 py-2.5 px-4 text-left text-white hover:bg-slate-700 disabled:opacity-50"
                    >
                      {pm.name}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => setPaymentStep("form")}
                  className="rounded-lg border border-slate-600 py-2 px-4 text-slate-300 hover:bg-slate-800 text-sm"
                >
                  ← Назад
                </button>
              </div>
            )}

            {paymentStep === "custom_message" && customPaymentMethod && (
              <div className="mt-4">
                <div className="rounded-lg bg-slate-800/80 p-4 mb-4 text-slate-200 text-sm whitespace-pre-line">
                  {customPaymentMethod.custom_message?.trim() || "Информация не указана."}
                </div>
                <button
                  type="button"
                  onClick={() => { setPaymentStep("form"); setCustomPaymentMethod(null); }}
                  className="rounded-lg border border-slate-600 py-2.5 px-4 text-slate-300 hover:bg-slate-800"
                >
                  Закрыть
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <p className="text-center">
        <Link href="/dashboard" className="text-teal-400 hover:underline text-sm">
          ← На дашборд
        </Link>
      </p>
    </main>
  );
}

export default function PricingPage() {
  return (
    <Suspense fallback={<main className="max-w-4xl mx-auto px-4 py-8"><div className="text-slate-400">Загрузка…</div></main>}>
      <PricingContent />
    </Suspense>
  );
}
