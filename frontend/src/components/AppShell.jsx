import { useEffect, useState } from "react";

import { Badge, Button, NoticeBanner } from "./Ui";
import { formatRole } from "../lib/format";

function buildNavigation(role) {
  const items = [{ label: "Дашборд", href: "/dashboard" }];

  if (role === "ADMIN") {
    items.push({ label: "Группы", href: "/groups" });
    items.push({ label: "Студенты", href: "/students" });
    items.push({ label: "Менторы", href: "/mentors" });
  }

  if (role === "STUDENT") {
    items.push({ label: "Мои оценки", href: "/my-grades" });
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
        description: "Вы можете ставить оценки по дням, заполнять месяц и сразу видеть всю группу в одной матрице.",
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

  if (currentPath === "/mentors") {
    return {
      eyebrow: "Админ",
      title: "Менторы",
      description: "Назначайте менторов, следите за их группами и держите систему в порядке.",
    };
  }

  return {
    eyebrow: "Админ",
    title: "Панель управления",
    description: "Контролируйте платформу, роли пользователей, группы и общий учебный процесс в одном месте.",
  };
}

function SidebarIntro({ eyebrow, title, description, compact = false }) {
  return (
    <div className={`sidebar__brand ${compact ? "sidebar__brand--mentor" : ""}`.trim()}>
      <p className="sidebar__eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}

function MentorSidebar({ currentPath, mentorGroups, user }) {
  const currentGroupId = extractCurrentGroupId(currentPath);
  const intro = buildSidebarIntro("MENTOR", currentPath);

  return (
    <>
      <SidebarIntro eyebrow={intro.eyebrow} title={intro.title} description={intro.description} compact />

      <div className="mentor-sidebar__section">
        <a className="mentor-sidebar__back" href="#/groups" title="Вернуться к списку групп">
          <span className="mentor-sidebar__back-icon">←</span>
          <span>Список групп</span>
        </a>
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

      <div className="sidebar__profile mentor-sidebar__profile">
        <Badge tone="teal">{formatRole(user.role)}</Badge>
        <strong>{user.full_name}</strong>
        <span>{user.username}</span>
      </div>
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
}) {
  const isMentor = user.role === "MENTOR";
  const navigation = buildNavigation(user.role);
  const intro = buildSidebarIntro(user.role, currentPath);
  const topbarTitle = isMentor ? "Ментор" : formatRole(user.role);
  const topbarEyebrow = isMentor ? "Табель групп" : "Платформа";
  const shellClassName = ["app-shell", lockedContent ? "app-shell--locked" : "", isMentor ? "app-shell--mentor" : ""]
    .filter(Boolean)
    .join(" ");
  const sidebarClassName = ["sidebar", isMentor ? "sidebar--mentor" : ""].filter(Boolean).join(" ");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [currentPath]);

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
            ×
          </button>
        </div>

        {isMentor ? (
          <MentorSidebar currentPath={currentPath} mentorGroups={mentorGroups} user={user} />
        ) : (
          <>
            <SidebarIntro eyebrow={intro.eyebrow} title={intro.title} description={intro.description} />

            <nav className="sidebar__nav">
              {navigation.map((item) => (
                <a
                  key={item.href}
                  className={`sidebar__link ${isActiveLink(currentPath, item.href) ? "sidebar__link--active" : ""}`}
                  href={`#${item.href}`}
                >
                  {item.label}
                </a>
              ))}
            </nav>

            <div className="sidebar__profile">
              <Badge tone="teal">{formatRole(user.role)}</Badge>
              <strong>{user.full_name}</strong>
              <span>{user.username}</span>
            </div>
          </>
        )}
      </aside>

      <div
        className={`workspace ${isMentor ? "workspace--mentor" : ""} ${lockedContent ? "workspace--locked" : ""}`.trim()}
      >
        <div className="workspace__stage">
          <div className="workspace__stage-inner">
            <header className="topbar">
              <div className="topbar__heading">
                <button type="button" className="topbar__menu-button" onClick={() => setMobileMenuOpen(true)}>
                  ☰
                </button>
                <p className="topbar__eyebrow">{topbarEyebrow}</p>
                <h2>{topbarTitle}</h2>
              </div>
              <div className="topbar__actions">
                <span className="topbar__user">{user.full_name}</span>
                <Button variant="ghost" onClick={onLogout}>
                  Выйти
                </Button>
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
