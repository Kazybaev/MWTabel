import { useDeferredValue, useState } from "react";

import { generateStrongPassword } from "../lib/password";
import { useResource } from "../lib/useResource";
import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, Modal, Panel, TextField } from "../components/Ui";

function createEmptyMentor() {
  return {
    full_name: "",
    username: "",
    email: "",
    password: "",
  };
}

export function MentorsPage({ api, sessionToken, user, onNotice }) {
  const { data, error, loading, reload } = useResource(() => api("/api/mentors/"), [sessionToken]);
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState(createEmptyMentor());
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const deferredSearch = useDeferredValue(search);

  if (user.role !== "ADMIN") {
    return <EmptyState title="Раздел закрыт" description="Только администратор может управлять менторами." />;
  }

  function openCreate() {
    setEditingId(null);
    setDraft(createEmptyMentor());
    setEditorOpen(true);
  }

  function openEdit(mentor) {
    setEditingId(mentor.id);
    setDraft({
      full_name: mentor.full_name,
      username: mentor.username,
      email: mentor.email || "",
      password: "",
    });
    setEditorOpen(true);
  }

  async function handleSave(event) {
    event.preventDefault();
    setSaving(true);

    try {
      await api(editingId ? `/api/mentors/${editingId}/` : "/api/mentors/", {
        method: editingId ? "PATCH" : "POST",
        body: draft,
      });
      setEditorOpen(false);
      await reload();
      onNotice({
        tone: "success",
        message: editingId ? "Данные ментора обновлены." : "Ментор создан.",
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
      await api(`/api/mentors/${deleteTarget.id}/`, {
        method: "DELETE",
      });
      setDeleteTarget(null);
      await reload();
      onNotice({
        tone: "success",
        message: "Ментор удален.",
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

  const mentors = (data || []).filter((mentor) => {
    const haystack = `${mentor.full_name} ${mentor.username} ${mentor.email}`.toLowerCase();
    return haystack.includes(deferredSearch.trim().toLowerCase());
  });

  if (loading) {
    return <LoadingBlock label="Загружаем менторов..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  return (
    <div className="page-stack">
      <Panel
        eyebrow="Команда"
        title="Менторы"
        description="Добавляйте преподавателей, обновляйте доступы и следите за нагрузкой по группам."
        actions={
          <div className="toolbar">
            <input
              className="search-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по имени или логину"
            />
            <Button onClick={openCreate}>Добавить ментора</Button>
          </div>
        }
      >
        {mentors.length ? (
          <div className="list-stack">
            {mentors.map((mentor) => (
              <div key={mentor.id} className="list-card list-card--actions">
                <div>
                  <strong>{mentor.full_name}</strong>
                  <p>{mentor.email || "Доступ к аккаунту ментора настроен"}</p>
                </div>
                <div className="list-card__actions">
                  <Badge tone="teal">{mentor.groups_count} групп</Badge>
                  <Button variant="ghost" onClick={() => openEdit(mentor)}>
                    Изменить
                  </Button>
                  <Button variant="danger" onClick={() => setDeleteTarget(mentor)}>
                    Удалить
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="Менторы не найдены" description="Смените фильтр или добавьте первого ментора." />
        )}
      </Panel>

      <Modal
        open={editorOpen}
        title={editingId ? "Редактирование ментора" : "Новый ментор"}
        description="Логин и пароль понадобятся для входа в React-интерфейс."
        onClose={() => setEditorOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditorOpen(false)}>
              Отмена
            </Button>
            <Button type="submit" form="mentor-form" disabled={saving}>
              {saving ? "Сохраняем..." : "Сохранить"}
            </Button>
          </>
        }
      >
        <form id="mentor-form" className="form-grid" onSubmit={handleSave}>
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
        </form>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        title="Удалить ментора"
        description={deleteTarget ? `Аккаунт ${deleteTarget.full_name} будет удален вместе с профилем.` : ""}
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
