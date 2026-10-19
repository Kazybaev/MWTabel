import { useDeferredValue, useState } from "react";

import { sortGroupsByName } from "../lib/groupSort";
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
    main_group: "",
    mentor: "",
    study_days: "",
    description: "",
  };
}

export function GroupsPage({ api, meta, sessionToken, user, onNotice, organization = "academy" }) {
  const { data, error, loading, reload } = useResource(() => api("/api/groups/"), [sessionToken]);
  const { data: mentors } = useResource(
    () => (user.role === "ADMIN" ? api("/api/mentors/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const isCollege = organization === "college";
  const { data: mainGroups, error: mainError, reload: reloadMainGroups } = useResource(
    () => isCollege ? api("/api/college-groups/") : Promise.resolve([]), [sessionToken, organization],
  );
  const [selectedMain, setSelectedMain] = useState(null);
  const [mainDraft, setMainDraft] = useState(null);
  const [search, setSearch] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState(createEmptyGroup());
  const [editingId, setEditingId] = useState(null);
  const [archiveTarget, setArchiveTarget] = useState(null);
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
    setDraft({ ...createEmptyGroup(), main_group: selectedMain || "", study_days: isCollege ? "MON_FRI" : "" });
    setEditorOpen(true);
  }

  function openEdit(group) {
    setEditingId(group.id);
    setDraft({
      course_name: group.course_name,
      main_group: group.main_group ? String(group.main_group) : "",
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
          main_group: isCollege && draft.main_group ? Number(draft.main_group) : null,
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

  async function saveMainGroup(event) {
    event.preventDefault();
    setSaving(true);
    try {
      await api(mainDraft.id ? `/api/college-groups/${mainDraft.id}/` : "/api/college-groups/", {
        method: mainDraft.id ? "PATCH" : "POST", body: { name: mainDraft.name },
      });
      setMainDraft(null);
      await reloadMainGroups();
      onNotice({ tone: "success", message: "Основная группа сохранена." });
    } catch (saveError) {
      onNotice({ tone: "danger", message: saveError.message });
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive() {
    if (!archiveTarget) {
      return;
    }

    setSaving(true);

    try {
      await api(`/api/groups/${archiveTarget.id}/archive/`, {
        method: "POST",
      });
      setArchiveTarget(null);
      await reload();
      onNotice({
        tone: "success",
        message: "Группа и связанные студенты перемещены в архив.",
      });
    } catch (archiveError) {
      onNotice({
        tone: "danger",
        message: archiveError.message,
      });
    } finally {
      setSaving(false);
    }
  }

  const groups = sortGroupsByName(data).filter((group) => {
    if (isCollege && (selectedMain === null || String(group.main_group || "") !== selectedMain)) return false;
    const haystack = `${group.course_name} ${group.mentor_name} ${group.study_days_label}`.toLowerCase();
    return haystack.includes(deferredSearch.trim().toLowerCase());
  });

  if (loading) {
    return <LoadingBlock label="Загружаем группы..." />;
  }

  if (error || mainError) {
    return <ErrorBlock message={error || mainError} action={<Button onClick={() => { reload(); reloadMainGroups(); }}>Повторить</Button>} />;
  }

  return (
    <div className="page-stack">
      {isCollege ? (
        <Panel title="Основные группы" description="Выберите группу, чтобы открыть её подгруппы и табели."
          actions={user.role === "ADMIN" ? <Button onClick={() => setMainDraft({ name: "" })}>Создать основную группу</Button> : null}>
          <div className="list-stack">
            {(mainGroups || []).map((main) => (
              <div key={main.id} className="list-card list-card--actions">
                <strong>{main.name}</strong>
                <div className="list-card__actions">
                  <Button variant={selectedMain === String(main.id) ? "primary" : "ghost"} onClick={() => setSelectedMain(String(main.id))}>Подгруппы</Button>
                  {user.role === "ADMIN" ? <Button variant="ghost" onClick={() => setMainDraft(main)}>Изменить название</Button> : null}
                </div>
              </div>
            ))}
            {(data || []).some((group) => !group.main_group) ? <Button variant="ghost" onClick={() => setSelectedMain("")}>Без основной группы</Button> : null}
            {!mainGroups?.length ? <p>Создайте основную группу и добавьте в неё подгруппы: ИИ, фронтенд, английский.</p> : null}
          </div>
        </Panel>
      ) : null}
      {(!isCollege || selectedMain !== null) ? <>

      <Panel
        className={isMentorView ? "groups-panel groups-panel--mentor" : "groups-panel"}
        eyebrow={isMentorView ? "МОИ ГРУППЫ" : "Потоки"}
        title={isCollege ? `Подгруппы · ${(mainGroups || []).find((main) => String(main.id) === selectedMain)?.name || "Без основной группы"}` : isMentorView ? "Выберите группу" : "Группы"}
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
            {user.role === "ADMIN" ? <Button onClick={openCreate}>{isCollege ? "Создать подгруппу" : "Создать группу"}</Button> : null}
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
                        <Button variant="danger" onClick={() => setArchiveTarget(group)}>
                          Архивировать
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

      </> : null}

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
            label={isCollege ? "Название подгруппы / предмета" : "Название курса"}
            value={draft.course_name}
            onChange={(value) => setDraft((current) => ({ ...current, course_name: value }))}
            required
          />
          {isCollege ? <SelectField label="Основная группа" value={draft.main_group}
            onChange={(value) => setDraft((current) => ({ ...current, main_group: value }))}
            options={(mainGroups || []).map((main) => ({ value: String(main.id), label: main.name }))} required /> : null}
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

      <Modal open={Boolean(mainDraft)} title={mainDraft?.id ? "Название основной группы" : "Новая основная группа"}
        onClose={() => setMainDraft(null)} footer={<Button type="submit" form="main-group-form" disabled={saving}>Сохранить</Button>}>
        <form id="main-group-form" onSubmit={saveMainGroup}>
          <TextField label="Название" value={mainDraft?.name || ""} onChange={(name) => setMainDraft((current) => ({ ...current, name }))} required />
        </form>
      </Modal>
      <Modal
        open={Boolean(archiveTarget)}
        title="Архивировать группу"
        description={archiveTarget ? `Группа ${archiveTarget.course_name} станет неактивной. Студенты будут архивированы, а уроки, оценки и история отчетов сохранятся.` : ""}
        onClose={() => setArchiveTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setArchiveTarget(null)}>
              Отмена
            </Button>
            <Button variant="danger" onClick={handleArchive} disabled={saving}>
              {saving ? "Архивируем..." : "Архивировать"}
            </Button>
          </>
        }
      />
    </div>
  );
}
