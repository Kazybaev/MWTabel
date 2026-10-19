import { useEffect, useState } from "react";

import { Button, Modal, SelectField, TextAreaField } from "./Ui";

function emptyGradeDraft() {
  return { score: "", comment: "" };
}

function formatTimestamp(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function AgrarianRecordModal({ api, target, gradeChoices, onClose, onChanged, onNotice }) {
  const [records, setRecords] = useState(target?.entries || []);
  const [gradeDraft, setGradeDraft] = useState(emptyGradeDraft());
  const [editingId, setEditingId] = useState(null);
  const [badges, setBadges] = useState([]);
  const [awards, setAwards] = useState([]);
  const [badgeDraft, setBadgeDraft] = useState({ badge: "", comment: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRecords(target?.entries || []);
    setGradeDraft(emptyGradeDraft());
    setEditingId(null);
    setBadgeDraft({ badge: "", comment: "" });
    if (!target) return;
    Promise.all([
      api("/api/badges/"),
      api(`/api/student-badges/?student=${target.student.id}&group=${target.groupId}`),
    ])
      .then(([badgeTypes, studentAwards]) => {
        setBadges(badgeTypes || []);
        setAwards(studentAwards || []);
      })
      .catch((error) => onNotice({ tone: "danger", message: error.message }));
  }, [api, onNotice, target]);

  if (!target) return null;

  async function saveGrade(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const record = await api(editingId ? `/api/grade-records/${editingId}/` : "/api/grade-records/", {
        method: editingId ? "PATCH" : "POST",
        body: editingId ? gradeDraft : {
          ...gradeDraft,
          student: target.student.id,
          group: target.groupId,
          date: target.date,
        },
      });
      setRecords((current) => editingId
        ? current.map((item) => (item.id === record.id ? record : item))
        : [...current, record]);
      setEditingId(null);
      setGradeDraft(emptyGradeDraft());
      onNotice({ tone: "success", message: editingId ? "Оценка обновлена." : "Оценка успешно добавлена. Можно добавить ещё одну." });
      await onChanged();
    } catch (error) {
      onNotice({ tone: "danger", message: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function deleteGrade(recordId) {
    setSaving(true);
    try {
      await api(`/api/grade-records/${recordId}/`, { method: "DELETE" });
      setRecords((current) => current.filter((item) => item.id !== recordId));
      onNotice({ tone: "success", message: "Оценка удалена." });
      await onChanged();
    } catch (error) {
      onNotice({ tone: "danger", message: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function awardBadge(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const award = await api("/api/student-badges/", {
        method: "POST",
        body: {
          student: target.student.id,
          group: target.groupId,
          badge: Number(badgeDraft.badge),
          comment: badgeDraft.comment,
        },
      });
      setAwards((current) => [award, ...current]);
      setBadgeDraft({ badge: "", comment: "" });
      onNotice({ tone: "success", message: "Значок выдан. Можно выбрать следующий." });
    } catch (error) {
      onNotice({ tone: "danger", message: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function deleteAward(awardId) {
    setSaving(true);
    try {
      await api(`/api/student-badges/${awardId}/`, { method: "DELETE" });
      setAwards((current) => current.filter((item) => item.id !== awardId));
      onNotice({ tone: "success", message: "Выданный значок удалён." });
    } catch (error) {
      onNotice({ tone: "danger", message: error.message });
    } finally {
      setSaving(false);
    }
  }

  function startEditing(record) {
    setEditingId(record.id);
    setGradeDraft({ score: record.score, comment: record.comment || "" });
  }

  return (
    <Modal
      open
      title={`${target.student.full_name} · ${target.date}`}
      description="Каждая оценка и каждый значок сохраняются отдельной записью."
      onClose={onClose}
    >
      <div className="agrarian-records">
        <section className="agrarian-records__section">
          <div className="agrarian-records__heading">
            <div><strong>Оценки за день</strong><span>{records.length} записей</span></div>
          </div>
          <div className="agrarian-records__list">
            {records.length ? records.map((record) => (
              <article key={record.id} className="agrarian-record-card">
                <span className={`agrarian-record-card__score agrarian-record-card__score--${record.score === "Н" ? "absence" : record.score}`}>{record.score}</span>
                <div>
                  <p>{record.comment || "Без комментария"}</p>
                  <small>{record.teacher_name || "Автор не указан"} · {formatTimestamp(record.created_at)}</small>
                </div>
                <div className="agrarian-record-card__actions">
                  <Button variant="ghost" onClick={() => startEditing(record)} disabled={saving}>Изменить</Button>
                  <Button variant="danger" onClick={() => deleteGrade(record.id)} disabled={saving}>Удалить</Button>
                </div>
              </article>
            )) : <p className="agrarian-records__empty">В этот день оценок пока нет.</p>}
          </div>
          <form className="agrarian-records__form" onSubmit={saveGrade}>
            <SelectField label="Оценка" value={gradeDraft.score} onChange={(score) => setGradeDraft((current) => ({ ...current, score }))} options={gradeChoices} required />
            <TextAreaField label="Комментарий к оценке" value={gradeDraft.comment} onChange={(comment) => setGradeDraft((current) => ({ ...current, comment }))} rows={3} placeholder="За что поставлена оценка" />
            <div className="agrarian-records__form-actions">
              {editingId ? <Button variant="ghost" onClick={() => { setEditingId(null); setGradeDraft(emptyGradeDraft()); }}>Отмена</Button> : null}
              <Button type="submit" disabled={saving || !gradeDraft.score}>{saving ? "Сохраняем..." : editingId ? "Сохранить изменения" : "Добавить оценку"}</Button>
            </div>
          </form>
        </section>

        <section className="agrarian-records__section">
          <div className="agrarian-records__heading"><div><strong>Достижения студента</strong><span>{awards.length} значков в этой группе</span></div></div>
          <div className="agrarian-badges">
            {awards.map((award) => (
              <article key={award.id} className="agrarian-badge-card">
                <span className="agrarian-badge-card__icon" aria-hidden="true">{award.badge_icon}</span>
                <div><strong>{award.badge_name}</strong><p>{award.comment || "Без комментария"}</p><small>{award.teacher_name} · {formatTimestamp(award.created_at)}</small></div>
                <Button variant="danger" onClick={() => deleteAward(award.id)} disabled={saving}>Удалить</Button>
              </article>
            ))}
          </div>
          <form className="agrarian-records__form" onSubmit={awardBadge}>
            <SelectField label="Значок" value={badgeDraft.badge} onChange={(badge) => setBadgeDraft((current) => ({ ...current, badge }))} options={badges.map((badge) => ({ value: String(badge.id), label: `${badge.icon} ${badge.name}` }))} required />
            <TextAreaField label="Комментарий к значку" value={badgeDraft.comment} onChange={(comment) => setBadgeDraft((current) => ({ ...current, comment }))} rows={3} placeholder="За что выдан значок" />
            <div className="agrarian-records__form-actions"><Button type="submit" disabled={saving || !badgeDraft.badge}>{saving ? "Сохраняем..." : "Выдать значок"}</Button></div>
          </form>
        </section>
      </div>
    </Modal>
  );
}
