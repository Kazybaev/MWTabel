import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";

import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, Modal } from "../components/Ui";
import { formatMonthLabel, toMonthValue } from "../lib/format";
import { getBulkDispatchPresentation, shouldPollReportBatch } from "../lib/reportDispatchResult";
import { useResource } from "../lib/useResource";
import "./ReportConversationsPage.css";

const STATUS = {
  pending: { label: "В очереди", tone: "blue" },
  accepted: { label: "Принято Meta", tone: "teal" },
  delivered: { label: "Доставлено", tone: "teal" },
  succeeded: { label: "Завершено (legacy, доставка не подтверждена)", tone: "neutral" },
  failed: { label: "Ошибка", tone: "sand" },
  not_sent: { label: "Не отправлялся", tone: "neutral" },
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

export function ReportConversationsPage({ api, sessionToken, user, organization = "academy" }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedStudentId, setSelectedStudentId] = useState(null);
  const [confirmSendAll, setConfirmSendAll] = useState(false);
  const [sendMode, setSendMode] = useState("all");
  const [sendMonth, setSendMonth] = useState(toMonthValue());
  const [selectedGroupIds, setSelectedGroupIds] = useState([]);
  const [selectedStudentIds, setSelectedStudentIds] = useState([]);
  const [sendingAll, setSendingAll] = useState(false);
  const [confirmRetryFailed, setConfirmRetryFailed] = useState(false);
  const [sendAllResult, setSendAllResult] = useState(null);
  const [sendAllError, setSendAllError] = useState("");
  const messagesRef = useRef(null);
  const conversations = useResource(() => api("/api/reports/conversations/"), [sessionToken]);
  const dispatchOptions = useResource(() => api("/api/reports/options/"), [sessionToken, organization]);
  const activeStudentId = selectedStudentId || conversations.data?.[0]?.student_id || null;
  const detail = useResource(
    () => activeStudentId ? api(`/api/reports/conversations/${activeStudentId}/`) : Promise.resolve(null),
    [sessionToken, activeStudentId],
  );
  const sendAllPresentation = sendAllResult ? getBulkDispatchPresentation(sendAllResult) : null;
  const batchStatusUrl = sendAllResult?.status_url;
  const batchPollingActive = shouldPollReportBatch(sendAllResult);

  const pollBatch = useEffectEvent(async (statusUrl) => {
    try {
      const next = await api(statusUrl);
      setSendAllResult(next);
      if (!next.remaining) {
        conversations.reload();
        if (activeStudentId) detail.reload();
      }
    } catch (error) {
      setSendAllError(error.message || "Не удалось обновить состояние пакета.");
    }
  });

  useEffect(() => {
    if (!batchPollingActive) return undefined;
    let stopped = false;
    let timer;
    const pollUntilTerminal = async () => {
      await pollBatch(batchStatusUrl);
      if (!stopped) timer = window.setTimeout(pollUntilTerminal, 2000);
    };
    timer = window.setTimeout(pollUntilTerminal, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [batchPollingActive, batchStatusUrl]);

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
      const body = { month: sendMonth };
      body.confirm_retry_failed = confirmRetryFailed;
      if (sendMode === "groups") body.group_ids = selectedGroupIds;
      if (sendMode === "students") body.student_ids = selectedStudentIds;
      const result = await api("/api/reports/send-all/", { method: "POST", body });
      setSendAllResult(result);
      setConfirmSendAll(false);
      conversations.reload();
      if (activeStudentId) detail.reload();
    } catch (error) {
      if (error.payload && typeof error.payload === "object" && "total" in error.payload) {
        setSendAllResult(error.payload);
        setConfirmSendAll(false);
        conversations.reload();
        if (activeStudentId) detail.reload();
      } else {
        setSendAllError(error.message || "Не удалось отправить отчёты. Попробуйте ещё раз.");
      }
    } finally {
      setSendingAll(false);
    }
  }

  function openDispatchCard() {
    setSendMode(organization === "college" ? "all" : "all");
    setSendMonth(toMonthValue());
    setSelectedGroupIds([]);
    setSelectedStudentIds([]);
    setConfirmRetryFailed(false);
    setSendAllError("");
    setConfirmSendAll(true);
  }

  function toggleSelection(setter, id) {
    setter((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
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
          <Button variant="danger" onClick={openDispatchCard}>
            Отправить отчёт всем
          </Button>
          <Button variant="secondary" onClick={conversations.reload} disabled={conversations.refreshing}>
            {conversations.refreshing ? "Обновляем…" : "Обновить"}
          </Button>
        </div>
      </header>

      {sendAllPresentation ? (
        <div className={`report-chat__bulk-result report-chat__bulk-result--${sendAllPresentation.tone}`} role={sendAllPresentation.role}>
          <strong>{sendAllPresentation.title}.</strong>
          {sendAllPresentation.isBatch ? (
            <span>
              В очереди — <strong>{sendAllPresentation.queued}</strong>, обрабатывается — <strong>{sendAllPresentation.processing}</strong>,
              принято Meta — <strong>{sendAllPresentation.accepted}</strong>, доставлено — <strong>{sendAllPresentation.delivered}</strong>,
              ошибок — <strong>{sendAllPresentation.failed}</strong>, пропущено — <strong>{sendAllPresentation.skipped}</strong>,
              отменено — <strong>{sendAllPresentation.cancelled}</strong>,
              осталось — <strong>{sendAllPresentation.remaining}</strong>, всего — <strong>{sendAllPresentation.total}</strong>.
            </span>
          ) : (
            <span>
              Успешно — <strong>{sendAllPresentation.succeeded}</strong>, ошибок — <strong>{sendAllPresentation.failed}</strong>,
              пропущено — <strong>{sendAllPresentation.skipped}</strong>, всего — <strong>{sendAllPresentation.total}</strong>.
            </span>
          )}
          {sendAllPresentation.firstError ? <span>Первая причина: {sendAllPresentation.firstError}</span> : null}
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
                <option value="succeeded">Завершено (legacy)</option>
                <option value="accepted">Принято Meta</option>
                <option value="delivered">Доставлено</option>
                <option value="failed">Ошибка</option>
              </select>
            </label>
          </div>

          <div className="report-chat__conversation-list">
            {filtered.map((item) => (
              <div className="report-chat__conversation-row" key={item.student_id}>
                <button
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
              </div>
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
        title="Отправить отчёты"
        description={organization === "college" ? "Выберите месяц для отправки отчётов студентам колледжа." : "Выберите получателей и месяц отчёта."}
        onClose={() => { if (!sendingAll) setConfirmSendAll(false); }}
        footer={(
          <>
            <Button variant="ghost" onClick={() => setConfirmSendAll(false)} disabled={sendingAll}>Отмена</Button>
            <Button variant="danger" onClick={handleSendAll} disabled={sendingAll || (sendMode === "groups" && !selectedGroupIds.length) || (sendMode === "students" && !selectedStudentIds.length)}>
              {sendingAll ? "Отправляем…" : "Отправить отчёты"}
            </Button>
          </>
        )}
      >
        <div className="report-chat__bulk-warning report-chat__dispatch-card">
          {organization !== "college" ? (
            <div className="report-chat__dispatch-modes" role="group" aria-label="Кому отправить отчёт">
              <button type="button" className={sendMode === "all" ? "is-active" : ""} onClick={() => setSendMode("all")}>Отправить всем</button>
              <button type="button" className={sendMode === "groups" ? "is-active" : ""} onClick={() => setSendMode("groups")}>Выбрать группы</button>
              <button type="button" className={sendMode === "students" ? "is-active" : ""} onClick={() => setSendMode("students")}>Выбрать студентов</button>
            </div>
          ) : null}
          <label className="report-chat__month-field"><span>Месяц отчёта</span><input type="month" value={sendMonth} onChange={(event) => setSendMonth(event.target.value)} /></label>
          {sendMode === "groups" ? (
            <div className="report-chat__dispatch-list" aria-label="Группы">
              {!dispatchOptions.data?.groups?.length ? <p>Нет доступных групп.</p> : dispatchOptions.data.groups.map((group) => <label key={group.id}><input type="checkbox" checked={selectedGroupIds.includes(group.id)} onChange={() => toggleSelection(setSelectedGroupIds, group.id)} /><span>{group.name}</span></label>)}
            </div>
          ) : null}
          {sendMode === "students" ? (
            <div className="report-chat__dispatch-list" aria-label="Студенты">
              {!dispatchOptions.data?.students?.length ? <p>Нет доступных студентов.</p> : dispatchOptions.data.students.map((student) => <label key={student.id}><input type="checkbox" checked={selectedStudentIds.includes(student.id)} onChange={() => toggleSelection(setSelectedStudentIds, student.id)} /><span>{student.name}<small>{student.group_name}</small></span></label>)}
            </div>
          ) : null}
          <p>Отчёты будут отправлены родителям выбранных активных студентов. Уже успешно отправленные отчёты будут пропущены.</p>
          <label className="report-chat__retry-confirm">
            <input type="checkbox" checked={confirmRetryFailed} onChange={(event) => setConfirmRetryFailed(event.target.checked)} />
            <span>Я явно подтверждаю повторную отправку ранее неуспешных (`failed`) попыток.</span>
          </label>
          {sendAllError ? <p className="report-chat__bulk-error" role="alert">{sendAllError}</p> : null}
        </div>
      </Modal>
    </section>
  );
}
