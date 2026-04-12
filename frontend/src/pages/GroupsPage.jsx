import { useDeferredValue, useState } from "react";

import { useResource } from "../lib/useResource";
import {
  Badge,
  Button,
  EmptyState,
  ErrorBlock,
  LoadingBlock,
  Modal,
  Panel,
  SelectField,
  TextAreaField,
  TextField,
} from "../components/Ui";

function createEmptyGroup() {
  return {
    course_name: "",
    mentor: "",
    study_days: "",
    description: "",
  };
}

export function GroupsPage({ api, meta, sessionToken, user, onNotice }) {
  const { data, error, loading, reload } = useResource(() => api("/api/groups/"), [sessionToken]);
  const { data: mentors } = useResource(
    () => (user.role === "ADMIN" ? api("/api/mentors/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState(createEmptyGroup());
  const [editingId, setEditingId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const deferredSearch = useDeferredValue(search);
  const isMentorView = user.role === "MENTOR";

  if (!["ADMIN", "MENTOR"].includes(user.role)) {
    return <EmptyState title="Раздел закрыт" description="У вас нет доступа к списку групп." />;
  }

  const mentorOptions = (mentors || []).map((mentor) => ({
    value: `${mentor.id}`,
    label: mentor.full_name,
  }));

  function openCreate() {
    setEditingId(null);
    setDraft(createEmptyGroup());
    setEditorOpen(true);
  }

  function openEdit(group) {
    setEditingId(group.id);
    setDraft({
      course_name: group.course_name,
      mentor: `${group.mentor}`,
      study_days: group.study_days,
      description: group.description || "",
    });
    setEditorOpen(true);
  }

  async function handleSave(event) {
    event.preventDefault();
    setSaving(true);

    try {
      await api(editingId ? `/api/groups/${editingId}/` : "/api/groups/", {
        method: editingId ? "PATCH" : "POST",
        body: {
          ...draft,
          mentor: Number(draft.mentor),
        },
      });
      setEditorOpen(false);
      await reload();
      onNotice({
        tone: "success",
        message: editingId ? "Группа обновлена." : "Группа создана.",
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

  async function handleDelete() {
    if (!deleteTarget) {
      return;
    }

    setSaving(true);

    try {
      await api(`/api/groups/${deleteTarget.id}/`, {
        method: "DELETE",
      });
      setDeleteTarget(null);
      await reload();
      onNotice({
        tone: "success",
        message: "Группа удалена.",
      });
    } catch (deleteError) {
      onNotice({
        tone: "danger",
        message: deleteError.message,
      });
    } finally {
      setSaving(false);
    }
  }

  const groups = (data || []).filter((group) => {
    const haystack = `${group.course_name} ${group.mentor_name} ${group.study_days_label}`.toLowerCase();
    return haystack.includes(deferredSearch.trim().toLowerCase());
  });

  if (loading) {
    return <LoadingBlock label="Загружаем группы..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  return (
    <div className="page-stack">
      <Panel
        eyebrow={isMentorView ? "МОИ ГРУППЫ" : "Потоки"}
        title={isMentorView ? "Выберите группу" : "Группы"}
        description={
          isMentorView
            ? "Нажмите на нужную группу, и сразу откроется табель на месяц. Здесь только ваши группы."
            : "Главная точка входа в месячный табель и учебную структуру."
        }
        actions={
          <div className="toolbar">
            <input
              className="search-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={isMentorView ? "Поиск по названию группы" : "Поиск по курсу или ментору"}
            />
            {user.role === "ADMIN" ? <Button onClick={openCreate}>Создать группу</Button> : null}
          </div>
        }
      >
        {groups.length ? (
          isMentorView ? (
            <div className="mentor-groups-grid">
              {groups.map((group) => (
                <a key={group.id} className="mentor-group-card" href={`#/groups/${group.id}/gradebook`}>
                  <div className="mentor-group-card__header">
                    <strong>{group.course_name}</strong>
                    <Badge tone="sand">{group.students_count} студентов</Badge>
                  </div>
                  <p>{group.study_days_label}</p>
                  <div className="mentor-group-card__footer">
                    <span>Открыть табель</span>
                    <span className="mentor-group-card__arrow">→</span>
                  </div>
                </a>
              ))}
            </div>
          ) : (
            <div className="list-stack">
              {groups.map((group) => (
                <div key={group.id} className="list-card list-card--actions">
                  <div>
                    <strong>{group.course_name}</strong>
                    <p>
                      {group.mentor_name} · {group.study_days_label}
                    </p>
                  </div>
                  <div className="list-card__actions">
                    <Badge tone="sand">{group.students_count} студентов</Badge>
                    <a className="button button--ghost" href={`#/groups/${group.id}`}>
                      Открыть
                    </a>
                    <a className="button button--ghost" href={`#/groups/${group.id}/gradebook`}>
                      Табель
                    </a>
                    {user.role === "ADMIN" ? (
                      <>
                        <Button variant="ghost" onClick={() => openEdit(group)}>
                          Изменить
                        </Button>
                        <Button variant="danger" onClick={() => setDeleteTarget(group)}>
                          Удалить
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          <EmptyState
            title="Группы не найдены"
            description={
              isMentorView
                ? "У вас пока нет закрепленных групп или поиск ничего не нашел."
                : "Попробуйте сменить поиск или создайте новую группу."
            }
          />
        )}
      </Panel>

      <Modal
        open={editorOpen}
        title={editingId ? "Редактирование группы" : "Новая группа"}
        description="После создания можно сразу открыть месячный табель и начать выставлять оценки."
        onClose={() => setEditorOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditorOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" form="group-form" disabled={saving}>
              {saving ? "Сохраняем..." : "Сохранить"}
            </Button>
          </>
        }
      >
        <form id="group-form" className="form-grid" onSubmit={handleSave}>
          <TextField
            label="Название курса"
            value={draft.course_name}
            onChange={(value) => setDraft((current) => ({ ...current, course_name: value }))}
            required
          />
          <SelectField
            label="Ментор"
            value={draft.mentor}
            onChange={(value) => setDraft((current) => ({ ...current, mentor: value }))}
            options={mentorOptions}
            required
          />
          <SelectField
            label="Дни обучения"
            value={draft.study_days}
            onChange={(value) => setDraft((current) => ({ ...current, study_days: value }))}
            options={meta.study_day_choices || []}
            required
          />
          <TextAreaField
            label="Описание"
            value={draft.description}
            onChange={(value) => setDraft((current) => ({ ...current, description: value }))}
          />
        </form>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        title="Удалить группу"
        description={deleteTarget ? `Группа ${deleteTarget.course_name} будет удалена вместе с уроками и записями табеля.` : ""}
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              Отмена
            </Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? "Удаляем..." : "Удалить"}
            </Button>
          </>
        }
      />
    </div>
  );
}
