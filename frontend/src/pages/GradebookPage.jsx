import { useCallback, useEffect, useRef, useState } from "react";

import { GradebookMatrix } from "../components/GradebookMatrix";
import { AgrarianRecordModal } from "../components/AgrarianRecordModal";
import { Button, EmptyState, ErrorBlock, LoadingBlock } from "../components/Ui";
import { toMonthValue } from "../lib/format";
import { navigateTo } from "../lib/router";
import { useResource } from "../lib/useResource";

const activeSaves = new Map();

function applySavedGrades(data, { lesson_dates, rows }) {
  const lessonDates = new Set(lesson_dates);
  const updates = new Map(rows.map((row) => [row.student_id, row]));
  return {
    ...data,
    filled_days_count: lessonDates.size,
    month_columns: data.month_columns.map((column) => ({
      ...column,
      has_lesson: lessonDates.has(column.date),
    })),
    rows: data.rows.map((row) => {
      const update = updates.get(row.student.id);
      if (!update) return row;
      const grades = new Map(update.cells.map((cell) => [cell.date, cell.grade]));
      return {
        ...row,
        average_grade: update.average_grade,
        attendance_count: update.attendance_count,
        cells: row.cells.map((cell) => grades.has(cell.date) ? { ...cell, grade: grades.get(cell.date) } : cell),
      };
    }),
  };
}

function removeSavedDrafts(current, entries, pending) {
  const next = { ...current };
  for (const [key, { student, date }] of entries) {
    if (pending.has(key)) continue;
    const grades = { ...next[student] };
    delete grades[date];
    if (Object.keys(grades).length) {
      next[student] = grades;
    } else {
      delete next[student];
    }
  }
  return next;
}

export function GradebookPage({ user, groupId, routeMonth, mode = "group", archived = false, ...props }) {
  const resolvedGroupId = mode === "student" ? user.group_id : groupId;
  const monthValue = routeMonth || toMonthValue();
  return (
    <GradebookMonth
      key={`${resolvedGroupId}/${monthValue}/${mode}/${archived}`}
      {...props}
      user={user}
      groupId={resolvedGroupId}
      monthValue={monthValue}
      mode={mode}
      archived={archived}
    />
  );
}

function GradebookMonth({ api, sessionToken, user, groupId, monthValue, onNotice, mode, archived }) {
  const [draftGrades, setDraftGrades] = useState({});
  const [saveStatus, setSaveStatus] = useState("synced");
  const [agrarianTarget, setAgrarianTarget] = useState(null);
  const queueRef = useRef({ pending: new Map(), timer: null, inFlight: null, flush: null, mounted: true });
  const endpoint = `/api/groups/${groupId}/gradebook/`;
  const saveKey = `${endpoint}${monthValue}`;
  const routePath = mode === "student" ? "/my-grades" : `/groups/${groupId}/gradebook`;
  const { data, error, loading, reload, setData } = useResource(async () => {
    if (!groupId) return null;

    // A quick return to the same month must wait for the previous screen's save.
    while (activeSaves.has(saveKey)) {
      await activeSaves.get(saveKey);
    }
    return api(`${endpoint}?month=${monthValue}${archived ? "&archived=1" : ""}`);
  }, [sessionToken]);

  useEffect(() => {
    const queue = queueRef.current;
    queue.mounted = true;
    return () => {
      queue.mounted = false;
      queue.flush?.();
    };
  }, []);

  const flush = useCallback(() => {
    const queue = queueRef.current;
    window.clearTimeout(queue.timer);
    queue.timer = null;
    if (queue.inFlight || !queue.pending.size) return;

    const entries = queue.pending;
    queue.pending = new Map();
    if (queue.mounted) setSaveStatus("saving");
    const request = Promise.resolve().then(async () => {
      let saved = false;
      try {
        const payload = await api(endpoint, {
          method: "PATCH",
          body: { month: monthValue, entries: [...entries.values()] },
        });
        saved = true;
        if (queue.mounted) {
          const unsaved = new Set(queue.pending.keys());
          setData((current) => applySavedGrades(current, payload));
          setDraftGrades((current) => removeSavedDrafts(current, entries, unsaved));
          setSaveStatus(queue.pending.size ? "pending" : "synced");
        }
      } catch (error) {
        queue.pending = new Map([...entries, ...queue.pending]);
        window.clearTimeout(queue.timer);
        queue.timer = null;
        if (queue.mounted) setSaveStatus("error");
        onNotice({ tone: "danger", message: error.message });
      } finally {
        queue.inFlight = null;
        activeSaves.delete(saveKey);
        if (saved && queue.pending.size && queue.timer === null) {
          queue.flush();
        }
      }
    });
    queue.inFlight = request;
    activeSaves.set(saveKey, request);
  }, [api, endpoint, monthValue, onNotice, saveKey, setData]);

  const handleGradeChange = useCallback((student, date, grade) => {
    const queue = queueRef.current;
    queue.pending.set(`${student}|${date}`, { student, date, grade });
    queue.flush = flush;
    setDraftGrades((current) => ({
      ...current,
      [student]: { ...current[student], [date]: grade },
    }));
    setSaveStatus("pending");
    window.clearTimeout(queue.timer);
    queue.timer = window.setTimeout(flush, 300);
  }, [flush]);

  const handleOpenAgrarianCell = useCallback((student, cell) => {
    setAgrarianTarget({ student, groupId, date: cell.date, entries: cell.grade_entries || [] });
  }, [groupId]);

  function handleMonthNavigation(nextMonth) {
    navigateTo(routePath, { month: nextMonth });
  }

  if (!groupId) {
    return (
      <EmptyState
        title="Группа не назначена"
        description="Когда администратор прикрепит вас к группе, здесь откроется месячный табель."
      />
    );
  }

  if (loading) {
    return <LoadingBlock label="Загружаем табель..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  if (!data) {
    return <EmptyState title="Табель не найден" description="Проверьте адрес группы или выберите другой месяц." />;
  }

  return (
    <>
      <GradebookMatrix
        data={data}
        draftGrades={draftGrades}
        onGradeChange={handleGradeChange}
        onRetrySave={flush}
        saveStatus={saveStatus}
        monthValue={monthValue}
        onMonthChange={handleMonthNavigation}
        onMonthStep={handleMonthNavigation}
        mentorMode={user.role === "MENTOR"}
        adminMode={user.role === "ADMIN"}
        lockedMode={mode === "student" || user.role === "MENTOR" || user.role === "ADMIN"}
        studentMode={mode === "student"}
        onOpenAgrarianCell={handleOpenAgrarianCell}
      />
      {agrarianTarget ? (
        <AgrarianRecordModal
          api={api}
          target={agrarianTarget}
          gradeChoices={data.grade_choices}
          onClose={() => setAgrarianTarget(null)}
          onChanged={reload}
          onNotice={onNotice}
        />
      ) : null}
    </>
  );
}
