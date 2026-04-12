import { useResource } from "../lib/useResource";
import { formatDate } from "../lib/format";
import { Badge, Button, EmptyState, ErrorBlock, LoadingBlock, MetricCard, Panel } from "../components/Ui";

function StudentOverviewPanel({ overview }) {
  return (
    <Panel eyebrow="Сводка" title="Моя учеба" description="Короткая информация по группе, ментору и текущим результатам.">
      <div className="list-stack">
        <div className="list-card">
          <div>
            <strong>Группа</strong>
            <p>{overview.group_name}</p>
          </div>
          <Badge tone="teal">Активная</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Ментор</strong>
            <p>{overview.mentor_name}</p>
          </div>
          <Badge tone="blue">Куратор</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Посещений</strong>
            <p>Отмеченные посещения в табеле</p>
          </div>
          <Badge tone="sand">{overview.attendance_count}</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Оценок</strong>
            <p>Все выставленные отметки</p>
          </div>
          <Badge tone="teal">{overview.grades_count}</Badge>
        </div>

        <div className="list-card">
          <div>
            <strong>Средний балл</strong>
            <p>Текущая средняя успеваемость</p>
          </div>
          <Badge tone="blue">{overview.average_grade}</Badge>
        </div>
      </div>
    </Panel>
  );
}

function DashboardListPanel({ eyebrow, title, description, children }) {
  return (
    <Panel eyebrow={eyebrow} title={title} description={description} className="dashboard-panel">
      <div className="dashboard-panel__scroll">{children}</div>
    </Panel>
  );
}

export function DashboardPage({ api, sessionToken, user }) {
  const { data, error, loading, reload } = useResource(() => api("/api/dashboard/"), [sessionToken]);

  if (loading) {
    return <LoadingBlock label="Загружаем дашборд..." />;
  }

  if (error) {
    return <ErrorBlock message={error} action={<Button onClick={reload}>Повторить</Button>} />;
  }

  const isStudentDashboard = Boolean(data.student_overview);
  const isAdminDashboard = user.role === "ADMIN" && !isStudentDashboard;

  return (
    <div className={`page-stack ${isAdminDashboard ? "dashboard-page dashboard-page--admin" : ""}`.trim()}>
      <section className="hero-band">
        <div>
          <p className="hero-band__eyebrow">РАБОЧАЯ ЗОНА</p>
          <h2>{data.dashboard_title}</h2>
          <p>{data.dashboard_copy}</p>
        </div>
        <div className="hero-band__meta">
          <strong>{user.full_name}</strong>
          <span>{user.username}</span>
        </div>
      </section>

      <div className="metric-grid">
        {data.summary_cards.map((card) => (
          <MetricCard key={card.label} label={card.label} value={card.value} tone={card.tone} />
        ))}
      </div>

      {isStudentDashboard ? (
        <StudentOverviewPanel overview={data.student_overview} />
      ) : (
        <div className={`split-grid ${isAdminDashboard ? "dashboard-panels" : ""}`.trim()}>
          {data.groups ? (
            <DashboardListPanel
              eyebrow="Группы"
              title="Активные потоки"
              description="Быстрый переход к группе и месячному табелю."
            >
              {data.groups.length ? (
                <div className="list-stack dashboard-list">
                  {data.groups.map((group) => (
                    <a key={group.id} className="list-card" href={`#/groups/${group.id}`}>
                      <div>
                        <strong>{group.course_name}</strong>
                        <p>{group.mentor_name}</p>
                      </div>
                      <Badge tone="sand">{group.students_count} студентов</Badge>
                    </a>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет групп" description="Добавьте первую группу, чтобы запустить табель." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.mentors ? (
            <DashboardListPanel eyebrow="Команда" title="Менторы" description="Кто сейчас ведет группы.">
              {data.mentors.length ? (
                <div className="list-stack dashboard-list">
                  {data.mentors.map((mentor) => (
                    <div key={mentor.id} className="list-card">
                      <div>
                        <strong>{mentor.full_name}</strong>
                        <p>{mentor.username}</p>
                      </div>
                      <Badge tone="teal">{mentor.groups_count} групп</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Нет менторов" description="После добавления они появятся здесь." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.students ? (
            <DashboardListPanel
              eyebrow="Студенты"
              title="Последние записи"
              description="Список участников, доступных по вашей роли."
            >
              {data.students.length ? (
                <div className="list-stack dashboard-list">
                  {data.students.map((student) => (
                    <div key={student.id} className="list-card">
                      <div>
                        <strong>{student.full_name}</strong>
                        <p>{student.group_name}</p>
                      </div>
                      <Badge tone="blue">{student.parent_name}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет студентов" description="Когда студенты появятся в системе, они будут здесь." />
              )}
            </DashboardListPanel>
          ) : null}

          {data.recent_lessons ? (
            <DashboardListPanel
              eyebrow="Занятия"
              title="Последние уроки"
              description="Свежие записи по журналу занятий."
            >
              {data.recent_lessons.length ? (
                <div className="list-stack dashboard-list">
                  {data.recent_lessons.map((lesson) => (
                    <div key={lesson.id} className="list-card">
                      <div>
                        <strong>{lesson.topic || "Без темы"}</strong>
                        <p>{lesson.group_name}</p>
                      </div>
                      <Badge tone="neutral">{formatDate(lesson.lesson_date)}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Пока нет уроков" description="Созданные уроки сразу появятся на дашборде." />
              )}
            </DashboardListPanel>
          ) : null}
        </div>
      )}
    </div>
  );
}
