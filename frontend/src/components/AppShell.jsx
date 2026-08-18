import { useState } from "react";

import { NoticeBanner } from "./Ui";
import { formatRole } from "../lib/format";

const navigationIcons = {
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  groups: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
  students: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /><path d="M17.5 4.5 19 6l3-3" /></>,
  archive: <><path d="M3 6h18" /><path d="M5 6v14h14V6" /><path d="M8 3h8l2 3H6l2-3Z" /><path d="M9 11h6" /></>,
  mentors: <><path d="m3 10 9-5 9 5-9 5-9-5Z" /><path d="M7 12.2V16c2.8 2.2 7.2 2.2 10 0v-3.8" /><path d="M21 10v6" /></>,
  reports: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z" /><path d="M8 9h8M8 13h5" /></>,
  grades: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /><path d="m9 10 2 2 4-4" /></>,
};

function NavigationIcon({ name }) {
  return (
    <svg className="sidebar__link-icon" viewBox="0 0 24 24" aria-hidden="true">
      {navigationIcons[name]}
    </svg>
  );
}

function buildNavigation(role) {
  const items = [{ label: "Дашборд", href: "/dashboard", icon: "dashboard" }];

  if (role === "ADMIN") {
    items.push({ label: "Группы", href: "/groups", icon: "groups" });
    items.push({ label: "Студенты", href: "/students", icon: "students" });
    items.push({ label: "Архив", href: "/archive", icon: "archive" });
    items.push({ label: "Менторы", href: "/mentors", icon: "mentors" });
    items.push({ label: "Отчёты", href: "/reports", icon: "reports" });
  }

  if (role === "STUDENT") {
    items.push({ label: "Мои оценки", href: "/my-grades", icon: "grades" });
  }

  return items;
}

function isActiveLink(currentPath, href) {
  if (href === "/dashboard" || href === "/groups") {
    return currentPath === href;
  }

  return currentPath === href || currentPath.startsWith(`${href}/`);
}

function extractCurrentGroupId(currentPath) {
  const match = currentPath.match(/^\/groups\/(\d+)/);
  return match ? Number(match[1]) : null;
}

function buildSidebarIntro(role, currentPath) {
  if (role === "MENTOR") {
    if (/^\/groups\/\d+\/gradebook$/.test(currentPath)) {
      return {
        eyebrow: "Ментор",
        title: "Табель группы",
        description:
          "Вы можете ставить оценки по дням, заполнять месяц и сразу видеть всю группу в одной матрице.",
      };
    }

    return {
      eyebrow: "Ментор",
      title: "Мои группы",
      description: "Открывайте свои группы, переходите в табель и быстро заполняйте оценки по студентам.",
    };
  }

  if (role === "STUDENT") {
    if (currentPath === "/my-grades") {
      return {
        eyebrow: "Студент",
        title: "Мои оценки",
        description: "Здесь вы видите только свои оценки, посещаемость и месячный табель по группе.",
      };
    }

    return {
      eyebrow: "Студент",
      title: "Личный кабинет",
      description: "Следите за средним баллом, своей группой, ментором и общей успеваемостью.",
    };
  }

  if (currentPath === "/groups") {
    return {
      eyebrow: "Админ",
      title: "Группы",
      description: "Создавайте группы, открывайте состав и управляйте учебной структурой платформы.",
    };
  }

  if (currentPath === "/students") {
    return {
      eyebrow: "Админ",
      title: "Студенты",
      description: "Добавляйте студентов, редактируйте профили и распределяйте их по нужным группам.",
    };
  }

  if (currentPath === "/archive") {
    return {
      eyebrow: "Админ",
      title: "Архив",
      description: "Восстанавливайте студентов в группы или окончательно удаляйте ненужные учетные записи.",
    };
  }

  if (currentPath === "/mentors") {
    return {
      eyebrow: "Админ",
      title: "Менторы",
      description: "Назначайте менторов, следите за их группами и держите систему в порядке.",
    };
  }

  if (currentPath === "/reports") {
    return {
      eyebrow: "Админ",
      title: "Чат отчётов",
      description: "Контролируйте отправки родителям и ответы Meta без повторной отправки сообщений.",
    };
  }

  return {
    eyebrow: "Админ",
    title: "Панель управления",
    description: "Контролируйте платформу, роли пользователей, группы и общий учебный процесс в одном месте.",
  };
}

function SidebarIntro({ eyebrow, title, description, compact = false, children }) {
  return (
    <div className={`sidebar__brand ${compact ? "sidebar__brand--mentor" : ""}`.trim()}>
      <p className="sidebar__eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children || <p>{description}</p>}
    </div>
  );
}

function LogoutButton({ onLogout }) {
  return (
    <div className="sidebar__logout-zone">
      <button
        type="button"
        className="logout-control"
        onClick={onLogout}
        aria-label="Выйти из системы"
        title="Выйти из системы"
      >
        <span className="logout-control__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path className="logout-control__door" d="M14 4.5V3H5v18h9v-1.5" />
            <path className="logout-control__arrow" d="M10 12h11m-4-4 4 4-4 4" />
          </svg>
        </span>
        <span className="logout-control__label">Выйти</span>
      </button>
    </div>
  );
}

