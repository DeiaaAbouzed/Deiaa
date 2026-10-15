import { get, post, put } from '../lib/api.js';
import { h, ltr, mount } from '../lib/dom.js';
import { ROLES } from '../lib/labels.js';
import { state } from '../lib/state.js';
import { badge, button, confirmDialog, field, loading, modal, pageHead, showError, timeAgo, toast } from '../lib/ui.js';

function showTemporaryPassword(username, password) {
  const box = h('div', { class: 'code-sample', style: { 'font-size': '1.2rem', 'text-align': 'center' } }, password);
  modal({
    title: 'كلمة المرور المؤقتة',
    body: h(
      'div',
      { class: 'stack' },
      h('p', {}, 'سلّم كلمة المرور هذه للمستخدم ', ltr(username), ' بشكل آمن. لن تظهر مرة أخرى، وسيُطلب منه تغييرها عند أول دخول.'),
      box,
    ),
    actions: [
      { label: 'نسخ', icon: 'file', onClick: () => navigator.clipboard?.writeText(password).then(() => toast('تم النسخ')) },
      { label: 'تم', kind: 'primary', onClick: (close) => close() },
    ],
  });
}

export default async function usersView(root) {
  const list = h('div', {});
  let branches = [];

  function roleSelect(value) {
    return h('select', { class: 'select' }, Object.entries(ROLES).map(([v, t]) => h('option', { value: v, selected: v === value }, t)));
  }
  function branchSelect(value) {
    return h('select', { class: 'select' }, h('option', { value: '' }, '—'), branches.map((b) => h('option', { value: b.id, selected: b.id === value }, b.name)));
  }

  function addUser() {
    const username = h('input', { class: 'input ltr', dir: 'ltr', placeholder: 'ahmed.ali', autocapitalize: 'none' });
    const fullName = h('input', { class: 'input' });
    const role = roleSelect('pharmacist');
    const branch = branchSelect(null);
    modal({
      title: 'مستخدم جديد',
      body: h('div', { class: 'stack' }, field('اسم الدخول', username, 'حروف إنجليزية صغيرة وأرقام'), field('الاسم الكامل', fullName), h('div', { class: 'form-grid' }, field('الدور', role), field('الفرع', branch))),
      actions: [
        { label: 'إلغاء', onClick: (close) => close() },
        {
          label: 'إنشاء',
          kind: 'primary',
          icon: 'plus',
          onClick: async (close) => {
            const body = { username: username.value.trim(), full_name: fullName.value.trim(), role: role.value, branch_id: branch.value ? Number(branch.value) : null };
            try {
              const result = await post('/api/users', body);
              close();
              showTemporaryPassword(result.user.username, result.temporary_password);
              load();
            } catch (error) {
              showError(error);
            }
          },
        },
      ],
    });
  }

  function editUser(user) {
    const fullName = h('input', { class: 'input', value: user.full_name });
    const role = roleSelect(user.role);
    const branch = branchSelect(user.branch_id);
    const active = h('input', { type: 'checkbox', checked: user.is_active });
    const self = user.id === state.me.user.id;
    const run = async (fn) => {
      try {
        await fn();
        load();
      } catch (error) {
        showError(error);
      }
    };
    modal({
      title: `المستخدم ${user.username}`,
      body: h(
        'div',
        { class: 'stack' },
        field('الاسم الكامل', fullName),
        h('div', { class: 'form-grid' }, field('الدور', role), field('الفرع', branch)),
        self ? null : h('label', { class: 'check' }, active, 'الحساب مفعّل'),
        h(
          'div',
          { class: 'row' },
          button('إعادة تعيين كلمة المرور', {
            size: 'sm',
            iconName: 'key',
            onClick: () => run(async () => {
              if (!(await confirmDialog('سيتم إنهاء جلسات المستخدم وإنشاء كلمة مرور مؤقتة جديدة. متابعة؟'))) return;
              const r = await post(`/api/users/${user.id}/reset-password`);
              showTemporaryPassword(user.username, r.temporary_password);
            }),
          }),
          user.locked ? button('فك القفل', { size: 'sm', iconName: 'lock', onClick: () => run(() => post(`/api/users/${user.id}/unlock`).then(() => toast('تم فك القفل'))) }) : null,
          user.totp_enabled
            ? button('إعادة ضبط التحقق بخطوتين', {
                size: 'sm',
                iconName: 'shield',
                onClick: () => run(async () => {
                  if (!(await confirmDialog('سيُطلب من المستخدم إعداد التحقق بخطوتين من جديد عند دخوله. متابعة؟'))) return;
                  await post(`/api/users/${user.id}/reset-2fa`);
                  toast('تمت إعادة الضبط');
                }),
              })
            : null,
          button('إنهاء كل الجلسات', { size: 'sm', iconName: 'logout', onClick: () => run(() => post(`/api/users/${user.id}/revoke-sessions`).then(() => toast('تم إنهاء الجلسات'))) }),
        ),
      ),
      actions: [
        { label: 'إلغاء', onClick: (close) => close() },
        {
          label: 'حفظ',
          kind: 'primary',
          onClick: async (close) => {
            const body = { full_name: fullName.value.trim(), role: role.value, branch_id: branch.value ? Number(branch.value) : null };
            if (!self) body.is_active = active.checked;
            try {
              await put(`/api/users/${user.id}`, body);
              close();
              toast('تم الحفظ');
              load();
            } catch (error) {
              showError(error);
            }
          },
        },
      ],
    });
  }

  function addBranch() {
    const name = h('input', { class: 'input', placeholder: 'فرع مدينة نصر' });
    modal({
      title: 'فرع جديد',
      body: field('اسم الفرع', name),
      actions: [
        { label: 'إلغاء', onClick: (close) => close() },
        { label: 'إضافة', kind: 'primary', onClick: async (close) => { try { await post('/api/branches', { name: name.value.trim() }); close(); load(); } catch (error) { showError(error); } } },
      ],
    });
  }

  async function load() {
    mount(list, loading());
    const [users, br] = await Promise.all([get('/api/users'), get('/api/branches')]);
    branches = br;
    mount(
      list,
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'table' },
          h('thead', {}, h('tr', {}, h('th', {}, 'المستخدم'), h('th', {}, 'الدور'), h('th', {}, 'الفرع'), h('th', {}, 'الحالة'), h('th', {}, 'آخر دخول'))),
          h(
            'tbody',
            {},
            users.map((u) =>
              h(
                'tr',
                { class: 'clickable', tabindex: '0', onClick: () => editUser(u), onKeydown: (e) => e.key === 'Enter' && editUser(u) },
                h('td', {}, h('strong', {}, u.full_name || u.username), h('div', { class: 'small muted' }, ltr(u.username))),
                h('td', {}, ROLES[u.role]),
                h('td', {}, u.branch || '—'),
                h(
                  'td',
                  {},
                  h(
                    'div',
                    { class: 'row' },
                    u.is_active ? null : badge('معطّل', 'bad'),
                    u.locked ? badge('مقفل مؤقتاً', 'warn', 'lock') : null,
                    u.totp_enabled ? badge('2FA', 'good', 'shield') : null,
                    u.must_change_password ? badge('كلمة مرور مؤقتة', 'warn') : null,
                  ),
                ),
                h('td', { class: 'small muted' }, timeAgo(u.last_login_at)),
              ),
            ),
          ),
        ),
      ),
    );
  }

  root.append(
    pageHead('المستخدمون والفروع', 'كل مستخدم يرى فقط ما يحتاجه لدوره', button('فرع جديد', { iconName: 'plus', onClick: addBranch }), button('مستخدم جديد', { kind: 'primary', iconName: 'plus', onClick: addUser })),
    list,
  );
  await load();
}
