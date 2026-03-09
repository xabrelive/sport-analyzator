import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import Link from "next/link";

export const metadata = {
  title: "Правила использования — PingWin",
  description: "Условия использования сервиса PingWin: только аналитика, риски на пользователе.",
};

export default function TermsPage() {
  return (
    <>
      <Header />
      <main className="min-h-screen">
        <article className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
          <h1 className="font-display text-3xl font-bold text-white sm:text-4xl">
            Правила использования
          </h1>
          <p className="mt-2 text-slate-400">
            Сервис PingWin (pingwin.pro)
          </p>
          <div className="prose prose-invert mt-10 max-w-none prose-p:text-slate-300 prose-li:text-slate-300 prose-a:text-cyan-400 prose-a:no-underline hover:prose-a:underline">
            <p>
              Используя сервис PingWin (pingwin.pro), вы соглашаетесь с приведёнными ниже правилами.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              1. Характер сервиса
            </h2>
            <p>
              PingWin предоставляет <strong>исключительно аналитическую информацию</strong> по спортивным событиям: статистику, данные по матчам в режиме лайв и линия, оценки вероятностей на основе имеющихся данных. Сервис не является букмекером, не принимает ставки и не даёт рекомендаций или призывов к заключению пари.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              2. Риски и ответственность
            </h2>
            <p>
              <strong>Любые ставки — на ваш страх и риск.</strong> Используя информацию Сервиса, вы принимаете все решения самостоятельно. Администрация PingWin не несёт ответственности за убытки, упущенную выгоду или иные последствия решений, принятых пользователем на основе или с учётом данных Сервиса. Вся ответственность за такие решения лежит на пользователе.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              3. Актуальность и задержки данных
            </h2>
            <p>
              Обновление данных может осуществляться с задержкой. Мы не гарантируем абсолютную синхронность с источниками и не несём ответственности за последствия возможных задержек или неточностей в отображаемой информации.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              4. Сторонние сервисы и источники
            </h2>
            <p>
              Сервис может использовать данные и интеграции со сторонними поставщиками. Мы не несём ответственности за работу, доступность, точность и своевременность данных сторонних сервисов, а также за убытки, возникшие в связи с их использованием.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              5. Техническое обслуживание
            </h2>
            <p>
              Сервис может приостанавливаться для проведения технического обслуживания. Суммарная длительность таких перерывов не превышает <strong>5 (пяти) дней в течение одного календарного месяца</strong>. О предстоящих работах по возможности сообщается заранее. За перерывы в указанных пределах ответственность не несётся.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              6. Использование ресурса
            </h2>
            <p>
              Пользуясь Сервисом, вы подтверждаете, что все решения, в том числе связанные с рисками и возможными убытками, вы принимаете на свою совесть и под свою ответственность. Администрация PingWin не несёт ответственности за любые прямые или косвенные убытки пользователей.
            </p>

            <h2 className="mt-8 text-xl font-semibold text-white">
              7. Изменения правил
            </h2>
            <p>
              Мы вправе изменять правила использования. Актуальная версия публикуется на данной странице. Продолжение использования Сервиса после публикации изменений считается принятием новых правил.
            </p>

            <p className="mt-8">
              По вопросам:{" "}
              <a href="https://t.me/PingwinBets" target="_blank" rel="noopener noreferrer">
                @PingwinBets
              </a>
              ,{" "}
              <a href="mailto:info@pingwin.pro">info@pingwin.pro</a>.
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
