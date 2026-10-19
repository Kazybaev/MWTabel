const DATE_LOCALE = "ru-RU";

export function formatDate(value) {
  if (!value) {
    return "—";
  }

  return new Intl.DateTimeFormat(DATE_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}

export function formatLongDate(value) {
  if (!value) {
    return "—";
  }

  return new Intl.DateTimeFormat(DATE_LOCALE, {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(value));
}

export function formatMonthLabel(value) {
  if (!value) {
    return "—";
  }

  return new Intl.DateTimeFormat(DATE_LOCALE, {
    month: "long",
    year: "numeric",
  }).format(new Date(`${value}-01`));
}

export function formatRole(value) {
  return {
    ADMIN: "Администратор",
    MENTOR: "Ментор",
    STUDENT: "Студент",
  }[value] || value;
}

export function toMonthValue(dateInput = new Date()) {
  const year = dateInput.getFullYear();
  const month = `${dateInput.getMonth() + 1}`.padStart(2, "0");
  return `${year}-${month}`;
}

export function formatGradeCount(count = 0) {
  const value = Number(count) || 0;
  const lastTwo = value % 100;
  const lastOne = value % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return `${value} оценок`;
  if (lastOne === 1) return `${value} оценка`;
  if (lastOne >= 2 && lastOne <= 4) return `${value} оценки`;
  return `${value} оценок`;
}

export function buildGradeMap(rows = []) {
  const entries = {};

  rows.forEach((row) => {
    row.cells.forEach((cell) => {
      entries[`${row.student.id}|${cell.date}`] = cell.grade || "";
    });
  });

  return entries;
}
