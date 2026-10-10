import { formatMonthLabel } from "../lib/format";

const REASONS = {
  no_lessons_in_month: "В этом месяце нет уроков.",
  trigger_lesson_not_created: "Последний урок ещё не создан.",
  trigger_lesson_not_marked: "На последнем уроке одного или нескольких предметов ещё нет оценки или отметки о пропуске.",
  already_sent: "Отчёт за этот месяц уже отправлен.",
  send_already_in_progress: "Отправка выполняется или ожидает подтверждения. Повторная отправка заблокирована.",
  awaiting_delivery_confirmation: "Ожидается подтверждение отправки родителю.",
  inactive_student: "Студент неактивен или находится в архиве.",
};

function describeReportResult(result) {
  if (result.status === "sent") return "Отправка родителю подтверждена.";
  if (result.status === "dry_run") return "Отчёт подготовлен без отправки.";
  if (result.reason === "not_due_today") {
    return `Отправка разрешена только в день последнего урока: ${result.trigger_date || "дата не определена"}.`;
  }
  return REASONS[result.reason] || result.reason || "Отправка не выполнена.";
}

export function ReportDispatchResults({ results, month }) {
  if (!results?.length) return null;
  return (
    <details className="report-dispatch-results" open={results.some((result) => result.status === "failed" || result.status === "pending")}>
      <summary>Результаты проверки отчётов{month ? ` за ${formatMonthLabel(month)}` : ""} ({results.length})</summary>
      <ul>
        {results.map((result) => (
          <li key={result.student_id}>
            <strong>{result.student_name}: </strong>
            <span role={result.status === "failed" ? "alert" : undefined}>{describeReportResult(result)}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}
