const SESSION_STORAGE_KEY = "tabel.react.session";

export function readStoredSession() {
  try {
    const rawValue = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }

    const parsedValue = JSON.parse(rawValue);
    return parsedValue?.access ? parsedValue : null;
  } catch {
    return null;
  }
}

export function writeStoredSession(session) {
  if (!session) {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    return;
  }

  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession() {
  window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

async function parseResponse(response) {
  if (response.status === 204 || response.status === 205) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

async function refreshAccessToken(refresh) {
  const response = await fetch("/api/auth/refresh/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ refresh }),
  });
  const payload = await parseResponse(response);

  if (!response.ok) {
    const error = new Error(getErrorMessage(payload, "Не удалось обновить сессию."));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export function getErrorMessage(payload, fallback = "Что-то пошло не так.") {
  if (!payload) {
    return fallback;
  }

  if (typeof payload === "string") {
    return payload || fallback;
  }

  if (Array.isArray(payload)) {
    return getErrorMessage(payload[0], fallback);
  }

  if (typeof payload === "object") {
    if (payload.detail) {
      return getErrorMessage(payload.detail, fallback);
    }

    const firstValue = Object.values(payload)[0];
    return getErrorMessage(firstValue, fallback);
  }

  return fallback;
}

export async function apiRequest(
  path,
  { method = "GET", body, headers = {}, session, onSessionChange, onUnauthorized } = {},
) {
  const requestHeaders = {
    Accept: "application/json",
    ...headers,
  };

  if (body !== undefined) {
    requestHeaders["Content-Type"] = "application/json";
  }

  if (session?.access) {
    requestHeaders.Authorization = `Bearer ${session.access}`;
  }

  const requestInit = {
    method,
    headers: requestHeaders,
  };

  if (body !== undefined) {
    requestInit.body = JSON.stringify(body);
  }

  let response = await fetch(path, requestInit);

  if (
    response.status === 401 &&
    session?.refresh &&
    path !== "/api/auth/refresh/" &&
    path !== "/api/auth/login/"
  ) {
    try {
      const refreshed = await refreshAccessToken(session.refresh);
      const nextSession = { ...session, access: refreshed.access };
      writeStoredSession(nextSession);
      onSessionChange?.(nextSession);
      requestInit.headers.Authorization = `Bearer ${nextSession.access}`;
      response = await fetch(path, requestInit);
    } catch (error) {
      clearStoredSession();
      onUnauthorized?.();
      throw error;
    }
  }

  const payload = await parseResponse(response);

  if (!response.ok) {
    if (response.status === 401) {
      clearStoredSession();
      onUnauthorized?.();
    }

    const error = new Error(getErrorMessage(payload));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}