function MentorSidebar({ currentPath, mentorGroups, user, onLogout, organization, onOrganizationChange, onNavigate }) {
  const currentGroupId = extractCurrentGroupId(currentPath);

  return (
    <>
      <div className="mentor-sidebar__section">
        <a className="mentor-sidebar__back" href="#/groups" title="Вернуться к списку групп" onClick={onNavigate}>
          <svg className="mentor-sidebar__back-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
          <span>Список групп</span>
        </a>
        {user.organizations?.length > 1 ? (
          <div className="organization-switcher" role="group" aria-label="Выбор организации">
            <button
              type="button"
              className={organization === "academy" ? "organization-switcher__button organization-switcher__button--active" : "organization-switcher__button"}
              aria-pressed={organization === "academy"}
              onClick={() => onOrganizationChange?.("academy")}
            >
              Академия
            </button>
            <button
              type="button"
              className={organization === "college" ? "organization-switcher__button organization-switcher__button--active" : "organization-switcher__button"}
              aria-pressed={organization === "college"}
              onClick={() => onOrganizationChange?.("college")}
            >
              Колледж
            </button>
          </div>
        ) : null}
      </div>

      <div className="mentor-sidebar__section mentor-sidebar__section--grow">
        <p className="mentor-sidebar__label">Группы ментора</p>
        <div className="mentor-sidebar__group-list">
          {mentorGroups.length ? (
            mentorGroups.map((group) => {
              const active = currentGroupId === group.id;
              return (
                <a
                  key={group.id}
                  className={`mentor-sidebar__group-link ${active ? "mentor-sidebar__group-link--active" : ""}`.trim()}
                  href={`#/groups/${group.id}/gradebook`}
                  title={group.course_name}
                  onClick={onNavigate}
                >
                  <strong>{group.course_name}</strong>
                  <small>{group.study_days_label}</small>
                  <span className="mentor-sidebar__group-pill">{group.students_count} студентов</span>
                </a>
              );
            })
          ) : (
            <p className="mentor-sidebar__empty">Нет закреплённых групп</p>
          )}
        </div>
      </div>

      <LogoutButton onLogout={onLogout} />
    </>
  );
}

export function AppShell({
  user,
  currentPath,
  notice,
  onDismissNotice,
  onLogout,
  children,
  mentorGroups = [],
  lockedContent = false,
  organization = "academy",
  onOrganizationChange,
}) {
  const isMentor = user.role === "MENTOR";
  const isReportsPage = currentPath === "/reports";
  const navigation = buildNavigation(user.role);
  const intro = buildSidebarIntro(user.role, currentPath);
  const topbarTitle = isMentor ? "Ментор" : formatRole(user.role);
  const topbarEyebrow = isMentor ? "Табель групп" : "Платформа";
  const shellClassName = ["app-shell", lockedContent ? "app-shell--locked" : "", isMentor ? "app-shell--mentor" : ""]
    .filter(Boolean)
    .join(" ");
  const sidebarClassName = ["sidebar", isMentor ? "sidebar--mentor" : ""].filter(Boolean).join(" ");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div className={shellClassName}>
      <div
        className={`app-shell__backdrop ${mobileMenuOpen ? "app-shell__backdrop--visible" : ""}`.trim()}
        onClick={() => setMobileMenuOpen(false)}
      />

      <aside className={`${sidebarClassName} ${mobileMenuOpen ? "sidebar--mobile-open" : ""}`.trim()}>
        <div className="sidebar__mobile-head">
          <div className="sidebar__mobile-brand">
            <span>{formatRole(user.role)}</span>
            <strong>{user.full_name}</strong>
          </div>
          <button type="button" className="sidebar__mobile-close" onClick={() => setMobileMenuOpen(false)}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        {isMentor ? (
          <MentorSidebar
            currentPath={currentPath}
            mentorGroups={mentorGroups}
            user={user}
            onLogout={onLogout}
            organization={organization}
            onOrganizationChange={onOrganizationChange}
            onNavigate={() => setMobileMenuOpen(false)}
          />
        ) : (
          <>
            <SidebarIntro eyebrow={intro.eyebrow} title={intro.title} description={intro.description}>
              {user.role === "ADMIN" && user.organizations?.length > 1 ? (
                <div className="organization-switcher" role="group" aria-label="Выбор организации">
                  <button
                    type="button"
                    className={organization === "academy" ? "organization-switcher__button organization-switcher__button--active" : "organization-switcher__button"}
                    aria-pressed={organization === "academy"}
                    onClick={() => onOrganizationChange?.("academy")}
                  >
                    Академия
                  </button>
                  <button
                    type="button"
                    className={organization === "college" ? "organization-switcher__button organization-switcher__button--active" : "organization-switcher__button"}
                    aria-pressed={organization === "college"}
                    onClick={() => onOrganizationChange?.("college")}
                  >
                    Колледж
                  </button>
                </div>
              ) : null}
            </SidebarIntro>

            <nav className="sidebar__nav">
              {navigation.map((item) => (
                <a
                  key={item.href}
                  className={`sidebar__link ${isActiveLink(currentPath, item.href) ? "sidebar__link--active" : ""}`}
                  href={`#${item.href}`}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  <NavigationIcon name={item.icon} />
                  <span>{item.label}</span>
                </a>
              ))}
            </nav>

            <LogoutButton onLogout={onLogout} />
          </>
        )}
      </aside>

      <div
        className={`workspace ${isMentor ? "workspace--mentor" : ""} ${lockedContent ? "workspace--locked" : ""} ${isReportsPage ? "workspace--reports" : ""}`.trim()}
      >
        <div className="workspace__stage">
          <div className="workspace__stage-inner">
            <header className="topbar">
              <div className="topbar__heading">
                <button type="button" className="topbar__menu-button" onClick={() => setMobileMenuOpen(true)}>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
                </button>
                <p className="topbar__eyebrow">{topbarEyebrow}</p>
                <h2>{topbarTitle}</h2>
              </div>
              <div className="topbar__actions">
                <span className="topbar__user">{user.full_name}</span>
              </div>
            </header>

            <NoticeBanner notice={notice} onDismiss={onDismissNotice} />
            <main className="workspace__content">{children}</main>
          </div>
        </div>
      </div>
    </div>
  );
}
