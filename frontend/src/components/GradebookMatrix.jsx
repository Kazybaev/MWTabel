import { useRef } from "react";

import { formatMonthLabel } from "../lib/format";
import { AgrarianGradeCellContent } from "./AgrarianGradeCellContent";
import { Button, Panel } from "./Ui";

function cellKey(studentId, date) {
  return `${studentId}|${date}`;
}

function resolveGradeTone(grade, fallbackTone = "empty") {
  return (
    {
      "5": "excellent",
      "4": "good",
      "3": "warning",
      "2": "danger",
      Н: "absence",
      н: "absence",
      A: "excellent",
      B: "good",
      C: "warning",
    }[grade] || fallbackTone
  );
}

function formatAverageGrade(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  return Number(value).toFixed(1).replace(".", ",");
}

function buildPanelTitle(data, compactGroupMode) {
  return compactGroupMode ? "" : data.page_title;
}

function buildPanelDescription(data, compactGroupMode) {
  if (compactGroupMode) {
    return "";
  }

  return data.page_copy;
}

export function GradebookMatrix({
  data,
  draftGrades,
  onGradeChange,
  saveStatus = "synced",
  monthValue,
  onMonthChange,
  onMonthStep,
  dirty,
  mentorMode = false,
  adminMode = false,
  lockedMode = false,
  studentMode = false,
  onOpenAgrarianCell,
}) {
  const scrollContainerRef = useRef(null);
  const saveMessage =
    {
      pending: "Есть изменения. Сохраняем автоматически...",
      saving: "Сохраняем изменения...",
      error: "Не удалось сохранить. Следующее изменение попробует снова.",
      synced: dirty ? "Изменения готовы к сохранению..." : "Все изменения сохраняются автоматически.",
    }[saveStatus] || "Все изменения сохраняются автоматически.";

  function scrollTable(direction) {
    const container = scrollContainerRef.current;
    if (!container) return;

    container.scrollBy({
      left: direction * Math.max(container.clientWidth * 0.72, 280),
      behavior: "smooth",
    });
  }

  return (
    <div
      className={`gradebook-layout ${mentorMode ? "gradebook-layout--mentor" : ""} ${
        adminMode ? "gradebook-layout--admin" : ""
      } ${
        studentMode ? "gradebook-layout--student" : ""
      } ${
        lockedMode ? "gradebook-layout--locked" : ""
      }`.trim()}
    >
      {mentorMode ? (
        <section className="gradebook-header">
          <div>
            <h2>{data.group.course_name}</h2>
            <p>
              {data.rows.length} студентов · {data.filled_days_count} активных дней в месяце
            </p>
          </div>
          <div className="gradebook-header__meta">
            <strong>{formatMonthLabel(monthValue)}</strong>
            <span>Листайте таблицу отдельно по горизонтали</span>
          </div>
        </section>
      ) : (
        <section className="hero-band">
          <div>
            <p className="hero-band__eyebrow">Матрица</p>
            <h2>{data.page_title}</h2>
            <p>{data.page_copy}</p>
          </div>
          <div className="hero-band__meta">
            <strong>{formatMonthLabel(monthValue)}</strong>
            <span>{data.group.course_name}</span>
            <small>{data.rows.length} студентов</small>
          </div>
        </section>
      )}

      <Panel
        className={lockedMode ? "gradebook-panel" : ""}
        eyebrow={mentorMode || adminMode ? "" : "Месяц"}
        title={buildPanelTitle(data, mentorMode || adminMode)}
        description={buildPanelDescription(data, mentorMode || adminMode)}
        actions={
          <div className="month-actions">
            <Button variant="ghost" onClick={() => onMonthStep(data.previous_month_value)}>
              ← Пред.
            </Button>
            <input
              className="month-picker"
              type="month"
              value={monthValue}
              onChange={(event) => onMonthChange(event.target.value)}
            />
            <Button variant="ghost" onClick={() => onMonthStep(data.next_month_value)}>
              След. →
            </Button>
          </div>
        }
      >
        {studentMode ? (
          <div className="gradebook-scroll-controls" aria-label="Управление прокруткой табеля">
            <span>Листайте табель вправо и влево</span>
            <div className="gradebook-scroll-controls__buttons">
              <button type="button" onClick={() => scrollTable(-1)} aria-label="Прокрутить табель влево">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
              </button>
              <button type="button" onClick={() => scrollTable(1)} aria-label="Прокрутить табель вправо">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
              </button>
            </div>
          </div>
        ) : null}

        <div ref={scrollContainerRef} className={`gradebook-scroll gradebook-scroll--matrix ${lockedMode ? "gradebook-scroll--locked" : ""} ${studentMode ? "gradebook-scroll--student" : ""}`.trim()} tabIndex="0" aria-label="Таблица оценок с горизонтальной прокруткой">
          <table className="gradebook-table">
            <thead>
              <tr>
                <th className="gradebook-table__sticky gradebook-table__sticky--index">№</th>
                <th className="gradebook-table__sticky gradebook-table__sticky--name">ФИО</th>
                <th className="gradebook-table__sticky gradebook-table__sticky--attendance">Посещ.</th>
                <th className="gradebook-table__sticky gradebook-table__sticky--average">Ср. балл</th>
                {data.month_columns.map((column) => (
                  <th
                    key={column.date}
                    className={[
                      column.is_weekend ? "is-weekend" : "",
                      column.is_today ? "is-today" : "",
                      column.is_study_day ? "is-study-day" : "",
                      column.has_lesson ? "has-lesson" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    <span>{column.label}</span>
                    <small>{column.weekday_label}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.student.id}>
                  <td className="gradebook-table__sticky gradebook-table__sticky--index">{row.index}</td>
                  <td className="gradebook-table__sticky gradebook-table__sticky--name">
                    <strong>{row.student.full_name}</strong>
                  </td>
                  <td className="gradebook-table__sticky gradebook-table__sticky--attendance">{row.attendance_count}</td>
                  <td className="gradebook-table__sticky gradebook-table__sticky--average">
                    {formatAverageGrade(row.average_grade)}
                  </td>
                  {row.cells.map((cell) => {
                    const value = draftGrades[cellKey(row.student.id, cell.date)] ?? "";
                    const tone = value ? resolveGradeTone(value, "empty") : "empty";
                    return (
                      <td
                        key={cell.date}
                        className={[
                          "gradebook-table__cell",
                          `gradebook-table__cell--${tone}`,
                          cell.is_weekend ? "is-weekend" : "",
                          cell.is_today ? "is-today" : "",
                          cell.is_study_day ? "is-study-day" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                      >
                        {data.agrarian_features && data.can_edit ? (
                          <button
                            type="button"
                            className="agrarian-cell-button"
                            onClick={() => onOpenAgrarianCell?.(row.student, cell)}
                            aria-label={`Оценки и достижения: ${row.student.full_name}, ${cell.date}`}
                          >
                            <AgrarianGradeCellContent
                              entries={cell.grade_entries}
                              bestGrade={cell.best_grade}
                              count={cell.grade_count}
                            />
                          </button>
                        ) : data.can_edit ? (
                          <select
                            className={[
                              "grade-select",
                              `grade-select--${tone}`,
                              value ? "grade-select--filled" : "grade-select--empty",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                            value={value}
                            onChange={(event) => onGradeChange(row.student.id, cell.date, event.target.value)}
                            aria-label={`Оценка для ${row.student.full_name} на ${cell.date}`}
                          >
                            <option value=""></option>
                            {data.grade_choices.map((choice) => (
                              <option key={choice.value} value={choice.value}>
                                {choice.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span>{value || ""}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data.can_edit && !data.agrarian_features ? (
          <div className="gradebook-toolbar">
            <span className={`gradebook-toolbar__status gradebook-toolbar__status--${saveStatus}`}>{saveMessage}</span>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
