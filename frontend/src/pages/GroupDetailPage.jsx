import { useState } from "react";

import { useResource } from "../lib/useResource";
import { formatDate } from "../lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  Modal,
  Panel,
  TextField,
} from "../components/Ui";

export function GroupDetailPage({ api, sessionToken, groupId, user, onNotice }) {
  const { data, error, loading, reload } = useResource(() => api(`/api/groups/${groupId}/`), [sessionToken, groupId]);
  const [lessonEditorOpen, setLessonEditorOpen] = useState(false);
  const [lessonDraft, setLessonDraft] = useState({
    lesson_date: new Date().toISOString().slice(0, 10),
    topic: "",
  });
  const [saving, setSaving] = useState(false);

  if (loading) {
    return <LoadingBlock label="Загружаем группу..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  if (!data) {
    return <EmptyState title="Группа не найдена" description="Проверьте адрес или вернитесь к списку групп." />;
  }

  async function handleCreateLesson(event) {
    event.preventDefault();
    setSaving(true);

    try {
      await api("/api/lessons/", {
        method: "POST",
        body: {
          group: data.id,
          lesson_date: lessonDraft.lesson_date,
          topic: lessonDraft.topic,
        },
      });
      setLessonEditorOpen(false);
      setLessonDraft({
        lesson_date: new Date().toISOString().slice(0, 10),
        topic: "",
      });
      await reload();
      onNotice({
        tone: "success",
        message: "Урок добавлен.",
      });
    } catch (saveError) {
      onNotice({
        tone: "danger",
        message: saveError.message,
      });
    } finally {
      setSaving(false);
    }
  }

  const canManageLessons = ["ADMIN", "MENTOR"].includes(user.role);

  return (
    <div className="page-stack">
      <section className="hero-band">
        <div>
          <p className="hero-band__eyebrow">ГРУППА</p>
          <h2>{data.course_name}</h2>
          <p>{data.description || "Описание пока не заполнено."}</p>
        </div>
        <div className="hero-band__meta">
          <strong>{data.mentor_name}</strong>
          <span>{data.study_days_label}</span>
        </div>
      </section>

      <div className="metric-grid">
        <Badge tone="teal">{data.students_count} студентов</Badge>
        <Badge tone="sand">{data.study_days_label}</Badge>
        <a className="button button--primary" href={`#/groups/${data.id}/gradebook`}>
          Открыть табель
        </a>
      </div>

      <div className="split-grid">
        <Panel eyebrow="Состав" title="Студенты группы" description="Участники, закрепленные за этим потоком.">
          {user.role === "STUDENT" ? (
            <EmptyState
              title="Состав скрыт"
              description="Для студента в интерфейсе остаются доступны только личные оценки."
            />
          ) : data.students.length ? (
            <div className="list-stack">
              {data.students.map((student) => (
                <div key={student.id} className="list-card">
                  <div>
                    <strong>{student.full_name}</strong>
                    <p>{student.parent_name}</p>
                  </div>
                  <Badge tone="blue">{student.parent_phone}</Badge>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="Пока нет студентов" description="Добавьте студентов, чтобы открыть полноценный табель." />
          )}
        </Panel>

        <Panel
          eyebrow="Журнал"
          title="Уроки"
          description="Список созданных занятий этой группы."
          actions={
            canManageLessons ? <Button onClick={() => setLessonEditorOpen(true)}>Добавить урок</Button> : null
          }
        >
          {data.lessons.length ? (
            <div className="list-stack">
              {data.lessons.map((lesson) => (
                <div key={lesson.id} className="list-card">
                  <div>
                    <strong>{lesson.topic || "Урок без темы"}</strong>
                    <p>{lesson.records.length} оценок в записи</p>
                  </div>
                  <Badge tone="neutral">{formatDate(lesson.lesson_date)}</Badge>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="Уроков пока нет" description="Созданные уроки будут появляться здесь и в табеле." />
          )}
        </Panel>
      </div>

      <Modal
        open={lessonEditorOpen}
        title="Новый урок"
        description="Урок появится в журнале, а дата сразу станет доступна в месячном табеле."
        onClose={() => setLessonEditorOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setLessonEditorOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" form="lesson-form" disabled={saving}>
              {saving ? "Сохраняем..." : "Добавить"}
            </Button>
          </>
        }
      >
        <form id="lesson-form" className="form-grid" onSubmit={handleCreateLesson}>
          <TextField
            label="Дата урока"
            value={lessonDraft.lesson_date}
            onChange={(value) => setLessonDraft((current) => ({ ...current, lesson_date: value }))}
            type="date"
            required
          />
          <TextField
            label="Тема"
            value={lessonDraft.topic}
            onChange={(value) => setLessonDraft((current) => ({ ...current, topic: value }))}
            placeholder="Например: Arrays и объекты"
          />
        </form>
      </Modal>
    </div>
  );
}
