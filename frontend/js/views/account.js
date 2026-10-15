import { del, get, post } from '../lib/api.js';
import { h, ltr, mount } from '../lib/dom.js';
import { ROLES } from '../lib/labels.js';
import { state } from '../lib/state.js';
import { alertBox, badge, button, field, pageHead, setBusy, showError, stepUp, timeAgo, toast } from '../lib/ui.js';

export default async function accountView(root) {
  const me = state.me;
  const sessionsBox = h('div', { class: 'stack' });

  async function loadSessions() {
    const sessions = await get('/api/auth/sessions');
    mount(
      sessionsBox,
      sessions.map((s) =>
        h(
          'div',
          { class: 'row between card flat' },
          h('div', {}, h('div', { class: 'small' }, ltr(s.user_agent.slice(0, 80) || 'متصفح')), h('div', { class: 'small muted' }, ltr(s.ip), ` · آخر نشاط ${timeAgo(s.last_seen_at)}`)),
          s.current ? badge('هذا الجهاز', 'good') : button('إنهاء', { size: 'sm', kind: 'danger', onClick: async () => { await del(`/api/auth/sessions/${s.id}`); loadSessions(); } }),
        ),
      ),
    );
  }

  const current = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
  const fresh = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const again = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const change = button('تغيير كلمة المرور', { kind: 'primary', iconName: 'key' });
  change.addEventListener('click', async () => {
    if (fresh.value !== again.value) return showError({ message: 'كلمتا المرور غير متطابقتين' });
    setBusy(change, true);
    try {
      state.me = await post('/api/auth/password', { current: current.value, new: fresh.value });
      current.value = fresh.value = again.value = '';
      toast('تم تغيير كلمة المرور وإنهاء جلساتك الأخرى');
      loadSessions();
    } catch (error) {
      showError(error);
    } finally {
      setBusy(change, false);
    }
  });

  const twofa = h('div', { class: 'stack' });
  function renderTwofa() {
    if (state.me.user.totp_enabled) {
      mount(
        twofa,
        alertBox('good', 'التحقق بخطوتين مفعّل', 'حسابك محمي برمز من تطبيق المصادقة عند كل دخول.', 'shield'),
        me.user.role === 'admin'
          ? null
          : button('إيقاف التحقق بخطوتين', {
              kind: 'danger',
              size: 'sm',
              onClick: async () => {
                const confirm = await stepUp('إيقاف التحقق بخطوتين', { totp: true });
                if (!confirm) return;
                try {
                  state.me = await post('/api/auth/totp/disable', confirm);
                  renderTwofa();
                } catch (error) {
                  showError(error);
                }
              },
            }),
      );
      return;
    }
    const password = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
    const begin = button('تفعيل التحقق بخطوتين', { kind: 'primary', iconName: 'shield' });
    begin.addEventListener('click', async () => {
      try {
        const setup = await post('/api/auth/totp/setup', { password: password.value });
        const code = h('input', { class: 'input code', inputmode: 'numeric', maxlength: 6, placeholder: '000000' });
        mount(
          twofa,
          h('p', {}, 'امسح الرمز بتطبيق المصادقة ثم أدخل الرمز الظاهر:'),
          h('div', { class: 'qr-box' }, h('img', { src: setup.qr, alt: 'رمز QR', width: 196, height: 196 })),
          h('div', { class: 'code-sample' }, setup.secret),
          code,
          button('تأكيد', {
            kind: 'primary',
            onClick: async () => {
              try {
                state.me = await post('/api/auth/totp/enable', { code: code.value });
                toast('تم تفعيل التحقق بخطوتين');
                renderTwofa();
              } catch (error) {
                showError(error);
              }
            },
          }),
        );
      } catch (error) {
        showError(error);
      }
    });
    mount(twofa, alertBox('warn', 'التحقق بخطوتين غير مفعّل', 'فعّله لحماية حسابك حتى لو سُرقت كلمة المرور.'), field('كلمة المرور', password), begin);
  }
  renderTwofa();

  root.append(
    pageHead('حسابي', `${me.user.full_name || me.user.username} - ${ROLES[me.user.role]}`),
    h(
      'div',
      { class: 'grid-2' },
      h('div', { class: 'card stack' }, h('h2', {}, 'كلمة المرور'), field('الحالية', current), field('الجديدة', fresh), field('تأكيد الجديدة', again), change),
      h('div', { class: 'card stack' }, h('h2', {}, 'التحقق بخطوتين'), twofa),
    ),
    h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', {}, 'الأجهزة المتصلة بحسابك')), sessionsBox),
  );
  await loadSessions();
}
