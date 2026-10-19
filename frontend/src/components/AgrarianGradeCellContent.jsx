import { formatGradeCount } from "../lib/format";

export function AgrarianGradeCellContent({ entries = [], bestGrade = "", count = entries.length, emptyLabel = "+" }) {
  const orderedEntries = [...entries].sort((left, right) => {
    const leftIsAbsence = String(left.score).toUpperCase() === "Н";
    const rightIsAbsence = String(right.score).toUpperCase() === "Н";
    return Number(rightIsAbsence) - Number(leftIsAbsence);
  });

  return (
    <>
      <span className="agrarian-cell-values" aria-hidden="true">
        {orderedEntries.length ? orderedEntries.map((entry, index) => {
          const isAbsence = String(entry.score).toUpperCase() === "Н";
          return (
            <strong
              key={entry.id ?? `${entry.score}-${index}`}
              className={[entry.score === bestGrade ? "is-best" : "", isAbsence ? "is-absence" : ""].filter(Boolean).join(" ")}
            >
              {entry.score}
            </strong>
          );
        }) : <strong className="is-empty">{emptyLabel}</strong>}
      </span>
      <small>{formatGradeCount(count)}</small>
    </>
  );
}
