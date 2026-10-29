// Minimal API client. All requests go to the same origin (/api is proxied to
// the backend). State-changing requests carry the CSRF token from the session.
let csrf: string | null = null;
let sessionPromise: Promise<string> | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function ensureSession(): Promise<string> {
  if (csrf) return csrf;
  if (!sessionPromise) {
    sessionPromise = fetch("/api/session", { method: "POST", credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new ApiError(r.status, "Could not start a workspace session. Is the backend running?");
        const data = (await r.json()) as { csrf_token: string };
        csrf = data.csrf_token;
        return csrf;
      })
      .finally(() => {
        sessionPromise = null;
      });
  }
  return sessionPromise;
}

export function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "detail" in detail) return errorMessage((detail as { detail: unknown }).detail, fallback);
  return fallback;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = await ensureSession();
  const method = init.method ?? "GET";
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { ...(init.body !== undefined ? { "content-type": "application/json" } : {}), ...(method !== "GET" ? { "x-csrf-token": token } : {}) },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  return data as T;
}

export async function downloadUrl(path: string): Promise<void> {
  await ensureSession();
  const a = document.createElement("a");
  a.href = `/api${path}`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
