import { useDeferredValue, useState } from "react";

import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, Modal, Panel, SelectField } from "../components/Ui";
import { sortGroupsByName } from "../lib/groupSort";
import { useResource } from "../lib/useResource";

function normalizePhoneSearch(value) {
  return String(value || "").replace(/\D/g, "");
}

function archiveDate(value) {
  return value ? new Date(value).toLocaleDateString("ru-RU") : "—";
}

export function ArchivedStudentsPage({ api, sessionToken, user, onNotice, organization, collegeBranch }) {
  const { data, error, loading, reload } = useResource(
    () => (user.role === "ADMIN" ? api("/api/students/archived/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const { data: groups, error: groupsError, loading: groupsLoading, reload: reloadGroups } = useResource(
    () => (user.role === "ADMIN" ? api("/api/groups/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const { data: archivedGroups, error: archivedGroupsError, loading: archivedGroupsLoading, reload: reloadArchivedGroups } = useResource(
    () => (user.role === "ADMIN" ? api("/api/groups/archived/") : Promise.resolve([])),
    [sessionToken, user.role],
  );
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("students");
  const [restoreTarget, setRestoreTarget] = useState(null);
  const [restoreGroupTarget, setRestoreGroupTarget] = useState(null);
  const [restoreGroup, setRestoreGroup] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const deferredSearch = useDeferredValue(search);
  const organizationLabel = organization === "academy" ? "Академия" : collegeBranch === "agrarian" ? "Аграрный колледж" : "Кувейтский колледж";

  async function reloadArchive() {
    await Promise.all([reload(), reloadGroups(), reloadArchivedGroups()]);
  }

  async function handleRestoreGroup() {
    if (!restoreGroupTarget) return;
    setSaving(true);
    try {
      await api(`/api/groups/${restoreGroupTarget.id}/restore/`, { method: "POST" });
      setRestoreGroupTarget(null);
      await reloadArchive();
      onNotice({ tone: "success", message: "Группа восстановлена вместе с её студентами, уроками и оценками." });
    } catch (restoreError) {
      onNotice({ tone: "danger", message: restoreError.message });
    } finally {
      setSaving(false);
    }
  }

  if (user.role !== "ADMIN") {
    return <EmptyState title="Раздел закрыт" description="Архив студентов доступен только администратору." />;
  }

  const groupOptions = sortGroupsByName(groups).map((group) => ({
    value: `${group.id}`,
    label: `${group.course_name} · ${group.mentor_name}`,
  }));
  const students = (data || []).filter((student) => {
    const query = deferredSearch.trim().toLowerCase();
    const phoneQuery = normalizePhoneSearch(query);
    const haystack =
      `${student.full_name} ${student.username} ${student.group_name} ${student.parent_name} ${student.parent_phone}`.toLowerCase();
    return haystack.includes(query) || (phoneQuery && normalizePhoneSearch(student.parent_phone).includes(phoneQuery));
  });
  const filteredGroups = sortGroupsByName(archivedGroups).filter((group) => {
    const query = deferredSearch.trim().toLowerCase();
    return `${group.course_name} ${group.mentor_name} ${group.study_days_label}`.toLowerCase().includes(query);
  });

  async function handleRestore() {
    if (!restoreTarget || !restoreGroup) return;
    setSaving(true);
    try {
      await api(`/api/students/${restoreTarget.id}/restore/`, {
        method: "POST",
        body: { group: Number(restoreGroup) },
      });
      setRestoreTarget(null);
      setRestoreGroup("");
      await reloadArchive();
      onNotice({ tone: "success", message: "Студент перенесен в группу. Его аккаунт снова активен." });
    } catch (restoreError) {
      onNotice({ tone: "danger", message: restoreError.message });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setSaving(true);
    try {
      await api(`/api/students/${deleteTarget.id}/`, { method: "DELETE" });
      setDeleteTarget(null);
      await reload();
      onNotice({ tone: "success", message: "Студент и все связанные данные удалены навсегда." });
    } catch (deleteError) {
      onNotice({ tone: "danger", message: deleteError.message });
    } finally {
      setSaving(false);
    }
  }

  if (loading || archivedGroupsLoading || groupsLoading) return <LoadingBlock label="Загружаем архив..." />;
  if (error || archivedGroupsError || groupsError) return <ErrorBlock message={error || archivedGroupsError || groupsError} action={<Button onClick={reloadArchive}>Повторить</Button>} />;

  return (
    <div className="page-stack">
      <Panel
        eyebrow={`Архив · ${organizationLabel}`}
        title={activeTab === "students" ? "Архив студентов" : "Архив групп"}
        description={activeTab === "students" ? "Здесь хранятся студенты, которые временно не учатся. Их аккаунты отключены, а оценки сохранены." : "Здесь хранятся группы, которые были деактивированы. Уроки и оценки сохранены."}
        actions={
          <div className="toolbar">
            <div className="button-group" role="tablist" aria-label="Тип архива">
              <Button variant={activeTab === "students" ? "primary" : "ghost"} onClick={() => setActiveTab("students")}>Студенты ({data?.length || 0})</Button>
              <Button variant={activeTab === "groups" ? "primary" : "ghost"} onClick={() => setActiveTab("groups")}>Группы ({archivedGroups?.length || 0})</Button>
            </div>
            <input
              className="search-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={activeTab === "students" ? "Поиск по имени, группе, родителю или телефону" : "Поиск по названию группы или ментору"}
              aria-label={activeTab === "students" ? "Поиск в архиве студентов" : "Поиск в архиве групп"}
            />
          </div>
        }
      >
        {activeTab === "groups" ? (filteredGroups.length ? (
          <div className="list-stack">
            {filteredGroups.map((group) => (
              <div key={group.id} className="list-card list-card--actions list-card--archived">
                <div>
                  <strong>{group.course_name}</strong>
                  <p>{group.mentor_name} · {group.study_days_label}</p>
                  <small>В архиве с {archiveDate(group.archived_at)} · Студентов: {group.students_count}</small>
                </div>
                <div className="list-card__actions">
                  <Badge tone="slate">В архиве</Badge>
                  <a className="button button--ghost" href={`#/groups/${group.id}?archived=1`}>Открыть группу</a>
                  <a className="button button--ghost" href={`#/groups/${group.id}/gradebook?archived=1`}>Табель</a>
                  <Button disabled={saving} onClick={() => setRestoreGroupTarget(group)}>Восстановить</Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title={archivedGroups?.length ? "Группы не найдены" : "Архив групп пуст"} description={archivedGroups?.length ? "Попробуйте изменить поисковый запрос." : "Архивные группы появятся здесь после архивирования."} />
        )) : students.length ? (
          <div className="list-stack">
            {students.map((student) => (
              <div key={student.id} className="list-card list-card--actions list-card--archived">
                <div>
                  <strong>{student.full_name}</strong>
                  <p>Последняя группа: {student.group_name} · {student.parent_name}</p>
                  <small>{student.parent_phone}</small>
                  <p>В архиве с {archiveDate(student.archived_at)}</p>
                </div>
                <div className="list-card__actions">
                  <Badge tone="slate">В архиве</Badge>
                  <a className="button button--ghost" href={`#/students/${student.id}/gradebook`}>Оценки и посещаемость</a>
                  <Button
                    onClick={() => {
                      setRestoreTarget(student);
                      setRestoreGroup((groups || []).some((group) => group.id === student.group) ? String(student.group) : "");
                    }}
                  >
                    Восстановить
                  </Button>
                  <Button variant="danger" onClick={() => setDeleteTarget(student)}>
                    Удалить
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            title={data?.length ? "Студенты не найдены" : "Архив пуст"}
            description={data?.length ? "Попробуйте изменить поисковый запрос." : "Архивные студенты появятся здесь."}
          />
        )}
      </Panel>

      <Modal
        open={Boolean(restoreGroupTarget)}
        title="Восстановить группу"
        description={restoreGroupTarget ? `${restoreGroupTarget.course_name} вернётся в раздел «${organizationLabel}». Студенты, отправленные в архив вместе с группой, будут восстановлены. Уроки и оценки сохранятся. Студенты, архивированные отдельно, останутся в архиве.` : ""}
        onClose={() => !saving && setRestoreGroupTarget(null)}
        footer={<>
          <Button variant="ghost" disabled={saving} onClick={() => setRestoreGroupTarget(null)}>Отмена</Button>
          <Button disabled={saving} onClick={handleRestoreGroup}>{saving ? "Восстанавливаем..." : "Восстановить группу"}</Button>
        </>}
      />

      <Modal
        open={Boolean(restoreTarget)}
        title="Восстановить студента в группе"
        description={restoreTarget ? `Выберите группу для ${restoreTarget.full_name}. Все оценки будут сохранены.` : ""}
        onClose={() => setRestoreTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRestoreTarget(null)}>Отмена</Button>
            <Button onClick={handleRestore} disabled={saving || !restoreGroup}>
              {saving ? "Переносим..." : "Перенести"}
            </Button>
          </>
        }
      >
        <SelectField label="Группа" value={restoreGroup} onChange={setRestoreGroup} options={groupOptions} required />
        {!groupOptions.length ? <p>В разделе «{organizationLabel}» нет активных групп. Сначала восстановите группу из архива или создайте новую.</p> : null}
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        title="Удалить студента навсегда"
        description={deleteTarget ? `${deleteTarget.full_name}, его оценки и отчеты будут удалены без возможности восстановления.` : ""}
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>Отмена</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? "Удаляем..." : "Удалить"}
            </Button>
          </>
        }
      />
    </div>
  );
}
