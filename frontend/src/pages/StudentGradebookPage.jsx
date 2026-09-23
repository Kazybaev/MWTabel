import { useRef, useState } from "react";

import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, Panel } from "../components/Ui";
import { AgrarianRecordModal } from "../components/AgrarianRecordModal";
import { AgrarianGradeCellContent } from "../components/AgrarianGradeCellContent";
import { formatMonthLabel, toMonthValue } from "../lib/format";
import { navigateTo } from "../lib/router";
import { useResource } from "../lib/useResource";

function cellKey(groupId, date) {
  return `${groupId}|${date}`;
}

function buildGradeMap(rows = []) {
  const values = {};
  rows.forEach((row) => {
    Object.entries(row.grades || {}).forEach(([date, grade]) => {
      values[cellKey(row.group_id, date)] = grade || "";
    });
  });
  return values;
}

function gradeTone(grade) {
  return {
    5: "excellent",
    4: "good",
    3: "warning",
    2: "danger",
    Н: "absence",
  }[grade] || "empty";
}

function formatAverage(value) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(1).replace(".", ",");
}

function StudentGradebookEditor({ api, data, month, onNotice, setData }) {
  const scrollContainerRef = useRef(null);
  const [draftGrades, setDraftGrades] = useState(() => buildGradeMap(data.rows));
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [agrarianTarget, setAgrarianTarget] = useState(null);

  function updateGrade(groupId, date, grade) {
    setDraftGrades((current) => ({ ...current, [cellKey(groupId, date)]: grade }));
    setDirty(true);
  }

  function scrollTable(direction) {
    const container = scrollContainerRef.current;
    if (!container) return;

    container.scrollBy({
      left: direction * Math.max(container.clientWidth * 0.72, 280),
      behavior: "smooth",
    });
  }

  async function saveGrades() {
    setSaving(true);
    try {
      const entries = Object.entries(draftGrades)
        .filter(([, grade]) => grade)
        .map(([key, grade]) => {
          const [groupId, date] = key.split("|");
          return { group: Number(groupId), date, grade };
        });
      const payload = await api(`/api/students/${data.student.id}/gradebook/`, {
        method: "POST",
        body: { month, entries },
      });
      setData(payload);
      setDraftGrades(buildGradeMap(payload.rows));
      setDirty(false);
      onNotice({ tone: "success", message: "Табель студента сохранён." });
    } catch (error) {
      onNotice({ tone: "danger", message: error.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-stack student-admin-gradebook">
      <section className="hero-band">
        <div>
          <p className="hero-band__eyebrow">ПЕРСОНАЛЬНЫЙ ТАБЕЛЬ</p>
          <h2>{data.student.full_name}</h2>
          <p>{data.student.username} · {data.student.parent_name} · {data.student.parent_phone}</p>
        </div>
        <div className="hero-band__meta">
          <strong>{data.student.groups_count} групп</strong>
          <span>{data.student.college_course ? `${data.student.college_course} курс` : "Академия"}</span>
          <small>{formatMonthLabel(month)}</small>
        </div>
      </section>

      <div className="metric-grid student-gradebook__summary">
        <Badge tone="blue">Предметов: {data.student.groups_count}</Badge>
        <Badge tone="teal">Оценок: {data.rows.reduce((sum, row) => sum + row.grades_count, 0)}</Badge>
        <Badge tone="sand">Посещений: {data.rows.reduce((sum, row) => sum + row.attendance_count, 0)}</Badge>
        <Badge tone="orange">Пропусков: {data.rows.reduce((sum, row) => sum + row.absence_count, 0)}</Badge>
      </div>

      <Panel
        eyebrow="Все предметы"
        title="Оценки и посещаемость"
        description="Каждая строка — отдельная группа студента. Измените оценку в нужный день и сохраните табель."
        actions={
          <div className="month-actions">
            <Button variant="ghost" onClick={() => navigateTo(`/students/${data.student.id}/gradebook`, { month: data.previous_month })}>← Пред.</Button>
            <input className="month-picker" type="month" value={month} onChange={(event) => navigateTo(`/students/${data.student.id}/gradebook`, { month: event.target.value })} />
            <Button variant="ghost" onClick={() => navigateTo(`/students/${data.student.id}/gradebook`, { month: data.next_month })}>След. →</Button>
          </div>
        }
      >
        {data.rows.length ? (
          <>
          <div className="student-gradebook__hint">
            <span>Полный календарь выбранного месяца</span>
            <strong>Все оценки показаны по датам</strong>
          </div>
          <div className="gradebook-scroll-controls" aria-label="Управление прокруткой табеля студента">
            <span>Свайпните таблицу или прокрутите её вправо и влево</span>
            <div className="gradebook-scroll-controls__buttons">
              <button type="button" onClick={() => scrollTable(-1)} aria-label="Прокрутить табель студента влево">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
              </button>
              <button type="button" onClick={() => scrollTable(1)} aria-label="Прокрутить табель студента вправо">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
              </button>
            </div>
          </div>
          <div ref={scrollContainerRef} className="college-gradebook__scroll college-gradebook__scroll--admin" tabIndex="0" role="region" aria-label="Персональный табель с горизонтальной прокруткой">
            <table className="college-gradebook student-gradebook__table">
              <thead>
                <tr>
                  <th>Предмет</th>
                  <th>Ср.</th>
                  <th>Посещ.</th>
                  {data.days.map((day) => (
                    <th key={day.date} className={`${day.is_weekend ? "is-weekend" : ""} ${day.is_today ? "is-today" : ""}`.trim()}>
                      <span>{day.day}</span><small>{day.weekday}</small>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.group_id}>
                    <th><strong>{row.subject}</strong><small>{row.mentor_name}</small></th>
                    <td>{formatAverage(row.average_grade)}</td>
                    <td>{row.attendance_count}</td>
                    {data.days.map((day) => {
                      const value = draftGrades[cellKey(row.group_id, day.date)] || "";
                      const tone = gradeTone(value);
                      return (
                        <td key={day.date} className={`gradebook-table__cell gradebook-table__cell--${tone} ${day.is_weekend ? "is-weekend" : ""}`.trim()}>
                          {data.agrarian_features ? (
                            <button
                              type="button"
                              className="agrarian-cell-button"
                              onClick={() => setAgrarianTarget({
                                student: data.student,
                                groupId: row.group_id,
                                date: day.date,
                                entries: row.grade_entries?.[day.date] || [],
                              })}
                              aria-label={`Оценки и достижения: ${row.subject}, ${day.date}`}
                            >
                              <AgrarianGradeCellContent
                                entries={row.grade_entries?.[day.date]}
                                bestGrade={value}
                                count={row.grade_counts?.[day.date]}
                              />
                            </button>
                          ) : <select
                            className={`grade-select grade-select--${tone} ${value ? "grade-select--filled" : "grade-select--empty"}`}
                            value={value}
                            onChange={(event) => updateGrade(row.group_id, day.date, event.target.value)}
                            aria-label={`${row.subject}, ${day.date}`}
                          >
                            <option value=""></option>
                            {data.grade_choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                          </select>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        ) : (
          <EmptyState title="Группы не назначены" description="Добавьте студенту хотя бы одну группу, чтобы открыть персональный табель." />
        )}
        {!data.agrarian_features ? <div className="student-gradebook__savebar">
          <span>{dirty ? "Есть несохранённые изменения" : "Все изменения сохранены"}</span>
          <Button onClick={saveGrades} disabled={!dirty || saving}>{saving ? "Сохраняем..." : "Сохранить табель"}</Button>
        </div> : null}
      </Panel>
      <AgrarianRecordModal
        api={api}
        target={agrarianTarget}
        gradeChoices={data.grade_choices}
        onClose={() => setAgrarianTarget(null)}
        onChanged={async () => {
          const payload = await api(`/api/students/${data.student.id}/gradebook/?month=${month}`);
          setData(payload);
        }}
        onNotice={onNotice}
      />
    </div>
  );
}

export function StudentGradebookPage({ api, sessionToken, studentId, routeMonth, onNotice }) {
  const requestedMonth = routeMonth || "";
  const { data, error, loading, reload, setData } = useResource(
    () => api(`/api/students/${studentId}/gradebook/${requestedMonth ? `?month=${requestedMonth}` : ""}`),
    [sessionToken, studentId, requestedMonth],
  );

  if (loading) return <LoadingBlock label="Загружаем персональный табель..." />;
  if (error) return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  if (!data) return <EmptyState title="Студент не найден" description="Вернитесь к списку студентов и выберите другую запись." />;

  const month = data.month || requestedMonth || toMonthValue();
  return <StudentGradebookEditor key={`${studentId}-${month}`} api={api} data={data} month={month} onNotice={onNotice} setData={setData} />;
}
