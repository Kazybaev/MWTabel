import { useEffect, useEffectEvent, useState, startTransition } from "react";

import "./App.css";
import { AppShell } from "./components/AppShell";
import { EmptyState, LoadingBlock } from "./components/Ui";
import { apiRequest, clearStoredSession, getErrorMessage, readStoredSession, writeStoredSession } from "./lib/api";
import { sortGroupsByName } from "./lib/groupSort";
import { matchPath, navigateTo, parseHashLocation } from "./lib/router";
import { DashboardPage } from "./pages/DashboardPage";
import { ArchivedStudentsPage } from "./pages/ArchivedStudentsPage";
import { GradebookPage } from "./pages/GradebookPage";
import { CollegeGradebookPage } from "./pages/CollegeGradebookPage";
import { GroupDetailPage } from "./pages/GroupDetailPage";
import { GroupsPage } from "./pages/GroupsPage";
import { LoginPage } from "./pages/LoginPage";
import { MentorsPage } from "./pages/MentorsPage";
import { ReportConversationsPage } from "./pages/ReportConversationsPage";
import { StudentsPage } from "./pages/StudentsPage";

const emptyMeta = {
  study_day_choices: [],
  grade_choices: [],
};

function defaultPathForUser(user) {
  if (user?.role === "MENTOR") {
    return "/groups";
  }

  if (user?.role === "STUDENT") {
    return "/my-grades";
  }

  return "/dashboard";
}

function NotFoundPage() {
  return (
    <EmptyState
      title="Страница не найдена"
      description="Проверьте адрес в навигации или вернитесь на дашборд."
      action={
        <a className="button button--primary" href="#/dashboard">
          На дашборд
        </a>
      }
    />
  );
}

function buildNotice(message, tone = "info") {
  return { message, tone };
}

