export function parseHashLocation() {
  const rawHash = window.location.hash.replace(/^#/, "") || "/dashboard";
  const [rawPath, rawSearch = ""] = rawHash.split("?");
  const path = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  const query = Object.fromEntries(new URLSearchParams(rawSearch));
  return {
    path,
    query,
  };
}

export function navigateTo(path, query = {}) {
  const params = new URLSearchParams();

  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, value);
    }
  });

  const nextHash = params.toString() ? `${path}?${params.toString()}` : path;
  if (window.location.hash === `#${nextHash}`) {
    return;
  }

  window.location.hash = nextHash;
}

export function matchPath(pattern, path) {
  const patternSegments = pattern.split("/").filter(Boolean);
  const pathSegments = path.split("/").filter(Boolean);

  if (patternSegments.length !== pathSegments.length) {
    return null;
  }

  const params = {};

  for (let index = 0; index < patternSegments.length; index += 1) {
    const patternSegment = patternSegments[index];
    const pathSegment = pathSegments[index];

    if (patternSegment.startsWith(":")) {
      params[patternSegment.slice(1)] = pathSegment;
      continue;
    }

    if (patternSegment !== pathSegment) {
      return null;
    }
  }

  return params;
}
