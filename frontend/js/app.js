import { get, on, post, setCsrf } from './lib/api.js';
import { clear, h, mount } from './lib/dom.js';
import { icon, logo } from './lib/icons.js';
import { ROLES } from './lib/labels.js';
import { currentPath, navigate, route, start, stop } from './lib/router.js';
import { ADMIN, EVERYONE, MANAGERS, STAFF, hasRole, homeRoute, state } from './lib/state.js';
import { loading, modal, showError } from './lib/ui.js';
import { renderLogin, renderOnboarding } from './views/login.js';

const root = document.getElementById('root');

// ---------- theme ----------
function storedTheme() {
  try {
    return localStorage.getItem('rushd-theme') || 'auto';
  } catch {
    return 'auto';
  }
}
function applyTheme(theme) {
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem('rushd-theme', theme);
  } catch {
    /* private mode */
  }
}
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
}

// ---------- routes ----------
const lazy = (path) => (container, params, query) => import(path).then((m) => m.default(container, params, query));
route('read', lazy('./views/read.js'), STAFF);
route('rx/:uid', lazy('./views/rx.js'), STAFF);
route('review', lazy('./views/review.js'), STAFF);
route('history', lazy('./views/history.js'), STAFF);
route('academy', lazy('./views/academy.js'), EVERYONE);
route('feed', lazy('./views/feed.js'), MANAGERS);
route('training', lazy('./views/training.js'), MANAGERS);
route('drugs', lazy('./views/drugs.js'), STAFF);
route('doctors', lazy('./views/doctors.js'), MANAGERS);
route('users', lazy('./views/users.js'), ADMIN);
route('settings', lazy('./views/settings.js'), ADMIN);
route('audit', lazy('./views/audit.js'), ADMIN);
route('account', lazy('./views/account.js'), EVERYONE);

const NAV = [
  { id: 'read', label: 'قراءة روشتة', icon: 'scan', roles: STAFF, primary: true },
  { id: 'review', label: 'المراجعة', icon: 'inbox', roles: STAFF, primary: true, badge: true },
  { id: 'history', label: 'السجل', icon: 'clock', roles: STAFF, primary: true },
  { id: 'academy', label: 'الأكاديمية', icon: 'book', roles: EVERYONE, primary: true },
  { section: 'التعلّم والبيانات', roles: STAFF },
  { id: 'feed', label: 'تغذية النظام', icon: 'layers', roles: MANAGERS },
  { id: 'training', label: 'مركز التدريب', icon: 'chart', roles: MANAGERS },
  { id: 'drugs', label: 'قاعدة الأدوية', icon: 'pill', roles: STAFF },
  { id: 'doctors', label: 'الأطباء', icon: 'doctor', roles: MANAGERS },
  { section: 'الإدارة والأمان', roles: ADMIN },
  { id: 'users', label: 'المستخدمون', icon: 'users', roles: ADMIN },
  { id: 'settings', label: 'الإعدادات', icon: 'sliders', roles: ADMIN },
  { id: 'audit', label: 'سجل الأمان', icon: 'shield', roles: ADMIN },
  { id: 'account', label: 'حسابي', icon: 'user', roles: EVERYONE },
];

// ---------- shell ----------
let navLinks = [];
let reviewBadges = [];

function initials(user) {
  // One letter only: two Arabic initials side by side join into an (often unfortunate) word.
  const name = (user.full_name || user.username || '?').replace(/^(د|دكتور|dr)\.?\s+/i, '').trim();
  return name.charAt(0).toUpperCase();
}

function navLink(item, cls = '') {
  const badge = item.badge ? h('span', { class: 'nav-badge hidden' }) : null;
  if (badge) reviewBadges.push(badge);
  const link = h('a', { href: `#/${item.id}`, class: cls, dataset: { route: item.id } }, icon(item.icon), h('span', {}, item.label), badge);
  navLinks.push(link);
  return link;
}

function openMoreSheet(items) {
  const list = h('div', { class: 'stack' }, items.map((item) => h('a', { href: `#/${item.id}`, class: 'btn block', onClick: () => sheet.close() }, icon(item.icon), item.label)));
  const sheet = modal({ title: 'المزيد', body: list });
}

function userMenu() {
  const user = state.me.user;
  const body = h(
    'div',
    { class: 'stack' },
    h('div', { class: 'row' }, h('span', { class: 'avatar' }, initials(user)), h('div', {}, h('strong', {}, user.full_name || user.username), h('div', { class: 'muted small' }, `${ROLES[user.role]}${user.branch ? ` - ${user.branch}` : ''}`))),
    h('a', { href: '#/account', class: 'btn block', onClick: () => menu.close() }, icon('user'), 'حسابي والأمان'),
    h('button', { class: 'btn danger block', type: 'button', onClick: () => { menu.close(); logout(); } }, icon('logout'), 'تسجيل الخروج'),
  );
  const menu = modal({ title: 'الحساب', body });
}

