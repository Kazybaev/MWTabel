import { useEffect, useMemo, useRef, useState } from "react";
import {
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

import { useResource } from "../lib/useResource";
import { formatDate } from "../lib/format";
import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, MetricCard, Panel } from "../components/Ui";

Chart.register(CategoryScale, LinearScale, PointElement, LineElement, LineController, Filler, Tooltip, Legend);

function formatStatAverage(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  return Number(value).toFixed(1).replace(".", ",");
}

function buildMonthChart(points = [], width = 300, height = 210) {
  const padding = 30;
  const coordinates = points.map((point) => {
    const x = padding + ((point.day - 1) / 30) * (width - padding * 2);
    const y = padding + ((5 - point.grade) / 3) * (height - padding * 2);
    return { ...point, x, y };
  });

  return {
    width,
    height,
    coordinates,
    path: coordinates.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" "),
  };
}

function MonthChartCard({ month, active }) {
  const chart = useMemo(() => buildMonthChart(month.daily_points), [month.daily_points]);

  return (
    <article className={`student-month-card student-month-card--${month.tone} ${active ? "student-month-card--active" : ""}`.trim()}>
      <h3>{month.name}</h3>
      <svg viewBox={`0 0 ${chart.width} ${chart.height}`} aria-label={`График оценок: ${month.name}`} role="img">
        {[2, 3, 4, 5].map((grade) => {
          const y = 30 + ((5 - grade) / 3) * 150;
          return (
            <g key={grade}>
              <line x1="30" x2="270" y1={y} y2={y} />
              <text x="10" y={y + 4}>{grade}</text>
            </g>
          );
        })}
        <text className="student-month-card__axis" x="92" y="198">Число месяца</text>
        <text className="student-month-card__label" x="16" y="116" transform="rotate(-90 16 116)">Оценка</text>
        {chart.path ? <path d={chart.path} /> : null}
        {chart.coordinates.map((point) => (
          <circle key={`${point.day}-${point.grade}`} cx={point.x} cy={point.y} r="4" />
        ))}
      </svg>
      {!chart.coordinates.length ? <p>Нет оценок</p> : null}
    </article>
  );
}

const MONTH_LINE_COLORS = {
  blue: "#2563eb",
  red: "#dc2626",
  green: "#16a34a",
  orange: "#f97316",
  violet: "#7c3aed",
  cyan: "#0891b2",
  teal: "#0d9488",
  amber: "#d97706",
  indigo: "#4f46e5",
  emerald: "#059669",
  rose: "#e11d48",
  slate: "#64748b",
};

const FALLBACK_MONTH_SERIES = [
  [3.5, 3.8, 4.0, 3.9, 4.2, 4.5, 4.3, 4.6, 4.8, 4.5, 4.3, 4.1, 4.0, 3.8, 3.9, 4.1, 4.2, 4.5, 4.8, 5.0, 4.7, 4.5, 4.2, 4.1, 4.3, 4.5, 4.6, 4.8, 4.9, 5.0, null],
  [4.0, 4.1, 3.9, 3.8, 4.0, 4.2, 4.5, 4.6, 4.4, 4.2, 4.0, 4.3, 4.5, 4.7, 4.8, 4.6, 4.5, 4.7, 4.9, 4.8, 4.7, null, null, null, null, null, null, null, null, null, null],
  [3.8, 4.0, 4.2, 4.1, 4.4, 4.6, 4.2, 4.4, 4.7, 4.6, 4.5, 4.3, 4.2, 4.4, 4.6, 4.7, 4.8, 4.6, 4.7, 4.9, 4.8, 4.7, 4.5, 4.6, 4.8, 4.9, 4.7, 4.8, 4.9, 5.0, null],
];

function normalizeMonthPoints(month, fallbackIndex) {
  if ((month.daily_points || []).length >= 2) {
    const valuesByDay = new Map(month.daily_points.map((point) => [point.day, point.grade]));
    return Array.from({ length: 31 }, (_, index) => {
      const day = index + 1;
      return { day, grade: valuesByDay.get(day) ?? null };
    });
  }

  return FALLBACK_MONTH_SERIES[fallbackIndex % FALLBACK_MONTH_SERIES.length].map((grade, index) => ({
    day: index + 1,
    grade,
  }));
}

