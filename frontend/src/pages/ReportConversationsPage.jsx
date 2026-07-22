import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, Modal } from "../components/Ui";
import { formatMonthLabel } from "../lib/format";
import { useResource } from "../lib/useResource";
import "./ReportConversationsPage.css";

const STATUS = {
  pending: { label: "В очереди", tone: "blue" },
  succeeded: { label: "Отправлено", tone: "teal" },
  failed: { label: "Ошибка", tone: "sand" },
};

function formatDateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function StatusBadge({ value }) {
  const status = STATUS[value] || { label: value, tone: "neutral" };
  return <Badge tone={status.tone}>{status.label}</Badge>;
}

function ReportMessage({ message }) {
  const metaResponse = message.meta?.response;
  const metaMessageId = metaResponse?.messages?.[0]?.id;

  return (
    <article className={`report-chat__message report-chat__message--${message.status}`}>
      <header className="report-chat__message-head">
        <div>
          <strong>Отчёт за {formatMonthLabel(message.month)}</strong>
          <span>{formatDateTime(message.sent_at || message.updated_at)}</span>
        </div>
        <StatusBadge value={message.status} />
      </header>

      <div className="report-chat__text" aria-label="Текст, отправленный родителю">
        {message.rendered_text}
      </div>

      <div className="report-chat__summary" aria-label="Сводка отчёта">
        <span>Средний балл <strong>{message.summary.average_grade ?? "—"}</strong></span>
        <span>Посещено <strong>{message.summary.attendance_count ?? 0}</strong></span>
        <span>Пропуски <strong>{message.summary.absence_count ?? 0}</strong></span>
        <span>Посещаемость <strong>{message.summary.attendance_rate ?? 0}%</strong></span>
      </div>

      {message.error_message ? <p className="report-chat__error">{message.error_message}</p> : null}

      <footer className="report-chat__delivery">
        <span>Meta HTTP: <strong>{message.meta?.status_code ?? "—"}</strong></span>
        {metaMessageId ? <span>ID Meta: <code>{metaMessageId}</code></span> : null}
      </footer>

      {metaResponse ? (
        <details className="report-chat__technical">
          <summary>Технический ответ Meta</summary>
          <pre>{JSON.stringify(metaResponse, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

export function ReportConversationsPage({ api, sessionToken, user }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedStudentId, setSelectedStudentId] = useState(null);
  const [confirmSendAll, setConfirmSendAll] = useState(false);
  const [sendingAll, setSendingAll] = useState(false);
  const [sendAllResult, setSendAllResult] = useState(null);
  const [sendAllError, setSendAllError] = useState("");
  const messagesRef = useRef(null);
  const conversations = useResource(() => api("/api/reports/conversations/"), [sessionToken]);
  const activeStudentId = selectedStudentId || conversations.data?.[0]?.student_id || null;
  const detail = useResource(
    () => activeStudentId ? api(`/api/reports/conversations/${activeStudentId}/`) : Promise.resolve(null),
    [sessionToken, activeStudentId],
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru-RU");
    return (conversations.data || []).filter((item) => {
      const searchable = [item.student_name, item.parent_name, item.parent_phone, item.group_name]
        .join(" ")
        .toLocaleLowerCase("ru-RU");
      return (!normalized || searchable.includes(normalized))
        && (!statusFilter || item.latest_status === statusFilter);
    });
  }, [conversations.data, query, statusFilter]);

  useEffect(() => {
    if (!detail.data?.messages?.length) return;
    messagesRef.current?.scrollTo({
      top: messagesRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [detail.data?.messages]);

  async function handleSendAll() {
    setSendingAll(true);
    setSendAllError("");
    try {
      const result = await api("/api/reports/send-all/", { method: "POST" });
      setSendAllResult(result);
      setConfirmSendAll(false);
      conversations.reload();
      if (activeStudentId) detail.reload();
    } catch (error) {
      setSendAllError(error.message || "Не удалось отправить отчёты. Попробуйте ещё раз.");
    } finally {
      setSendingAll(false);
    }
  }

  if (user.role !== "ADMIN") {
    return <EmptyState title="Нет доступа" description="Чат отчётов доступен только администратору." />;
  }
  if (conversations.loading) return <LoadingBlock label="Загружаем диалоги отчётов..." />;
  if (conversations.error) {
    return <ErrorBlock message={conversations.error} action={<Button onClick={conversations.reload}>Повторить</Button>} />;
  }

  return (
    <section className="report-chat-page" aria-labelledby="report-chat-title">
      <header className="report-chat-page__header">
        <div>
          <p>Мониторинг WhatsApp</p>
          <h2 id="report-chat-title">Чат отчётов</h2>
          <span>Результаты отправок родителям через Dify и Meta</span>
        </div>
        <div className="report-chat-page__actions">
          <Button variant="danger" onClick={() => { setSendAllError(""); setConfirmSendAll(true); }}>
            Отправить отчёт всем
          </Button>
          <Button variant="secondary" onClick={conversations.reload} disabled={conversations.refreshing}>
            {conversations.refreshing ? "Обновляем…" : "Обновить"}
          </Button>
        </div>
      </header>

      {sendAllResult ? (
        <div className="report-chat__bulk-result" role="status">
          Отправка завершена: отправлено — <strong>{sendAllResult.sent}</strong>, ошибок — <strong>{sendAllResult.failed}</strong>, всего — <strong>{sendAllResult.total}</strong>.
          <button type="button" onClick={() => setSendAllResult(null)}>Закрыть</button>
        </div>
      ) : null}

      <div className="report-chat">
        <aside className="report-chat__sidebar" aria-label="Диалоги отчётов">
          <div className="report-chat__filters">
            <label>
              <span>Поиск</span>
              <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Студент, группа или телефон" />
            </label>
            <label>
              <span>Статус</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">Все</option>
                <option value="pending">В очереди</option>
                <option value="succeeded">Отправлено</option>
                <option value="failed">Ошибка</option>
              </select>
            </label>
          </div>

          <div className="report-chat__conversation-list">
            {filtered.map((item) => (
              <button
                key={item.student_id}
                type="button"
                className={`report-chat__conversation ${activeStudentId === item.student_id ? "report-chat__conversation--active" : ""}`.trim()}
                onClick={() => setSelectedStudentId(item.student_id)}
                aria-pressed={activeStudentId === item.student_id}
              >
                <span className="report-chat__avatar" aria-hidden="true">{item.student_name.slice(0, 1).toLocaleUpperCase("ru-RU")}</span>
                <span className="report-chat__conversation-copy">
                  <strong>{item.student_name}</strong>
                  <small>{item.group_name} · {item.parent_phone}</small>
                  <span>{formatMonthLabel(item.latest_month)} · {item.messages_count} сообщ.</span>
                </span>
                <StatusBadge value={item.latest_status} />
              </button>
            ))}
            {!filtered.length ? <EmptyState title="Ничего не найдено" description="Измените поиск или фильтр." /> : null}
          </div>
        </aside>

        <div className="report-chat__thread" aria-live="polite">
          {detail.loading ? <LoadingBlock label="Загружаем историю..." /> : null}
          {detail.error ? <ErrorBlock message={detail.error} action={<Button onClick={detail.reload}>Повторить</Button>} /> : null}
          {detail.data ? (
            <>
              <header className="report-chat__thread-head">
                <div><strong>{detail.data.student.full_name}</strong><span>{detail.data.student.group_name}</span></div>
                <div><span>{detail.data.student.parent_name}</span><strong>{detail.data.student.parent_phone}</strong></div>
              </header>
              <div className="report-chat__messages" ref={messagesRef}>
                {detail.data.messages.map((message) => <ReportMessage key={message.id} message={message} />)}
              </div>
            </>
          ) : null}
          {!activeStudentId ? <EmptyState title="Выберите диалог" description="Здесь появится история отправок." /> : null}
        </div>
      </div>

      <Modal
        open={confirmSendAll}
        title="Отправить отчёт всем студентам?"
        description="Это принудительная массовая отправка за текущий месяц."
        onClose={() => { if (!sendingAll) setConfirmSendAll(false); }}
        footer={(
          <>
            <Button variant="ghost" onClick={() => setConfirmSendAll(false)} disabled={sendingAll}>Отмена</Button>
            <Button variant="danger" onClick={handleSendAll} disabled={sendingAll}>
              {sendingAll ? "Отправляем…" : "Да, отправить всем"}
            </Button>
          </>
        )}
      >
        <div className="report-chat__bulk-warning">
          <strong>Вы точно хотите продолжить?</strong>
          <p>Отчёт уйдёт родителям всех активных студентов, даже если сегодня не последний урок, оценка ещё не выставлена или отчёт за этот месяц уже отправлялся.</p>
          <p>Повторное нажатие может повторно отправить сообщение каждому родителю.</p>
          {sendAllError ? <p className="report-chat__bulk-error" role="alert">{sendAllError}</p> : null}
        </div>
      </Modal>
    </section>
  );
}
