import { useDeferredValue, useState } from "react";

import { generateStrongPassword } from "../lib/password";
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
  TextField,
} from "../components/Ui";

function createEmptyStudent() {
  return {
    full_name: "",
    username: "",
    email: "",
    password: "",
    parent_name: "",
    parent_phone: "",
    group: "",
  };
}

export function StudentsPage({ api, sessionToken, user, onNotice }) {
  const { data, error, loading, reload } = useResource(() => api("/api/students/"), [sessionToken]);
  const { data: groups } = useResource(
    () => (user.role === "ADMIN" ? api("/api/groups/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState(createEmptyStudent());
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const deferredSearch = useDeferredValue(search);

  if (!["ADMIN", "MENTOR"].includes(user.role)) {
    return <EmptyState title="Раздел закрыт" description="У вас нет доступа к списку студентов." />;
  }

  const groupOptions = (groups || []).map((group) => ({
    value: `${group.id}`,
    label: `${group.course_name} · ${group.mentor_name}`,
  }));

  function openCreate() {
    setEditingId(null);
    setDraft(createEmptyStudent());
    setEditorOpen(true);
  }

  function openEdit(student) {
    setEditingId(student.id);
    setDraft({
      full_name: student.full_name,
      username: student.username,
      email: student.email || "",
      password: "",
      parent_name: student.parent_name,
      parent_phone: student.parent_phone,
      group: `${student.group}`,
    });
    setEditorOpen(true);
  }

  async function handleSave(event) {
    event.preventDefault();
    setSaving(true);

    try {
      await api(editingId ? `/api/students/${editingId}/` : "/api/students/", {
        method: editingId ? "PATCH" : "POST",
        body: {
          ...draft,
          group: Number(draft.group),
        },
      });
      setEditorOpen(false);
      await reload();
      onNotice({
        tone: "success",
        message: editingId ? "Данные студента обновлены." : "Студент добавлен.",
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
      await api(`/api/students/${deleteTarget.id}/`, {
        method: "DELETE",
      });
      setDeleteTarget(null);
      await reload();
      onNotice({
        tone: "success",
        message: "Студент удален.",
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

  const students = (data || []).filter((student) => {
    const haystack = `${student.full_name} ${student.username} ${student.group_name} ${student.parent_name}`.toLowerCase();
    return haystack.includes(deferredSearch.trim().toLowerCase());
  });

  if (loading) {
    return <LoadingBlock label="Загружаем студентов..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  return (
    <div className="page-stack">
      <Panel
        eyebrow="Список"
        title="Студенты"
        description="Здесь можно быстро находить участников групп и управлять их учетными данными."
        actions={
          <div className="toolbar">
            <input
              className="search-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по имени, группе или родителю"
            />
            {user.role === "ADMIN" ? <Button onClick={openCreate}>Добавить студента</Button> : null}
          </div>
        }
      >
        {students.length ? (
          <div className="list-stack">
            {students.map((student) => (
              <div key={student.id} className="list-card list-card--actions">
                <div>
                  <strong>{student.full_name}</strong>
                  <p>
                    {student.group_name} · {student.parent_name}
                  </p>
                </div>
                <div className="list-card__actions">
                  <Badge tone="blue">{student.parent_phone}</Badge>
                  <a className="button button--ghost" href={`#/groups/${student.group}`}>
                    Группа
                  </a>
                  {user.role === "ADMIN" ? (
                    <>
                      <Button variant="ghost" onClick={() => openEdit(student)}>
                        Изменить
                      </Button>
                      <Button variant="danger" onClick={() => setDeleteTarget(student)}>
                        Удалить
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="Студенты не найдены" description="Попробуйте изменить поисковый запрос." />
        )}
      </Panel>

      <Modal
        open={editorOpen}
        title={editingId ? "Редактирование студента" : "Новый студент"}
        description="Студент увидит в системе только свои оценки и свою группу."
        onClose={() => setEditorOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditorOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" form="student-form" disabled={saving}>
              {saving ? "Сохраняем..." : "Сохранить"}
            </Button>
          </>
        }
      >
        <form id="student-form" className="form-grid" onSubmit={handleSave}>
          <TextField
            label="Полное имя"
            value={draft.full_name}
            onChange={(value) => setDraft((current) => ({ ...current, full_name: value }))}
            required
          />
          <TextField
            label="Логин"
            value={draft.username}
            onChange={(value) => setDraft((current) => ({ ...current, username: value }))}
            required
          />
          <TextField
            label="Email"
            value={draft.email}
            onChange={(value) => setDraft((current) => ({ ...current, email: value }))}
            type="email"
          />
          <TextField
            label="Пароль"
            value={draft.password}
            onChange={(value) => setDraft((current) => ({ ...current, password: value }))}
            type="password"
            revealable
            onGenerate={() => setDraft((current) => ({ ...current, password: generateStrongPassword() }))}
            help={editingId ? "Оставьте пустым, если менять пароль не нужно." : "Задайте стартовый пароль."}
          />
          <TextField
            label="Имя родителя"
            value={draft.parent_name}
            onChange={(value) => setDraft((current) => ({ ...current, parent_name: value }))}
            required
          />
          <TextField
            label="Телефон родителя"
            value={draft.parent_phone}
            onChange={(value) => setDraft((current) => ({ ...current, parent_phone: value }))}
            required
          />
          <SelectField
            label="Группа"
            value={draft.group}
            onChange={(value) => setDraft((current) => ({ ...current, group: value }))}
            options={groupOptions}
            required
          />
        </form>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        title="Удалить студента"
        description={deleteTarget ? `Аккаунт ${deleteTarget.full_name} будет удален вместе с оценками.` : ""}
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
