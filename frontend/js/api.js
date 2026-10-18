// Thin fetch wrapper around the AuraSense REST API (same origin).

async function req(method, path, body, isForm = false) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opt.body = body;
    else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("application/json") ? r.json() : r.blob();
}

export const api = {
  get: (p, params) => req("GET", params ? `${p}?${new URLSearchParams(params)}` : p),
  post: (p, body) => req("POST", p, body),
  put: (p, body) => req("PUT", p, body),
  del: (p) => req("DELETE", p),
  form: (p, fd) => req("POST", p, fd, true),
  file: (rel) => `/api/files/${rel}`,
};

export async function fetchBlob(url) {
  const r = await fetch(url);
  return r.blob();
}
