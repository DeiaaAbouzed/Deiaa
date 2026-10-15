import { h, mount } from './dom.js';
import { icon } from './icons.js';
import { LEVELS, STATUSES } from './labels.js';

// ---------- formatting (Arabic, Egypt) ----------
const nf = new Intl.NumberFormat('ar-EG');
const pf = new Intl.NumberFormat('ar-EG', { style: 'percent', maximumFractionDigits: 1 });
const usd = new Intl.NumberFormat('ar-EG', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const dtf = new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium', timeStyle: 'short' });
const df = new Intl.DateTimeFormat('ar-EG', { day: 'numeric', month: 'short' });

export const fmtNum = (n) => (n === null || n === undefined ? '—' : nf.format(n));
export const fmtPct = (x) => (x === null || x === undefined ? '—' : pf.format(x));
export const fmtUsd = (x) => (x === null || x === undefined ? '—' : usd.format(x));
export const fmtDateTime = (iso) => (iso ? dtf.format(new Date(iso)) : '—');
export const fmtDay = (iso) => (iso ? df.format(new Date(iso)) : '—');

export function drugCount(n) {
  if (n === 0) return 'بدون أدوية';
  if (n === 1) return 'دواء واحد';
  if (n === 2) return 'دواءان';
  if (n >= 3 && n <= 10) return `${fmtNum(n)} أدوية`;
  return `${fmtNum(n)} دواءً`;
}

export function timeAgo(iso) {
  if (!iso) return '—';
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat('ar-EG', { numeric: 'auto' });
  if (seconds < 60) return rtf.format(-seconds, 'second');
  if (seconds < 3600) return rtf.format(-Math.round(seconds / 60), 'minute');
  if (seconds < 86400) return rtf.format(-Math.round(seconds / 3600), 'hour');
  return rtf.format(-Math.round(seconds / 86400), 'day');
}

// ---------- small components ----------
export function badge(text, kind = '', iconName = null) {
  return h('span', { class: `badge ${kind}` }, iconName ? icon(iconName) : null, text);
}

export function statusBadge(status) {
  const s = STATUSES[status] || { label: status, kind: '' };
  return badge(s.label, s.kind);
}

export function levelBadge(level) {
  const l = LEVELS[level] || LEVELS.medium;
  return badge(l.label, l.kind, l.icon);
}

export function button(label, { kind = '', iconName = null, onClick = null, type = 'button', size = '', title = null, disabled = false } = {}) {
  return h(
    'button',
    { class: `btn ${kind} ${size}`.trim(), type, onClick, title, 'aria-label': title || null, disabled },
    iconName ? icon(iconName) : null,
    label,
  );
}

export function iconButton(iconName, title, onClick, kind = 'ghost') {
  return h('button', { class: `btn icon ${kind}`, type: 'button', title, 'aria-label': title, onClick }, icon(iconName));
}

export function field(label, control, hint = null) {
  return h('label', { class: 'field' }, h('span', {}, label, hint ? h('span', { class: 'hint' }, ` - ${hint}`) : null), control);
}

export function empty(message, iconName = 'inbox', action = null) {
  return h('div', { class: 'empty' }, icon(iconName), h('p', {}, message), action ? h('div', { class: 'row', style: { 'justify-content': 'center', 'margin-top': '12px' } }, action) : null);
}

export function loading() {
  return h('div', { class: 'loading-block' }, h('span', { class: 'spinner', role: 'status', 'aria-label': 'جاري التحميل' }));
}

export function alertBox(kind, title, text = null, iconName = null) {
  const icons = { info: 'info', warn: 'alert', bad: 'alert', good: 'check' };
  return h('div', { class: `alert ${kind}`, role: kind === 'bad' ? 'alert' : null }, icon(iconName || icons[kind] || 'info'), h('div', {}, h('strong', {}, title), text ? h('span', {}, text) : null));
}

export function pageHead(title, subtitle = null, ...actions) {
  return h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, title), subtitle ? h('p', {}, subtitle) : null), actions.length ? h('div', { class: 'row' }, actions) : null);
}

