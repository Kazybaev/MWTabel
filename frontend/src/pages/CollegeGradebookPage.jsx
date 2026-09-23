import { useRef } from "react";

import { Button, EmptyState, ErrorBlock, LoadingBlock, Panel } from "../components/Ui";
import { AgrarianGradeCellContent } from "../components/AgrarianGradeCellContent";
import { toMonthValue } from "../lib/format";
import { navigateTo } from "../lib/router";
import { useResource } from "../lib/useResource";

export function CollegeGradebookPage({ api, sessionToken, routeMonth }) {
  const scrollContainerRef = useRef(null);
  const month = routeMonth || toMonthValue();
  const { data, error, loading, reload } = useResource(
    () => api(`/api/college-gradebook/?month=${month}`),
    [sessionToken, month],
  );

  if (loading) return <LoadingBlock label="Загружаем общий табель колледжа..." />;
  if (error) return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  if (!data?.rows?.length) return <EmptyState title="Предметы пока не назначены" description="После назначения предметов здесь появится общий месячный табель." />;

  function scrollTable(direction) {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.scrollBy({
      left: direction * Math.max(container.clientWidth * 0.72, 260),
      behavior: "smooth",
    });
  }

  return (
    <div className="page-stack student-self-gradebook">
    <Panel eyebrow="Колледж" title="Мой общий табель" description="Все предметы и оценки за выбранный месяц находятся в одной таблице.">
      <label className="college-gradebook__month">
        <span>Месяц</span>
        <input type="month" value={month} onChange={(event) => navigateTo("/my-grades", { month: event.target.value })} />
      </label>
      <div className="gradebook-scroll-controls" aria-label="Управление прокруткой табеля студента">
        <span>Проведите пальцем по таблице или используйте стрелки</span>
        <div className="gradebook-scroll-controls__buttons">
          <button type="button" onClick={() => scrollTable(-1)} aria-label="Прокрутить оценки влево">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
          </button>
          <button type="button" onClick={() => scrollTable(1)} aria-label="Прокрутить оценки вправо">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
          </button>
        </div>
      </div>
      <div
        ref={scrollContainerRef}
        className="college-gradebook__scroll college-gradebook__scroll--student-profile"
        tabIndex="0"
        role="region"
        aria-label="Табель оценок с горизонтальной прокруткой"
      >
        <table className="college-gradebook">
          <thead><tr><th>Предмет</th>{data.days.map((day) => <th key={day.date}>{day.day}</th>)}</tr></thead>
          <tbody>{data.rows.map((row) => (
            <tr key={row.group_id}><th>{row.subject}</th>{data.days.map((day) => {
              const entries = row.grade_entries?.[day.date] || [];
              return <td key={day.date}>{data.agrarian_features ? (
                entries.length ? <div className="agrarian-cell-summary">
                  <AgrarianGradeCellContent
                    entries={entries}
                    bestGrade={row.grades[day.date]}
                    count={row.grade_counts?.[day.date]}
                    emptyLabel="—"
                  />
                </div> : "—"
              ) : row.grades[day.date] || "—"}</td>;
            })}</tr>
          ))}</tbody>
        </table>
      </div>
    </Panel>
    {data.agrarian_features ? (
      <Panel eyebrow="История" title="Мои достижения" description="Все полученные значки сохраняются в истории.">
        {data.badges?.length ? <div className="student-badge-history">{data.badges.map((award) => (
          <article key={award.id} className="agrarian-badge-card">
            <span className="agrarian-badge-card__icon" aria-hidden="true">{award.badge_icon}</span>
            <div><strong>{award.badge_name}</strong><p>{award.comment || "Без комментария"}</p><small>{award.group_name} · {award.teacher_name}</small></div>
          </article>
        ))}</div> : <EmptyState title="Достижений пока нет" description="Полученные значки появятся здесь." />}
      </Panel>
    ) : null}
    </div>
  );
}