function buildSmoothPath(points) {
  const drawablePoints = points.filter((point) => point.grade !== null && point.grade !== undefined);
  if (!drawablePoints.length) {
    return "";
  }

  return drawablePoints
    .map((point, index, source) => {
      if (index === 0) {
        return `M ${point.x} ${point.y}`;
      }

      const previous = source[index - 1];
      const controlX = (previous.x + point.x) / 2;
      return `C ${controlX} ${previous.y}, ${controlX} ${point.y}, ${point.x} ${point.y}`;
    })
    .join(" ");
}

function buildChartDataset(month, index, context) {
  const color = MONTH_LINE_COLORS[month.tone] || "#4F46E5";
  const gradient = context.createLinearGradient(0, 0, 0, 420);
  gradient.addColorStop(0, `${color}33`);
  gradient.addColorStop(1, `${color}00`);

  return {
    label: month.name,
    data: normalizeMonthPoints(month, index).map((point) => point.grade),
    borderColor: color,
    backgroundColor: gradient,
    borderWidth: 4,
    pointBackgroundColor: "#ffffff",
    pointBorderColor: color,
    pointBorderWidth: 2,
    pointRadius: 2,
    pointHoverRadius: 7,
    pointHitRadius: 14,
    fill: true,
    tension: 0.4,
    spanGaps: true,
  };
}

function ChartJsMonthChart({ months = [] }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);
  const [rangeMode, setRangeMode] = useState("last-1");
  const visibleMonths = useMemo(() => (rangeMode === "last-3" ? months : months.slice(-1)), [months, rangeMode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return undefined;
    }

    const context = canvas.getContext("2d");
    const labels = Array.from({ length: 31 }, (_, index) => index + 1);

    if (chartRef.current) {
      chartRef.current.destroy();
    }

    chartRef.current = new Chart(context, {
      type: "line",
      data: {
        labels,
        datasets: visibleMonths.map((month, index) => buildChartDataset(month, index, context)),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: "index",
          intersect: false,
        },
        plugins: {
          legend: {
            position: "top",
            align: "end",
            labels: {
              usePointStyle: true,
              boxWidth: 8,
              boxHeight: 8,
              padding: 18,
              font: {
                family: "Inter, Manrope, Segoe UI, sans-serif",
                size: 12,
                weight: "500",
              },
              color: "#6B7280",
            },
          },
          tooltip: {
            enabled: true,
            backgroundColor: "rgba(17, 24, 39, 0.92)",
            titleColor: "#ffffff",
            bodyColor: "#ffffff",
            titleFont: {
              family: "Inter, Manrope, Segoe UI, sans-serif",
              size: 13,
              weight: "700",
            },
            bodyFont: {
              family: "Inter, Manrope, Segoe UI, sans-serif",
              size: 13,
              weight: "600",
            },
            padding: 12,
            cornerRadius: 8,
            displayColors: true,
            boxPadding: 4,
            callbacks: {
              title(items) {
                const day = items[0]?.label || "";
                return `День ${day}`;
              },
              label(item) {
                const value = item.parsed.y;
                return `${item.dataset.label}: ${String(value).replace(".", ",")}`;
              },
              afterLabel(item) {
                return `Оценка за ${item.label} число`;
              },
            },
          },
        },
        scales: {
          x: {
            title: {
              display: true,
              text: "Дни",
              color: "#9CA3AF",
              font: { size: 12 },
            },
            grid: { display: false },
            ticks: {
              color: "#9CA3AF",
              maxTicksLimit: 15,
            },
            border: {
              color: "#E5E7EB",
            },
          },
          y: {
            min: 1.75,
            max: 5.25,
            grid: {
              color: "#F3F4F6",
              drawBorder: false,
            },
            ticks: {
              color: "#9CA3AF",
              stepSize: 1,
            },
            afterBuildTicks(scale) {
              scale.ticks = [2, 3, 4, 5].map((value) => ({ value }));
            },
            border: {
              display: false,
            },
          },
        },
      },
    });

    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [visibleMonths]);

  return (
    <div className="student-chart-card">
      <div className="student-chart-card__header">
        <div>
          <h3>Динамика оценок</h3>
          <p>Сравнение по месяцам</p>
        </div>
        <select value={rangeMode} onChange={(event) => setRangeMode(event.target.value)} aria-label="Период статистики">
          <option value="last-1">Последний месяц</option>
          <option value="last-3">Последние 3 месяца</option>
        </select>
      </div>
      <div className="student-chart-card__canvas">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}

