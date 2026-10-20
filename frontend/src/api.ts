export type User = { id: number; email: string; name: string; role: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** FastAPI devuelve `detail` como texto, o como lista de errores de validación (422). */
const formatDetail = (detail: unknown): string => {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => (e && typeof e === "object" && "msg" in e ? `${(e as { loc?: unknown[] }).loc?.slice(1).join(".") ?? ""}: ${(e as { msg: string }).msg}` : String(e)))
      .join("; ");
  }
  return JSON.stringify(detail);
};

const readCookie = (name: string): string | null => {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
};

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const method = (init.method ?? (init.json !== undefined ? "POST" : "GET")).toUpperCase();
  const headers = new Headers(init.headers);
  if (init.json !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(path, {
    ...init,
    method,
    headers,
    credentials: "same-origin",
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = formatDetail(data.detail ?? data);
    } catch {
      /* cuerpo no JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** POST con JSON que devuelve un fichero (p. ej. la vista previa PNG del editor de imágenes). */
export async function apiBlob(path: string, json: unknown, signal?: AbortSignal): Promise<Blob> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const csrf = readCookie("csrf");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(path, { method: "POST", headers, credentials: "same-origin", body: JSON.stringify(json), signal });
  if (!res.ok) {
    let detail = res.statusText;
    try { const data = await res.json(); detail = formatDetail(data.detail ?? data); } catch { /* no JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}
