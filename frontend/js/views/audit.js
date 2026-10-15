import { get, post } from '../lib/api.js';
import { h, ltr, mount } from '../lib/dom.js';
import { AUDIT_ACTIONS } from '../lib/labels.js';
import { alertBox, button, fmtDateTime, fmtNum, loading, pageHead, setBusy, showError } from '../lib/ui.js';

const ALERTING = new Set(['login_failed', 'account_locked', 'password_change_failed', 'prescription_deleted', 'dataset_exported', 'totp_reset', 'sessions_revoked']);

export default async function auditView(root) {
  let page = 1;
  let action = '';
  const list = h('div', {});
  const result = h('div', {});
  const filter = h('select', { class: 'select', 'aria-label': 'نوع الحدث', onChange: (e) => { action = e.target.value; page = 1; load(); } }, h('option', { value: '' }, 'كل الأحداث'), Object.entries(AUDIT_ACTIONS).map(([v, t]) => h('option', { value: v }, t)));

  async function load() {
    mount(list, loading());
    const data = await get('/api/audit', { page, action });
    const pages = Math.max(1, Math.ceil(data.total / 50));
    mount(
      list,
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'table' },
          h('thead', {}, h('tr', {}, h('th', {}, 'الوقت'), h('th', {}, 'المستخدم'), h('th', {}, 'الحدث'), h('th', {}, 'الهدف'), h('th', {}, 'IP'))),
          h(
            'tbody',
            {},
            data.items.map((e) =>
              h(
                'tr',
                {},
                h('td', { class: 'small num' }, fmtDateTime(e.ts)),
                h('td', {}, ltr(e.username || '—')),
                h('td', {}, h('span', { class: ALERTING.has(e.action) ? 'error-text' : '' }, AUDIT_ACTIONS[e.action] || e.action)),
                h('td', { class: 'small' }, ltr(e.target)),
                h('td', { class: 'small muted' }, ltr(e.ip)),
              ),
            ),
          ),
        ),
      ),
      h(
        'div',
        { class: 'row', style: { 'justify-content': 'center', 'margin-top': '12px' } },
        page > 1 ? button('الأحدث', { size: 'sm', onClick: () => { page -= 1; load(); } }) : null,
        h('span', { class: 'small muted' }, `${fmtNum(data.total)} حدث · صفحة ${fmtNum(page)} من ${fmtNum(pages)}`),
        page < pages ? button('الأقدم', { size: 'sm', onClick: () => { page += 1; load(); } }) : null,
      ),
    );
  }

  const verify = button('فحص سلامة السجل', { kind: 'primary', iconName: 'shield' });
  verify.addEventListener('click', async () => {
    setBusy(verify, true, 'جاري الفحص...');
    try {
      const r = await post('/api/audit/verify');
      mount(
        result,
        r.ok
          ? alertBox('good', 'السجل سليم ولم يتم العبث به', `تم التحقق من ${fmtNum(r.checked)} حدثاً بسلسلة توقيع مشفرة.`, 'shield')
          : alertBox('bad', 'تحذير: تم العبث بسجل الأمان!', `${r.reason} (السطر رقم ${fmtNum(r.broken_at)}). أبلغ مسؤول النظام فوراً.`),
      );
    } catch (error) {
      showError(error);
    } finally {
      setBusy(verify, false);
    }
  });

  root.append(
    pageHead('سجل الأمان', 'كل دخول وكل وصول لبيانات المرضى مسجّل بسلسلة توقيعات لا يمكن تعديلها دون اكتشاف ذلك', verify),
    result,
    h('div', { class: 'row', style: { margin: '12px 0' } }, filter),
    list,
  );
  await load();
}