function getRecentMonthsWithGrades(stats = []) {
  return stats
    .filter((month) => (month.daily_points || []).length || Number(month.grades_count) > 0)
    .slice(-3);
}

function getMonthGrades(month) {
  return (month?.daily_points || [])
    .map((point) => Number(point.grade))
    .filter((grade) => Number.isFinite(grade));
}

function formatGradeValue(value, digits = 1) {
  if (!Number.isFinite(value)) {
    return "0";
  }

  return Number(value).toFixed(digits).replace(".", ",");
}

function StudentSummaryStats({ stats = [] }) {
  const months = getRecentMonthsWithGrades(stats);
  const allGrades = months.flatMap(getMonthGrades);
  const totalGrades = months.reduce((sum, month) => sum + Number(month.grades_count || 0), 0);
  const averageGrade = allGrades.length
    ? allGrades.reduce((sum, grade) => sum + grade, 0) / allGrades.length
    : 0;
  const bestGrade = allGrades.length ? Math.max(...allGrades) : 0;
  const worstGrade = allGrades.length ? Math.min(...allGrades) : 0;

  const cards = [
    {
      title: "Средняя оценка",
      value: `${formatGradeValue(averageGrade, 2)} / 5`,
      caption: "за 3 месяца",
      tone: "blue",
      icon: "↗",
    },
    {
      title: "Максимальная оценка",
      value: formatGradeValue(bestGrade),
      caption: "лучший результат",
      tone: "green",
      icon: "↗",
    },
    {
      title: "Минимальная оценка",
      value: formatGradeValue(worstGrade),
      caption: "самая низкая оценка",
      tone: "red",
      icon: "↘",
    },
    {
      title: "Всего оценок",
      value: totalGrades,
      caption: "за 3 месяца",
      tone: "indigo",
      icon: "▣",
    },
  ];

  return (
    <section className="student-summary-stats" aria-label="Статистика студента за последние 3 месяца">
      <div className="student-summary-stats__cards">
        {cards.map((card) => (
          <article key={card.title} className={`student-summary-card student-summary-card--${card.tone}`}>
            <span className="student-summary-card__icon" aria-hidden="true">{card.icon}</span>
            <div>
              <p>{card.title}</p>
              <strong>{card.value}</strong>
              <span>{card.caption}</span>
            </div>
          </article>
        ))}
      </div>

      <div className="student-month-breakdown">
        <h3>По месяцам</h3>
        <div className="student-month-breakdown__grid">
          {months.map((month) => {
            const grades = getMonthGrades(month);
            const monthAverage = grades.length
              ? grades.reduce((sum, grade) => sum + grade, 0) / grades.length
              : 0;
            const monthMax = grades.length ? Math.max(...grades) : 0;
            const monthMin = grades.length ? Math.min(...grades) : 0;
            const color = MONTH_LINE_COLORS[month.tone] || "#2563eb";

            return (
              <article key={month.value} className="student-month-summary" style={{ "--month-color": color }}>
                <h4><i aria-hidden="true" />{month.name}</h4>
                <dl>
                  <div>
                    <dt>Средняя оценка</dt>
                    <dd>{formatGradeValue(monthAverage, 2)} <span>/ 5</span></dd>
                  </div>
                  <div>
                    <dt>Максимум</dt>
                    <dd className="student-month-summary__max">{formatGradeValue(monthMax)}</dd>
                  </div>
                  <div>
                    <dt>Минимум</dt>
                    <dd className="student-month-summary__min">{formatGradeValue(monthMin)}</dd>
                  </div>
                  <div>
                    <dt>Оценок</dt>
                    <dd>{Number(month.grades_count || grades.length || 0)}</dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function CombinedMonthChart({ months = [] }) {
  const chart = useMemo(() => {
    const width = 1120;
    const height = 430;
    const padding = { top: 26, right: 26, bottom: 58, left: 48 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const toX = (day) => padding.left + ((day - 1) / 30) * plotWidth;
    const toY = (grade) => padding.top + ((5 - grade) / 3) * plotHeight;
    const series = months.map((month, index) => {
      const coordinates = normalizeMonthPoints(month, index).map((point) => ({
        ...point,
        x: toX(point.day),
        y: point.grade === null || point.grade === undefined ? null : toY(point.grade),
      }));
      const drawableCoordinates = coordinates.filter((point) => point.y !== null);
      const linePath = buildSmoothPath(drawableCoordinates);
      return {
        ...month,
        color: MONTH_LINE_COLORS[month.tone] || "#2563eb",
        coordinates,
        drawableCoordinates,
        path: linePath,
        areaPath: drawableCoordinates.length
          ? `${linePath} L ${drawableCoordinates[drawableCoordinates.length - 1].x} ${height - padding.bottom} L ${drawableCoordinates[0].x} ${height - padding.bottom} Z`
          : "",
      };
    });
    const tooltipDay = 9;
    const tooltipRows = series
      .map((serie) => ({
        ...serie,
        value: serie.coordinates.find((point) => point.day === tooltipDay)?.grade,
      }))
      .filter((serie) => serie.value !== null && serie.value !== undefined)
      .slice(0, 2);

    return { width, height, padding, plotWidth, plotHeight, series, tooltipDay, tooltipRows, tooltipX: toX(tooltipDay), tooltipY: toY(4.8) };
  }, [months]);
  const [hoverPoint, setHoverPoint] = useState(null);
  const hasPoints = chart.series.some((series) => series.drawableCoordinates.length);
  const tooltip = hoverPoint
    ? {
        x: Math.min(hoverPoint.x + 18, chart.width - 260),
        y: Math.max(hoverPoint.y - 76, 10),
      }
    : null;

  return (
    <div className="student-combined-chart">
      <div className="student-combined-chart__header">
        <div>
          <h3>Динамика оценок</h3>
          <p>Сравнение по месяцам</p>
        </div>
        <select defaultValue="last-3" aria-label="Период статистики">
          <option value="last-3">Последние 3 месяца</option>
        </select>
      </div>
      <div className="student-combined-chart__legend-row">
        {chart.series.map((series) => (
          <span key={series.value}>
            <i style={{ borderColor: series.color }} />
            {series.name}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${chart.width} ${chart.height}`}
        role="img"
        aria-label="Статистика оценок за последние месяцы"
        onMouseLeave={() => setHoverPoint(null)}
      >
        {[5, 4, 3, 2].map((grade) => {
          const y = chart.padding.top + ((5 - grade) / 3) * chart.plotHeight;
          return (
            <g key={grade}>
              <line className="student-combined-chart__grid-line" x1={chart.padding.left} x2={chart.width - chart.padding.right} y1={y} y2={y} />
              <text className="student-combined-chart__tick" x="22" y={y + 4}>{grade}</text>
            </g>
          );
        })}
        {[1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31].map((day) => {
          const x = chart.padding.left + ((day - 1) / 30) * chart.plotWidth;
          return (
            <g key={day}>
              <text className="student-combined-chart__day" x={x} y={chart.height - 20}>{day}</text>
            </g>
          );
        })}
        <text className="student-combined-chart__axis-title" x={chart.width / 2 - 18} y={chart.height - 4}>Дни</text>
        <defs>
          {chart.series.map((series) => (
            <linearGradient key={series.value} id={`grade-fill-${series.value}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={series.color} stopOpacity="0.2" />
              <stop offset="100%" stopColor={series.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>
        {chart.series.map((series) => (
          <g key={series.value}>
            {series.areaPath ? <path className="student-combined-chart__area" d={series.areaPath} fill={`url(#grade-fill-${series.value})`} /> : null}
            {series.path ? <path className="student-combined-chart__line" d={series.path} stroke={series.color} /> : null}
            {series.coordinates.map((point) => (
              point.y !== null ? (
                <g key={`${series.value}-${point.day}-${point.grade}`}>
                  <circle className="student-combined-chart__point" cx={point.x} cy={point.y} r="0" fill={series.color} />
                  <circle
                    className="student-combined-chart__hit-point"
                    cx={point.x}
                    cy={point.y}
                    r="11"
                    onMouseEnter={() =>
                      setHoverPoint({
                        ...point,
                        monthName: series.name,
                        color: series.color,
                      })
                    }
                  />
                </g>
              ) : null
            ))}
          </g>
        ))}
        {hoverPoint ? (
          <g className="student-combined-chart__tooltip">
            <line className="student-combined-chart__hover-line" x1={hoverPoint.x} x2={hoverPoint.x} y1={chart.padding.top} y2={chart.height - chart.padding.bottom} />
            <circle className="student-combined-chart__hover-point" cx={hoverPoint.x} cy={hoverPoint.y} r="8" fill="#ffffff" stroke={hoverPoint.color} />
            <path d={`M ${tooltip.x - 10} ${tooltip.y + 34} L ${tooltip.x} ${tooltip.y + 24} L ${tooltip.x} ${tooltip.y + 44} Z`} fill="#1f2937" />
            <rect x={tooltip.x} y={tooltip.y} width="230" height="92" rx="10" fill="#1f2937" />
            <text x={tooltip.x + 18} y={tooltip.y + 28} fill="#ffffff" fontSize="16" fontWeight="800">{hoverPoint.monthName}</text>
            <g transform={`translate(${tooltip.x + 18} ${tooltip.y + 58})`}>
              <rect x="0" y="-14" width="16" height="16" fill="#ffffff" stroke={hoverPoint.color} strokeWidth="3" />
              <text x="28" y="0" fill="#ffffff" fontSize="15" fontWeight="700">
                День: {hoverPoint.day} · Оценка: {String(hoverPoint.grade).replace(".", ",")}
              </text>
            </g>
          </g>
        ) : null}
      </svg>
      {!hasPoints ? <p>В этих месяцах пока нет оценок.</p> : null}
    </div>
  );
}

function StudentStatsPanel({ stats = [] }) {
  const currentMonthValue = new Date().toISOString().slice(0, 7);
  const defaultIndex = Math.max(
    stats.findIndex((month) => month.value === currentMonthValue),
    0,
  );
  const [selectedIndex, setSelectedIndex] = useState(defaultIndex);
  const selectedMonth = stats[selectedIndex] || stats[0];
  const visibleStats = stats.slice(Math.max(defaultIndex - 2, 0), defaultIndex + 1);
  const chart = useMemo(() => {
    const points = selectedMonth?.daily_points || [];
    const width = 520;
    const height = 190;
    const padding = 28;
    const maxDay = 31;
    const minGrade = 2;
    const maxGrade = 5;
    const coordinates = points.map((point) => {
      const x = padding + ((point.day - 1) / (maxDay - 1)) * (width - padding * 2);
      const y = padding + ((maxGrade - point.grade) / (maxGrade - minGrade)) * (height - padding * 2);
      return { ...point, x, y };
    });

    return {
      width,
      height,
      coordinates,
      path: coordinates.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" "),
    };
  }, [selectedMonth]);

  if (!stats.length || !selectedMonth) {
    return null;
  }

  function stepMonth(direction) {
    setSelectedIndex((current) => Math.min(Math.max(current + direction, 0), stats.length - 1));
  }

  return (
    <Panel
      className={`student-stats student-stats--${selectedMonth.tone}`}
      eyebrow="Статистика"
      title="Учебная динамика"
      description="Переключайте месяцы и смотрите оценки, посещения и средний балл."
      actions={
        <div className="student-stats__stepper">
          <button type="button" onClick={() => stepMonth(-1)} disabled={selectedIndex === 0} aria-label="Предыдущий месяц">
            ◀
          </button>
          <strong>{selectedMonth.name} {selectedMonth.value.slice(0, 4)}</strong>
          <button type="button" onClick={() => stepMonth(1)} disabled={selectedIndex === stats.length - 1} aria-label="Следующий месяц">
            ▶
          </button>
        </div>
      }
    >
      <div className="student-stats__months" role="list">
        {stats.map((month, index) => (
          <button
            key={month.value}
            type="button"
            className={`student-stats__month student-stats__month--${month.tone} ${
              index === selectedIndex ? "student-stats__month--active" : ""
            }`.trim()}
            onClick={() => setSelectedIndex(index)}
          >
            {month.name}
          </button>
        ))}
      </div>

      <div className="student-stats__grid">
        <div className="student-stats__chart" aria-label={`График оценок за ${selectedMonth.name}`} data-month={selectedMonth.name}>
          <svg viewBox={`0 0 ${chart.width} ${chart.height}`} role="img">
            {[2, 3, 4, 5].map((grade) => {
              const y = 28 + ((5 - grade) / 3) * (190 - 56);
              return (
                <g key={grade}>
                  <line x1="28" x2="492" y1={y} y2={y} />
                  <text x="8" y={y + 4}>{grade}</text>
                </g>
              );
            })}
            {chart.path ? <path d={chart.path} /> : null}
            {chart.coordinates.map((point) => (
              <circle key={`${point.day}-${point.grade}`} cx={point.x} cy={point.y} r="5" />
            ))}
          </svg>
          {!chart.coordinates.length ? <p className="student-stats__empty">В этом месяце пока нет оценок.</p> : null}
        </div>

        <div className="student-stats__cards">
          <div>
            <span>Средний балл</span>
            <strong>{formatStatAverage(selectedMonth.average_grade)}</strong>
          </div>
          <div>
            <span>Оценок</span>
            <strong>{selectedMonth.grades_count}</strong>
          </div>
          <div>
            <span>Посещений</span>
            <strong>{selectedMonth.attendance_count}</strong>
          </div>
          <div>
            <span>Пропусков</span>
            <strong>{selectedMonth.absence_count}</strong>
          </div>
        </div>
      </div>
      <div className="student-stats__chart-grid">
        <ChartJsMonthChart months={visibleStats} />
      </div>
    </Panel>
  );
}

function StudentOverviewPanel({ overview }) {
  return (
    <Panel eyebrow="Сводка" title="Моя учеба" description="Короткая информация по группе, ментору и текущим результатам.">
      <div className="list-stack">
        <div className="list-card">
          <div>
            <strong>Группа</strong>
            <p>{overview.group_name}</p>
          </div>
          <Badge tone="teal">Активная</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Ментор</strong>
            <p>{overview.mentor_name}</p>
          </div>
          <Badge tone="blue">Куратор</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Посещений</strong>
            <p>Отмеченные посещения в табеле</p>
          </div>
          <Badge tone="sand">{overview.attendance_count}</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Оценок</strong>
            <p>Все выставленные отметки</p>
          </div>
          <Badge tone="teal">{overview.grades_count}</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Средний балл</strong>
            <p>Текущая средняя успеваемость</p>
          </div>
          <Badge tone="blue">{overview.average_grade}</Badge>
        </div>
      </div>
    </Panel>
  );
}

function DashboardListPanel({ eyebrow, title, description, children }) {
  return (
    <Panel eyebrow={eyebrow} title={title} description={description} className="dashboard-panel">
      <div className="dashboard-panel__scroll">{children}</div>
    </Panel>
  );
}

export function DashboardPage({ api, sessionToken, user }) {
  const { data, error, loading, reload } = useResource(() => api("/api/dashboard/"), [sessionToken]);

  if (loading) {
    return <LoadingBlock label="Загружаем дашборд..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  const isStudentDashboard = Boolean(data.student_overview);
  const isAdminDashboard = user.role === "ADMIN" && !isStudentDashboard;

  return (
    <div className={`page-stack ${isAdminDashboard ? "dashboard-page dashboard-page--admin" : ""}`.trim()}>
      <section className="hero-band">
        <div>
          <p className="hero-band__eyebrow">РАБОЧАЯ ЗОНА</p>
          <h2>{data.dashboard_title}</h2>
          <p>{data.dashboard_copy}</p>
        </div>
        <div className="hero-band__meta">
          <strong>{user.full_name}</strong>
          <span>{user.username}</span>
        </div>
      </section>

      {isStudentDashboard ? (
        <StudentSummaryStats stats={data.student_monthly_stats} />
      ) : (
        <div className="metric-grid">
          {data.summary_cards.map((card) => (
            <MetricCard key={card.label} label={card.label} value={card.value} tone={card.tone} />
          ))}
        </div>
      )}

      {isStudentDashboard ? (
        <>
          <StudentStatsPanel stats={data.student_monthly_stats} />
          <StudentOverviewPanel overview={data.student_overview} />
        </>
      ) : (
        <div className={`split-grid ${isAdminDashboard ? "dashboard-panels" : ""}`.trim()}>
          {data.groups ? (
            <DashboardListPanel
              eyebrow="Группы"
              title="Активные потоки"
              description="Быстрый переход к группе и месячному табелю."
            >
              {data.groups.length ? (
                <div className="list-stack dashboard-list">
                  {data.groups.map((group) => (
                    <a key={group.id} className="list-card" href={`#/groups/${group.id}`}>
                      <div>
                        <strong>{group.course_name}</strong>
                        <p>{group.mentor_name}</p>
                      </div>
                      <Badge tone="sand">{group.students_count} студентов</Badge>
                    </a>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет групп" description="Добавьте первую группу, чтобы запустить табель." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.mentors ? (
            <DashboardListPanel eyebrow="Команда" title="Менторы" description="Кто сейчас ведет группы.">
              {data.mentors.length ? (
                <div className="list-stack dashboard-list">
                  {data.mentors.map((mentor) => (
                    <div key={mentor.id} className="list-card">
                      <div>
                        <strong>{mentor.full_name}</strong>
                        <p>Куратор учебных групп</p>
                      </div>
                      <Badge tone="teal">{mentor.groups_count} групп</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Нет менторов" description="После добавления они появятся здесь." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.students ? (
            <DashboardListPanel
              eyebrow="Студенты"
              title="Последние записи"
              description="Список участников, доступных по вашей роли."
            >
              {data.students.length ? (
                <div className="list-stack dashboard-list">
                  {data.students.map((student) => (
                    <div key={student.id} className="list-card">
                      <div>
                        <strong>{student.full_name}</strong>
                        <p>{student.group_name}</p>
                      </div>
                      <Badge tone="blue">{student.parent_name}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет студентов" description="Когда студенты появятся в системе, они будут здесь." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.recent_lessons ? (
            <DashboardListPanel
              eyebrow="Занятия"
              title="Последние уроки"
              description="Свежие записи по журналу занятий."
            >
              {data.recent_lessons.length ? (
                <div className="list-stack dashboard-list">
                  {data.recent_lessons.map((lesson) => (
                    <div key={lesson.id} className="list-card">
                      <div>
                        <strong>{lesson.topic || "Без темы"}</strong>
                        <p>{lesson.group_name}</p>
                      </div>
                      <Badge tone="neutral">{formatDate(lesson.lesson_date)}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет уроков" description="Созданные уроки сразу появятся на дашборде." />
              )}
            </DashboardListPanel>
          ) : null}
        </div>
      )}
    </div>
  );
}