function App() {
  const [session, setSession] = useState(() => readStoredSession());
  const [organization, setOrganization] = useState(() => window.localStorage.getItem("tabel.organization") || "academy");
  const [route, setRoute] = useState(() => parseHashLocation());
  const [meta, setMeta] = useState(emptyMeta);
  const [mentorGroups, setMentorGroups] = useState([]);
  const [notice, setNotice] = useState(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [pendingSession, setPendingSession] = useState(null);
  const [bootstrapping, setBootstrapping] = useState(Boolean(readStoredSession()?.access));

  function updateSession(nextSession) {
    if (!nextSession) {
      clearStoredSession();
      setSession(null);
      return;
    }

    writeStoredSession(nextSession);
    setSession(nextSession);
  }

  const handleUnauthorized = useEffectEvent(() => {
    clearStoredSession();
    setSession(null);
    setMeta(emptyMeta);
    setNotice(buildNotice("Сессия завершилась. Войдите снова.", "danger"));
    startTransition(() => navigateTo("/login"));
  });

  async function callApi(path, options = {}) {
    return apiRequest(path, {
      ...options,
      session,
      organization,
      onSessionChange: updateSession,
      onUnauthorized: handleUnauthorized,
    });
  }

  function changeOrganization(value) {
    window.localStorage.setItem("tabel.organization", value);
    setOrganization(value);
    window.location.reload();
  }

  const syncUserProfile = useEffectEvent(async () => {
    if (!session?.access) {
      setBootstrapping(false);
      return;
    }

    try {
      const user = await apiRequest("/api/me/", {
        session,
        onSessionChange: updateSession,
        onUnauthorized: handleUnauthorized,
      });
      updateSession({ ...session, user });
    } catch {
      // handled by apiRequest
    } finally {
      setBootstrapping(false);
    }
  });

  const loadMeta = useEffectEvent(async () => {
    if (!session?.access) {
      setMeta(emptyMeta);
      return;
    }

    try {
      const payload = await apiRequest("/api/meta/", {
        session,
        onSessionChange: updateSession,
        onUnauthorized: handleUnauthorized,
      });
      setMeta(payload);
    } catch (error) {
      setNotice(buildNotice(getErrorMessage(error.payload, error.message), "danger"));
    }
  });

  const loadMentorGroups = useEffectEvent(async () => {
    if (!session?.access || session?.user?.role !== "MENTOR") {
      setMentorGroups([]);
      return;
    }

    try {
      const payload = await apiRequest("/api/groups/", {
        session,
        onSessionChange: updateSession,
        onUnauthorized: handleUnauthorized,
      });
      setMentorGroups(sortGroupsByName(payload));
    } catch {
      setMentorGroups([]);
    }
  });

  const handleHashChange = useEffectEvent(() => {
    startTransition(() => {
      setRoute((currentRoute) => {
        const nextRoute = parseHashLocation();
        const currentQuery = JSON.stringify(currentRoute.query || {});
        const nextQuery = JSON.stringify(nextRoute.query || {});

        if (currentRoute.path === nextRoute.path && currentQuery === nextQuery) {
          return currentRoute;
        }

        return nextRoute;
      });
    });
  });

  useEffect(() => {
    if (!window.location.hash) {
      navigateTo(session?.access ? defaultPathForUser(session.user) : "/login");
    }

    window.addEventListener("hashchange", handleHashChange);
    return () => {
      window.removeEventListener("hashchange", handleHashChange);
    };
  }, []);

  useEffect(() => {
    syncUserProfile();
  }, [session?.access]);

  useEffect(() => {
    loadMeta();
  }, [session?.access]);

  useEffect(() => {
    loadMentorGroups();
  }, [session?.access, session?.user?.role]);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setNotice(null);
    }, 5000);

    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    if (!session?.access || !session?.user) {
      return;
    }

    if (route.path === "/login") {
      navigateTo(defaultPathForUser(session.user));
    }
  }, [route.path, session?.access, session?.user]);

  async function handleLogin(credentials) {
    setAuthLoading(true);
    setAuthError("");

    try {
      const nextSession = await apiRequest("/api/auth/login/", {
        method: "POST",
        body: credentials,
      });
      const user = await apiRequest("/api/me/", {
        session: nextSession,
      });
      const finalSession = { ...nextSession, user };
      if ((user.organizations || []).length > 1) {
        setPendingSession(finalSession);
        return;
      }
      const onlyOrganization = user.organizations?.[0] || "academy";
      window.localStorage.setItem("tabel.organization", onlyOrganization);
      setOrganization(onlyOrganization);
      updateSession(finalSession);
      setNotice(buildNotice("Вы вошли в систему.", "success"));
      startTransition(() => navigateTo(defaultPathForUser(user)));
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthLoading(false);
    }
  }

  function handlePortalSelect(value) {
    if (!pendingSession?.user?.organizations?.includes(value)) return;
    window.localStorage.setItem("tabel.organization", value);
    setOrganization(value);
    updateSession(pendingSession);
    setPendingSession(null);
    startTransition(() => navigateTo(defaultPathForUser(pendingSession.user)));
  }

  async function handleLogout() {
    try {
      if (session?.refresh) {
        await callApi("/api/auth/logout/", {
          method: "POST",
          body: { refresh: session.refresh },
        });
      }
    } catch {
      // logout is best-effort
    } finally {
      clearStoredSession();
      setSession(null);
      setMeta(emptyMeta);
      setNotice(buildNotice("Вы вышли из системы.", "info"));
      startTransition(() => navigateTo("/login"));
    }
  }

  function renderAuthenticatedPage() {
    const gradebookRoute = matchPath("/groups/:id/gradebook", route.path);
    const groupRoute = matchPath("/groups/:id", route.path);

    if (route.path === "/dashboard") {
      if (session.user.role === "MENTOR") {
        return (
          <GroupsPage
            api={callApi}
            meta={meta}
            sessionToken={session.access}
            user={session.user}
            onNotice={setNotice}
          />
        );
      }

      return <DashboardPage api={callApi} sessionToken={session.access} user={session.user} />;
    }

    if (route.path === "/groups") {
      return (
        <GroupsPage
          api={callApi}
          meta={meta}
          sessionToken={session.access}
          user={session.user}
          onNotice={setNotice}
        />
      );
    }

    if (route.path === "/students") {
      return <StudentsPage api={callApi} sessionToken={session.access} user={session.user} onNotice={setNotice} organization={organization} />;
    }

    if (route.path === "/archive") {
      return <ArchivedStudentsPage api={callApi} sessionToken={session.access} user={session.user} onNotice={setNotice} />;
    }

    if (route.path === "/mentors") {
      return <MentorsPage api={callApi} sessionToken={session.access} user={session.user} onNotice={setNotice} />;
    }

    if (route.path === "/reports") {
      return <ReportConversationsPage api={callApi} sessionToken={session.access} user={session.user} />;
    }

    if (route.path === "/my-grades") {
      if (organization === "college") {
        return <CollegeGradebookPage api={callApi} sessionToken={session.access} routeMonth={route.query.month} />;
      }
      return (
        <GradebookPage
          api={callApi}
          sessionToken={session.access}
          user={session.user}
          routeMonth={route.query.month}
          onNotice={setNotice}
          mode="student"
        />
      );
    }

    if (gradebookRoute) {
      return (
        <GradebookPage
          api={callApi}
          sessionToken={session.access}
          user={session.user}
          groupId={Number(gradebookRoute.id)}
          routeMonth={route.query.month}
          onNotice={setNotice}
        />
      );
    }

    if (groupRoute) {
      if (session.user.role === "MENTOR") {
        return (
          <GradebookPage
            api={callApi}
            sessionToken={session.access}
            user={session.user}
            groupId={Number(groupRoute.id)}
            routeMonth={route.query.month}
            onNotice={setNotice}
          />
        );
      }

      return (
        <GroupDetailPage
          api={callApi}
          sessionToken={session.access}
          user={session.user}
          groupId={Number(groupRoute.id)}
          onNotice={setNotice}
        />
      );
    }

    return <NotFoundPage />;
  }

  if (!session?.access) {
    return <LoginPage onLogin={handleLogin} loading={authLoading} error={authError} portals={pendingSession?.user?.organizations} onPortalSelect={handlePortalSelect} />;
  }

  if (bootstrapping || !session.user) {
    return <LoadingBlock label="Подготавливаем рабочее пространство..." />;
  }

  const gradebookRoute = matchPath("/groups/:id/gradebook", route.path);
  const groupRoute = matchPath("/groups/:id", route.path);
  const adminDashboardLocked = route.path === "/dashboard" && session.user.role === "ADMIN";
  const lockedContent =
    adminDashboardLocked ||
    route.path === "/reports" ||
    route.path === "/my-grades" ||
    Boolean(gradebookRoute) ||
    (session.user.role === "MENTOR" && Boolean(groupRoute));

  return (
    <AppShell
      user={session.user}
      currentPath={route.path}
      notice={notice}
      onDismissNotice={() => setNotice(null)}
      onLogout={handleLogout}
      mentorGroups={mentorGroups}
      lockedContent={lockedContent}
      organization={organization}
      onOrganizationChange={changeOrganization}
    >
      {renderAuthenticatedPage()}
    </AppShell>
  );
}

export default App;
