import { get } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { MANAGERS, hasRole } from '../lib/state.js';
import { badge, button, drugCount, empty, fmtNum, fmtPct, loading, pageHead, statusBadge, timeAgo } from '../lib/ui.js';

const FILTERS = [
  ['', 'الكل'],
  ['needs_review', 'تحتاج مراجعة'],
  ['verified', 'معتمدة'],
  ['queued,processing', 'قيد القراءة'],
  ['failed', 'فشلت'],
  ['rejected', 'مرفوضة'],
];

export default async function historyView(root, _params, query) {
  let status = query.status || '';
  let page = 1;
  let mine = !hasRole(MANAGERS) || query.mine === '1';
  const list = h('div', { class: 'rx-list' });
  const pager = h('div', { class: 'row', style: { 'justify-content': 'center', 'margin-top': '16px' } });
  const tabs = h(
    'div',
    { class: 'tabs', role: 'tablist' },
    FILTERS.map(([value, label]) =>
      h('button', { type: 'button', role: 'tab', class: value === status ? 'active' : '', onClick: (e) => { status = value; page = 1; [...tabs.children].forEach((b) => b.classList.toggle('active', b === e.currentTarget)); load(); } }, label),
    ),
  );

  async function load() {
    mount(list, loading());
    const data = await get('/api/prescriptions', { status, page, mine: mine ? 'true' : null, batch_id: query.batch || null, doctor_id: query.doctor || null });
    if (!data.items.length) {
      mount(list, empty('لا توجد روشتات هنا بعد', 'clock'));
      mount(pager);
      return;
    }
    mount(
      list,
      data.items.map((rx) =>
        h(
          'a',
          { class: 'rx-row', href: `#/rx/${rx.uid}` },
          h('img', { src: `/api/prescriptions/${rx.uid}/image?variant=thumb`, alt: '', loading: 'lazy' }),
          h(
            'div',
            { class: 'grow' },
            h('div', { class: 'row' }, h('strong', {}, rx.doctor ? rx.doctor.name : 'طبيب غير محدد'), statusBadge(rx.status)),
            h(
              'div',
              { class: 'small muted' },
              `${timeAgo(rx.created_at)} · ${drugCount(rx.num_items)}`,
              rx.uploaded_by && hasRole(MANAGERS) ? ` · ${rx.uploaded_by}` : '',
            ),
            rx.error && rx.status === 'failed' ? h('div', { class: 'small error-text' }, rx.error) : null,
          ),
          rx.acc_drug !== null && rx.acc_drug !== undefined
            ? badge(`دقة الآلة ${fmtPct(rx.acc_drug)}`, rx.acc_drug >= 0.99 ? 'good' : 'warn')
            : rx.ai_confidence
              ? badge(`ثقة ${fmtPct(rx.ai_confidence)}`)
              : null,
        ),
      ),
    );
    const pages = Math.ceil(data.total / 30);
    mount(
      pager,
      page > 1 ? button('السابق', { size: 'sm', iconName: 'chevronRight', onClick: () => { page -= 1; load(); } }) : null,
      h('span', { class: 'small muted' }, `صفحة ${fmtNum(page)} من ${fmtNum(pages)} (${fmtNum(data.total)} روشتة)`),
      page < pages ? button('التالي', { size: 'sm', iconName: 'chevronLeft', onClick: () => { page += 1; load(); } }) : null,
    );
  }

  const mineToggle = hasRole(MANAGERS)
    ? h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: mine, onChange: (e) => { mine = e.target.checked; page = 1; load(); } }), 'روشتاتي فقط')
    : null;
  root.append(pageHead('سجل الروشتات', hasRole(MANAGERS) ? 'كل الروشتات في الفروع' : 'الروشتات التي قرأتها'), h('div', { class: 'row between' }, tabs, mineToggle), list, pager);
  await load();
}
