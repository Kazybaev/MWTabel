import { useEffect, useEffectEvent, useRef, useState } from "react";

import { GradebookMatrix } from "../components/GradebookMatrix";
import { Button, EmptyState, ErrorBlock, LoadingBlock } from "../components/Ui";
import { buildGradeMap, toMonthValue } from "../lib/format";
import { navigateTo } from "../lib/router";
import { useResource } from "../lib/useResource";

function buildEntriesFromDraft(draftGrades) {
  return Object.entries(draftGrades)
    .filter(([, value]) => value)
    .map(([key, grade]) => {
      const [student, date] = key.split("|");
      return {
        student: Number(student),
        date,
        grade,
      };
    });
}

function hasDraftChanges(sourceGrades = {}, draftGrades = {}) {
  const keys = new Set([...Object.keys(sourceGrades), ...Object.keys(draftGrades)]);

  for (const key of keys) {
    if ((sourceGrades[key] || "") !== (draftGrades[key] || "")) {
      return true;
    }
  }

  return false;
}

function serializeGradeMap(gradeMap = {}) {
  return JSON.stringify(
    Object.entries(gradeMap).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey)),
  );
}

export function GradebookPage({ api, sessionToken, user, groupId, routeMonth, onNotice, mode = "group" }) {
  const resolvedGroupId = mode === "student" ? user.group_id : groupId;
  const monthValue = routeMonth || toMonthValue();
  const lockedGradebook = mode === "student" || user.role === "MENTOR" || user.role === "ADMIN";
  const [draftGrades, setDraftGrades] = useState({});
  const [persistedGrades, setPersistedGrades] = useState({});
  const [saveStatus, setSaveStatus] = useState("synced");
  const saveTimerRef = useRef(null);
  const saveRequestIdRef = useRef(0);
  const latestDraftSignatureRef = useRef(serializeGradeMap({}));
  const routePath = mode === "student" ? "/my-grades" : `/groups/${resolvedGroupId}/gradebook`;
  const { data, error, loading, reload, setData } = useResource(
    () => {
      if (!resolvedGroupId) {
        return Promise.resolve(null);
      }
      return api(`/api/groups/${resolvedGroupId}/gradebook/?month=${monthValue}`);
    },
    [sessionToken, resolvedGroupId, monthValue],
  );

  useEffect(() => {
    if (!data?.rows) {
      return;
    }

    const nextGrades = buildGradeMap(data.rows);
    latestDraftSignatureRef.current = serializeGradeMap(nextGrades);
    setDraftGrades(nextGrades);
    setPersistedGrades(nextGrades);
    setSaveStatus("synced");
  }, [data]);

  useEffect(() => {
    latestDraftSignatureRef.current = serializeGradeMap(draftGrades);
  }, [draftGrades]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, []);

  function handleMonthNavigation(nextMonth) {
    navigateTo(routePath, { month: nextMonth });
  }

  function handleGradeChange(studentId, date, grade) {
    setDraftGrades((current) => ({
      ...current,
      [`${studentId}|${date}`]: grade,
    }));
  }

  const persistSnapshot = useEffectEvent(async (snapshot, requestId) => {
    if (!resolvedGroupId || !data?.can_edit) {
      return;
    }

    const snapshotSignature = serializeGradeMap(snapshot);
    setSaveStatus("saving");

    try {
      const payload = await api(`/api/groups/${resolvedGroupId}/gradebook/`, {
        method: "POST",
        body: {
          month: monthValue,
          entries: buildEntriesFromDraft(snapshot),
        },
      });
      setPersistedGrades(snapshot);

      if (saveRequestIdRef.current === requestId && latestDraftSignatureRef.current === snapshotSignature) {
        setData(payload);
        setSaveStatus("synced");
      }
    } catch (saveError) {
      if (saveRequestIdRef.current === requestId) {
        setSaveStatus("error");
      }
      onNotice({
        tone: "danger",
        message: saveError.message,
      });
    }
  });

  const dirty = hasDraftChanges(persistedGrades, draftGrades);

  useEffect(() => {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }

    if (!resolvedGroupId || !data?.can_edit) {
      return undefined;
    }

    if (!dirty) {
      setSaveStatus((current) => (current === "error" ? current : "synced"));
      return undefined;
    }

    setSaveStatus("pending");
    const snapshot = { ...draftGrades };
    const requestId = saveRequestIdRef.current + 1;
    saveRequestIdRef.current = requestId;
    saveTimerRef.current = window.setTimeout(() => {
      persistSnapshot(snapshot, requestId);
    }, 450);

    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
    };
  }, [data?.can_edit, dirty, draftGrades, monthValue, persistSnapshot, resolvedGroupId]);

  if (!resolvedGroupId) {
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
    <GradebookMatrix
      data={data}
      draftGrades={draftGrades}
      onGradeChange={handleGradeChange}
      saveStatus={saveStatus}
      monthValue={monthValue}
      onMonthChange={handleMonthNavigation}
      onMonthStep={handleMonthNavigation}
      dirty={dirty}
      mentorMode={user.role === "MENTOR"}
      lockedMode={lockedGradebook}
      studentMode={mode === "student"}
    />
  );
}
