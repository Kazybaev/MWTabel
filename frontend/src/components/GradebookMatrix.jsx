import { formatMonthLabel } from "../lib/format";
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

function buildPanelTitle(data, mentorMode) {
  return mentorMode ? "" : data.page_title;
}

function buildPanelDescription(data, mentorMode) {
  if (mentorMode) {
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
}) {
  const saveMessage =
    {
      pending: "Есть изменения. Сохраняем автоматически...",
      saving: "Сохраняем изменения...",
      error: "Не удалось сохранить. Следующее изменение попробует снова.",
      synced: dirty ? "Изменения готовы к сохранению..." : "Все изменения сохраняются автоматически.",
    }[saveStatus] || "Все изменения сохраняются автоматически.";

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
        eyebrow={mentorMode ? "" : "Месяц"}
        title={buildPanelTitle(data, mentorMode)}
        description={buildPanelDescription(data, mentorMode)}
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
        <div className={`gradebook-scroll ${lockedMode ? "gradebook-scroll--locked" : ""}`.trim()}>
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
                        {data.can_edit ? (
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

        {data.can_edit ? (
          <div className="gradebook-toolbar">
            <span className={`gradebook-toolbar__status gradebook-toolbar__status--${saveStatus}`}>{saveMessage}</span>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
