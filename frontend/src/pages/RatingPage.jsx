import { useState } from "react";

import { Button, EmptyState, ErrorBlock, LoadingBlock, Panel } from "../components/Ui";
import { useResource } from "../lib/useResource";
import "./RatingPage.css";

const TOP_OPTIONS = [3, 10, 100];
const PERIOD_OPTIONS = [
  { value: "month", label: "Этот месяц" },
  { value: "all", label: "За всё время" },
];
const MEDALS = { 1: "🥇", 2: "🥈", 3: "🥉" };

function formatPoints(value) {
  return `${value > 0 ? "+" : ""}${value}`;
}

function formatAverage(value) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(1).replace(".", ",");
}

function RankChange({ value }) {
  if (!value) {
    return <span className="rating-change rating-change--same" title="Без изменений с вчерашнего дня">—</span>;
  }

  const up = value > 0;
  return (
    <span
      className={`rating-change ${up ? "rating-change--up" : "rating-change--down"}`}
      title={up ? `Поднялись на ${value} с вчерашнего дня` : `Опустились на ${Math.abs(value)} с вчерашнего дня`}
    >
      {up ? "▲" : "▼"} {Math.abs(value)}
    </span>
  );
}

function MeTag() {
  return <span className="rating-me-tag">Вы</span>;
}

function RatingRow({ entry }) {
  return (
    <li className={`rating-row ${entry.is_me ? "rating-row--me" : ""} ${entry.rank <= 3 ? `rating-row--top${entry.rank}` : ""}`.trim()}>
      <span className="rating-row__rank">{MEDALS[entry.rank] || entry.rank}</span>
      <span className="rating-row__who">
        <strong>
          {entry.full_name}
          {entry.is_me ? <MeTag /> : null}
        </strong>
        <small>
          {entry.group_name} · ср. балл {formatAverage(entry.average_grade)} · пропусков {entry.absences_count}
        </small>
      </span>
      <RankChange value={entry.rank_change} />
      <span className="rating-row__points">{formatPoints(entry.points)}</span>
    </li>
  );
}

function Podium({ entries }) {
  // Classic podium order: 2nd, 1st, 3rd.
  const order = [entries[1], entries[0], entries[2]].filter(Boolean);
  return (
    <div className="rating-podium">
      {order.map((entry) => (
        <article
          key={entry.rank}
          className={`rating-podium__place rating-podium__place--${entry.rank} ${entry.is_me ? "rating-podium__place--me" : ""}`.trim()}
        >
          <span className="rating-podium__medal" aria-hidden="true">{MEDALS[entry.rank]}</span>
          <strong className="rating-podium__name">{entry.full_name}</strong>
          {entry.is_me ? <MeTag /> : null}
          <small>{entry.group_name}</small>
          <span className="rating-podium__points">{formatPoints(entry.points)} баллов</span>
          <RankChange value={entry.rank_change} />
          <span className="rating-podium__step">{entry.rank}</span>
        </article>
      ))}
    </div>
  );
}

export function RatingPage({ api, sessionToken, organization, collegeBranch }) {
  const [period, setPeriod] = useState("month");
  const [topLimit, setTopLimit] = useState(10);
  const { data, error, loading, reload } = useResource(
    () => api(`/api/rating/?period=${period}`),
    [sessionToken, period, organization, collegeBranch],
  );

  if (loading) {
    return <LoadingBlock label="Загружаем рейтинг..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  const visible = data.top.slice(0, topLimit);
  const me = data.me;
  const meOutsideVisible = me && !visible.some((entry) => entry.is_me);

  return (
    <div className="page-stack rating-page">
      <Panel
        eyebrow={data.scope_label}
        title="Рейтинг студентов"
        description={`${data.period_label} · участников: ${data.participants_count}. Пятёрки и четвёрки поднимают вас выше, тройки, двойки и пропуски — опускают.`}
        actions={
          <div className="rating-switch" role="group" aria-label="Период рейтинга">
            {PERIOD_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`rating-switch__option ${period === option.value ? "rating-switch__option--active" : ""}`.trim()}
                aria-pressed={period === option.value}
                onClick={() => setPeriod(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      >
        {me ? (
          <section className="rating-me-card" aria-label="Ваше место в рейтинге">
            <div className="rating-me-card__rank">
              <span>Ваше место</span>
              <strong>{me.rank}</strong>
              <small>из {data.participants_count}</small>
            </div>
            <dl className="rating-me-card__stats">
              <div><dt>Баллы</dt><dd>{formatPoints(me.points)}</dd></div>
              <div><dt>За сегодня</dt><dd><RankChange value={me.rank_change} /></dd></div>
              <div><dt>Оценок</dt><dd>{me.grades_count}</dd></div>
              <div><dt>Пропусков</dt><dd>{me.absences_count}</dd></div>
              <div><dt>Ср. балл</dt><dd>{formatAverage(me.average_grade)}</dd></div>
            </dl>
          </section>
        ) : null}

        <div className="rating-toolbar">
          <div className="rating-switch" role="group" aria-label="Размер рейтинга">
            {TOP_OPTIONS.map((limit) => (
              <button
                key={limit}
                type="button"
                className={`rating-switch__option ${topLimit === limit ? "rating-switch__option--active" : ""}`.trim()}
                aria-pressed={topLimit === limit}
                onClick={() => setTopLimit(limit)}
              >
                Топ {limit}
              </button>
            ))}
          </div>
        </div>

        {visible.length === 0 ? (
          <EmptyState title="Рейтинг пока пуст" description="Как только появятся оценки, здесь выстроится лестница лучших студентов." />
        ) : (
          <>
            {topLimit === 3 ? <Podium entries={visible} /> : null}
            <ol className="rating-list">
              {topLimit === 3
                ? null
                : visible.map((entry) => <RatingRow key={entry.rank} entry={entry} />)}
              {meOutsideVisible ? (
                <>
                  <li className="rating-list__gap" aria-hidden="true">···</li>
                  <RatingRow entry={me} />
                </>
              ) : null}
            </ol>
          </>
        )}
      </Panel>
    </div>
  );
}
