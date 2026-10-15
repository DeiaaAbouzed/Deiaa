// Minimal hash router. Each view renders into the root and may return a cleanup function.
import { clear } from './dom.js';
import { hasRole } from './state.js';
import { loading, showError } from './ui.js';

const routes = [];
let cleanup = null;
let renderId = 0;
let rootEl = null;
let fallbackFn = () => '';
let afterNavigate = () => {};

export function route(pattern, view, roles) {
  const keys = [];
  const regex = new RegExp(
    '^' +
      pattern.replace(/:(\w+)/g, (_, key) => {
        keys.push(key);
        return '([^/]+)';
      }) +
      '$',
  );
  routes.push({ pattern, regex, keys, view, roles });
}

export function navigate(path) {
  const target = `#/${path}`;
  if (window.location.hash === target) render();
  else window.location.hash = target;
}

export function currentPath() {
  return window.location.hash.replace(/^#\/?/, '').split('?')[0];
}

export function start(root, fallback, onNavigate) {
  rootEl = root;
  fallbackFn = fallback;
  afterNavigate = onNavigate || afterNavigate;
  window.addEventListener('hashchange', render);
  render();
}

export function stop() {
  window.removeEventListener('hashchange', render);
  if (cleanup) cleanup();
  cleanup = null;
}

async function render() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const [path, queryString] = raw.split('?');
  const query = Object.fromEntries(new URLSearchParams(queryString || ''));
  const match = routes.find((r) => r.regex.test(path));
  if (!match || (match.roles && !hasRole(match.roles))) {
    navigate(fallbackFn());
    return;
  }
  const params = {};
  const values = match.regex.exec(path).slice(1);
  match.keys.forEach((key, i) => {
    params[key] = decodeURIComponent(values[i]);
  });

  if (cleanup) {
    try {
      cleanup();
    } catch {
      /* ignore */
    }
    cleanup = null;
  }
  const id = ++renderId;
  clear(rootEl).append(loading());
  afterNavigate(path);
  window.scrollTo(0, 0);
  try {
    const container = document.createElement('div');
    const result = await match.view(container, params, query);
    if (id !== renderId) {
      if (typeof result === 'function') result();
      return; // the user navigated away meanwhile
    }
    clear(rootEl).append(container);
    cleanup = typeof result === 'function' ? result : null;
    const heading = rootEl.querySelector('h1');
    if (heading) {
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
  } catch (error) {
    if (id !== renderId) return;
    clear(rootEl);
    if (error && error.status !== 401) showError(error);
  }
}
