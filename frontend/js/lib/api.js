// Thin fetch wrapper: same-origin cookies, CSRF header, Arabic errors.

let csrfToken = null;
const handlers = { unauthorized: [], restricted: [] };

export class ApiError extends Error {
  constructor(status, message, code = null, data = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function setCsrf(token) {
  csrfToken = token;
}

export function on(event, fn) {
  handlers[event].push(fn);
}

function buildUrl(path, query) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== null && value !== undefined && value !== '') url.searchParams.set(key, value);
  }
  return url;
}

function fail(status, data, path) {
  const message = (data && typeof data.detail === 'string' && data.detail) || `حدث خطأ (${status})`;
  const error = new ApiError(status, message, data && data.code, data);
  if (status === 401 && !path.startsWith('/api/auth/login')) handlers.unauthorized.forEach((fn) => fn(error));
  if (status === 403 && ['password_change_required', 'totp_setup_required'].includes(error.code)) {
    handlers.restricted.forEach((fn) => fn(error));
  }
  return error;
}

// Account administration answers 403 step_up_required until the password is re-entered; the app
// registers a dialog here, and the original request is retried once after a successful step-up.
let stepUpProvider = null;
export function setStepUpProvider(fn) {
  stepUpProvider = fn;
}

export async function request(method, path, options = {}) {
  try {
    return await send(method, path, options);
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== 'step_up_required' || !stepUpProvider) throw error;
    const credentials = await stepUpProvider();
    if (!credentials) throw new ApiError(403, 'تم الإلغاء', 'cancelled');
    await send('POST', '/api/auth/step-up', { json: credentials });
    return send(method, path, options);
  }
}

async function send(method, path, { json, form, query, signal, raw = false } = {}) {
  const headers = { Accept: 'application/json' };
  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  let response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body,
      signal,
      credentials: 'same-origin',
      cache: 'no-store',
      redirect: 'error',
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, 'تعذر الاتصال بالخادم - تحقق من الشبكة');
  }
  if (raw && response.ok) return response;
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json().catch(() => null) : null;
  if (!response.ok) throw fail(response.status, data, path);
  return data;
}

export const get = (path, query, opts = {}) => request('GET', path, { ...opts, query });
export const post = (path, json, opts = {}) => request('POST', path, { ...opts, json });
export const put = (path, json) => request('PUT', path, { json });
export const del = (path) => request('DELETE', path);
export const postForm = (path, form) => request('POST', path, { form });

/** Multipart upload with progress (fetch cannot report upload progress). */
export function upload(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', path);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.responseType = 'json';
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(fail(xhr.status, xhr.response, path));
    };
    xhr.onerror = () => reject(new ApiError(0, 'انقطع الاتصال أثناء الرفع'));
    xhr.send(form);
  });
}

/** Fetch a file (CSV export, encrypted dataset) and hand it to the browser as a download. */
export async function download(method, path, { json, filename } = {}) {
  const response = await request(method, path, { json, raw: true });
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/);
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename || (match ? match[1] : 'download');
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
}
