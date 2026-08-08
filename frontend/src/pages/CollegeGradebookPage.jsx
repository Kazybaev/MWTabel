import { Button, EmptyState, ErrorBlock, LoadingBlock, Panel } from "../components/Ui";
import { toMonthValue } from "../lib/format";
import { navigateTo } from "../lib/router";
import { useResource } from "../lib/useResource";

export function CollegeGradebookPage({ api, sessionToken, routeMonth }) {
  const month = routeMonth || toMonthValue();
  const { data, error, loading, reload } = useResource(
    () => api(`/api/college-gradebook/?month=${month}`),
    [sessionToken, month],
  );

  if (loading) return <LoadingBlock label="Загружаем общий табель колледжа..." />;
  if (error) return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  if (!data?.rows?.length) return <EmptyState title="Предметы пока не назначены" description="После назначения предметов здесь появится общий месячный табель." />;

  return (
    <Panel eyebrow="Колледж" title="Мой общий табель" description="Все предметы и оценки за выбранный месяц находятся в одной таблице.">
      <label className="college-gradebook__month">
        <span>Месяц</span>
        <input type="month" value={month} onChange={(event) => navigateTo("/my-grades", { month: event.target.value })} />
      </label>
      <div className="college-gradebook__scroll">
        <table className="college-gradebook">
          <thead><tr><th>Предмет</th>{data.days.map((day) => <th key={day.date}>{day.day}</th>)}</tr></thead>
          <tbody>{data.rows.map((row) => (
            <tr key={row.group_id}><th>{row.subject}</th>{data.days.map((day) => <td key={day.date}>{row.grades[day.date] || "—"}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    </Panel>
  );
}