export function progressBar(fraction) {
  const bar = h('span', {});
  bar.style.setProperty('width', `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`);
  return h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': Math.round(fraction * 100), 'aria-valuemin': 0, 'aria-valuemax': 100 }, bar);
}

// ---------- toast ----------
export function toast(message, kind = '') {
  const box = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind}` }, icon(kind === 'bad' ? 'alert' : 'check'), h('span', {}, message));
  box.append(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 6000 : 3500);
}

export function showError(error) {
  toast(error && error.message ? error.message : 'حدث خطأ غير متوقع', 'bad');
}

// ---------- modal ----------
export function modal({ title, body, actions = [], wide = false, onClose = null }) {
  const previous = document.activeElement;
  const close = () => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
    if (previous && previous.focus) previous.focus();
    if (onClose) onClose();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') close();
  };
  const dialog = h(
    'div',
    { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('div', { class: 'modal-head' }, h('h2', {}, title), iconButton('x', 'إغلاق', close)),
    body,
    actions.length ? h('div', { class: 'modal-actions' }, actions.map((a) => button(a.label, { kind: a.kind || '', iconName: a.icon, onClick: () => a.onClick(close) }))) : null,
  );
  const backdrop = h('div', { class: 'modal-backdrop', onClick: (e) => e.target === backdrop && close() }, dialog);
  document.body.append(backdrop);
  document.addEventListener('keydown', onKey);
  const focusable = dialog.querySelector('input, select, textarea, button.primary');
  (focusable || dialog).focus();
  return { close, dialog };
}

export function confirmDialog(message, { title = 'تأكيد', confirm = 'تأكيد', danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    modal({
      title,
      body: h('p', {}, message),
      actions: [
        { label: 'إلغاء', onClick: (close) => { done = true; close(); resolve(false); } },
        { label: confirm, kind: danger ? 'danger' : 'primary', onClick: (close) => { done = true; close(); resolve(true); } },
      ],
      onClose: () => { if (!done) resolve(false); },
    });
  });
}

/** Ask the user to re-enter their password (+ 2FA code) before a sensitive action. */
export function stepUp(title, { totp = false, extra = null, note = 'هذا إجراء حساس؛ أدخل كلمة مرورك للمتابعة.' } = {}) {
  return new Promise((resolve) => {
    const password = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
    const code = h('input', { class: 'input code', inputmode: 'numeric', maxlength: 6, autocomplete: 'one-time-code', placeholder: '000000' });
    let done = false;
    const submit = (close) => {
      if (!password.value) return password.focus();
      done = true;
      close();
      resolve({ password: password.value, totp: totp ? code.value || null : null, extra: extra ? extra.read() : null });
    };
    const form = h(
      'form',
      { class: 'stack', onSubmit: (e) => { e.preventDefault(); submit(handle.close); } },
      alertBox('info', 'تأكيد الهوية مطلوب', note, 'lock'),
      field('كلمة المرور', password),
      totp ? field('رمز التحقق بخطوتين', code) : null,
      extra ? extra.node : null,
      h('button', { type: 'submit', class: 'hidden' }),
    );
    const handle = modal({
      title,
      body: form,
      actions: [
        { label: 'إلغاء', onClick: (close) => { done = true; close(); resolve(null); } },
        { label: 'متابعة', kind: 'primary', icon: 'lock', onClick: submit },
      ],
      onClose: () => { if (!done) resolve(null); },
    });
  });
}

export function setBusy(btn, busy, text = null) {
  if (!btn) return;
  if (busy) {
    const label = text || btn.textContent;
    if (!btn._saved) btn._saved = Array.from(btn.childNodes);
    btn.disabled = true;
    mount(btn, h('span', { class: 'spinner' }), label);
  } else {
    btn.disabled = false;
    if (btn._saved) {
      mount(btn, ...btn._saved);
      btn._saved = null;
    }
  }
}
