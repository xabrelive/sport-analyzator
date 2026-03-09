import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import Link from "next/link";

export const metadata = {
  title: "Политика конфиденциальности — PingWin",
  description: "Как PingWin обрабатывает персональные данные пользователей.",
};

export default function PrivacyPage() {
  return (
    <>
      <Header />
      <main className="min-h-screen">
        <article className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
          <h1 className="font-display text-3xl font-bold text-white sm:text-4xl">
            Политика конфиденциальности
          </h1>
          <p className="mt-2 text-slate-400">
            Сервис PingWin (pingwin.pro)
          </p>
          <div className="prose prose-invert mt-10 max-w-none prose-p:text-slate-300 prose-li:text-slate-300 prose-a:text-cyan-400 prose-a:no-underline hover:prose-a:underline">
            <p>
              Настоящая политика описывает, как мы собираем, используем и храним информацию при использовании сервиса PingWin (далее — Сервис).
            </p>
            <h2 className="mt-8 text-xl font-semibold text-white">
              1. Какие данные мы обрабатываем
            </h2>
            <p>
              При регистрации и использовании Сервиса мы можем обрабатывать: адрес электронной почты, хеш пароля, данные аккаунта Telegram (идентификатор, имя, username при входе через Telegram), настройки уведомлений и предпочтения по видам спорта, технические данные доступа (IP, тип устройства) в объёме, необходимом для работы Сервиса и безопасности.
            </p>
            <h2 className="mt-8 text-xl font-semibold text-white">
              2. Цели обработки
            </h2>
            <p>
              Данные используются для предоставления доступа к аналитике, отправки уведомлений (Telegram, email), связи с пользователем, улучшения работы Сервиса и соблюдения требований законодательства.
            </p>
            <h2 className="mt-8 text-xl font-semibold text-white">
              3. Передача данных третьим лицам
            </h2>
            <p>
              Мы не передаём персональные данные третьим лицам в маркетинговых целях. Передача возможна провайдерам услуг (хостинг, почта, мессенджеры) в объёме, необходимом для работы Сервиса, а также по требованию закона.
            </p>
            <h2 className="mt-8 text-xl font-semibold text-white">
              4. Хранение и безопасность
            </h2>
            <p>
              Мы применяем технические и организационные меры для защиты данных. Пароли хранятся в зашифрованном виде. Пользователь обязан сохранять конфиденциальность учётных данных.
            </p>
            <h2 className="mt-8 text-xl font-semibold text-white">
              5. Ваши права
            </h2>
            <p>
              Вы можете запросить доступ к своим данным, их исправление или удаление, направив обращение на info@pingwin.pro или через канал @PingwinBets.
            </p>
            <p className="mt-8">
              Использование Сервиса означает согласие с настоящей политикой. Мы вправе обновлять её; актуальная версия публикуется на данной странице.
            </p>
          </div>
          <p className="mt-10">
            <Link href="/" className="text-cyan-400 hover:underline">
              ← На главную
            </Link>
          </p>
        </article>
        <Footer />
      </main>
    </>
  );
}