function renderShell() {
  navLinks = [];
  reviewBadges = [];
  const me = state.me;
  const visible = NAV.filter((item) => hasRole(item.roles));
  const sidenav = h(
    'nav',
    { class: 'sidenav', 'aria-label': 'القائمة الرئيسية' },
    visible.map((item) => (item.section ? h('div', { class: 'nav-section' }, item.section) : navLink(item))),
  );
  const links = visible.filter((i) => !i.section);
  const primary = links.filter((i) => i.primary).slice(0, 4);
  const rest = links.filter((i) => !primary.includes(i));
  const bottom = h(
    'nav',
    { class: 'bottom-nav', 'aria-label': 'التنقل السريع' },
    primary.map((item) => navLink(item)),
    rest.length ? h('a', { href: '#', onClick: (e) => { e.preventDefault(); openMoreSheet(rest); } }, icon('more'), h('span', {}, 'المزيد')) : null,
  );
  const themeBtn = h('button', { class: 'btn icon ghost', type: 'button', title: 'تبديل المظهر', 'aria-label': 'تبديل المظهر' }, icon(isDark() ? 'sun' : 'moon'));
  themeBtn.addEventListener('click', () => {
    applyTheme(isDark() ? 'light' : 'dark');
    mount(themeBtn, icon(isDark() ? 'sun' : 'moon'));
  });
  const header = h(
    'header',
    { class: 'app-header' },
    h('a', { class: 'brand', href: `#/${homeRoute()}` }, logo(), h('span', {}, me.app.name || 'رُشد', h('small', {}, me.app.pharmacy_name || 'قارئ الروشتات الذكي'))),
    h(
      'div',
      { class: 'header-actions' },
      themeBtn,
      h('button', { class: 'user-chip', type: 'button', onClick: userMenu, 'aria-label': 'قائمة الحساب' }, h('span', { class: 'small' }, me.user.full_name || me.user.username), h('span', { class: 'avatar' }, initials(me.user))),
    ),
  );
  const view = h('main', { id: 'view', tabindex: '-1' });
  mount(root, header, h('div', { class: 'layout' }, sidenav, view), bottom);
  return view;
}

function markActive(path) {
  const section = path.split('/')[0];
  if (section !== 'rx') {
    // A prescription page belongs to wherever it was opened from (read, review, history).
    for (const link of navLinks) link.classList.toggle('active', link.dataset.route === section);
  }
  refreshReviewBadge();
}

let badgeTimer = null;
async function refreshReviewBadge() {
  if (!hasRole(STAFF) || !reviewBadges.length) return;
  clearTimeout(badgeTimer);
  badgeTimer = setTimeout(async () => {
    try {
      const { remaining } = await get('/api/review/next');
      for (const b of reviewBadges) {
        b.textContent = remaining > 99 ? '99+' : new Intl.NumberFormat('ar-EG').format(remaining);
        b.classList.toggle('hidden', !remaining);
      }
    } catch {
      /* non-critical */
    }
  }, 300);
}

// ---------- session ----------
async function logout() {
  try {
    await post('/api/auth/logout');
  } catch {
    /* session may already be gone */
  }
  state.me = null;
  setCsrf(null);
  stop();
  showLogin();
}

function showLogin(message = null) {
  stop();
  state.me = null;
  renderLogin(root, { message, onSuccess: enter });
}

function enter(me) {
  state.me = me;
  setCsrf(me.csrf);
  if (me.flags.must_change_password || me.flags.must_setup_2fa) {
    renderOnboarding(root, me, (updated) => enter(updated));
    return;
  }
  const view = renderShell();
  if (!window.location.hash || window.location.hash === '#/' || window.location.hash === '#') {
    window.history.replaceState(null, '', `#/${homeRoute()}`);
  }
  start(view, homeRoute, markActive);
  if (currentPath()) markActive(currentPath());
}

on('unauthorized', () => {
  if (state.me) showLogin('انتهت جلستك لحماية البيانات، سجّل الدخول مرة أخرى.');
});
on('restricted', async () => {
  try {
    enter(await get('/api/auth/me'));
  } catch (error) {
    showError(error);
  }
});

async function boot() {
  applyTheme(storedTheme());
  clear(root).append(loading());
  try {
    enter(await get('/api/auth/me'));
  } catch (error) {
    if (error.status === 401) showLogin();
    else renderLogin(root, { message: error.message, onSuccess: enter });
  }
  if ('serviceWorker' in navigator && (window.location.protocol === 'https:' || window.location.hostname === 'localhost')) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

window.addEventListener('rushd:navigate', (e) => navigate(e.detail));
boot();
