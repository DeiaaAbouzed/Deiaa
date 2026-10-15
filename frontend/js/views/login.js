import { post } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { icon, logo } from '../lib/icons.js';
import { alertBox, button, field, setBusy } from '../lib/ui.js';

function shell(...content) {
  return h(
    'div',
    { class: 'auth-wrap' },
    h(
      'div',
      { class: 'auth-card' },
      h('div', { class: 'brand' }, logo()),
      h('div', { class: 'auth-title' }, h('h1', {}, 'رُشد'), h('p', {}, 'قارئ الروشتات الذكي - يتعلم من خبرة صيدلياتك')),
      h('div', { class: 'card' }, content),
      h(
        'div',
        { class: 'trust-row' },
        h('span', {}, icon('lock'), 'تشفير AES-256'),
        h('span', {}, icon('shield'), 'تحقق بخطوتين'),
        h('span', {}, icon('activity'), 'سجل أمان غير قابل للتلاعب'),
      ),
    ),
  );
}

export function renderLogin(root, { message = null, onSuccess }) {
  const username = h('input', { class: 'input ltr', name: 'username', autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false', required: true, dir: 'ltr' });
  const password = h('input', { class: 'input', type: 'password', name: 'password', autocomplete: 'current-password', required: true });
  const code = h('input', { class: 'input code', inputmode: 'numeric', pattern: '[0-9]*', maxlength: 6, autocomplete: 'one-time-code', placeholder: '000000' });
  const codeField = field('رمز التحقق من تطبيق المصادقة', code);
  codeField.classList.add('hidden');
  const error = h('div', { class: 'error-text', role: 'alert' });
  const submit = button('تسجيل الدخول', { kind: 'primary block lg', type: 'submit', iconName: 'lock' });

  const form = h(
    'form',
    {
      class: 'stack',
      onSubmit: async (e) => {
        e.preventDefault();
        error.textContent = '';
        setBusy(submit, true, 'جاري التحقق...');
        try {
          const me = await post('/api/auth/login', { username: username.value.trim(), password: password.value, totp: code.value || null });
          onSuccess(me);
        } catch (err) {
          if (err.code === 'mfa_required') {
            codeField.classList.remove('hidden');
            code.focus();
            error.textContent = '';
          } else {
            error.textContent = err.message;
            if (err.code === 'mfa_invalid') {
              code.value = '';
              code.focus();
            } else {
              password.value = '';
              password.focus();
            }
          }
        } finally {
          setBusy(submit, false);
        }
      },
    },
    message ? alertBox('info', message) : null,
    field('اسم المستخدم', username),
    field('كلمة المرور', password),
    codeField,
    error,
    submit,
  );
  mount(root, shell(form));
  username.focus();
}

function passwordStep(me, onDone) {
  const min = me.app.password_min_length || 10;
  const current = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
  const fresh = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true, minlength: min });
  const again = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true });
  const error = h('div', { class: 'error-text', role: 'alert' });
  const submit = button('حفظ كلمة المرور', { kind: 'primary block', type: 'submit', iconName: 'key' });
  return h(
    'form',
    {
      class: 'stack',
      onSubmit: async (e) => {
        e.preventDefault();
        error.textContent = '';
        if (fresh.value !== again.value) {
          error.textContent = 'كلمتا المرور غير متطابقتين';
          return;
        }
        setBusy(submit, true);
        try {
          onDone(await post('/api/auth/password', { current: current.value, new: fresh.value }));
        } catch (err) {
          error.textContent = err.message;
        } finally {
          setBusy(submit, false);
        }
      },
    },
    alertBox('info', 'أهلاً بك! اختر كلمة مرور جديدة', `${min} أحرف على الأقل، وتمزج بين حروف كبيرة وصغيرة وأرقام أو رموز.`, 'key'),
    field('كلمة المرور الحالية (المؤقتة)', current),
    field('كلمة المرور الجديدة', fresh),
    field('تأكيد كلمة المرور', again),
    error,
    submit,
  );
}

function totpStep(me, onDone) {
  const box = h('div', { class: 'stack' });
  const password = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true });
  const error = h('div', { class: 'error-text', role: 'alert' });
  const start = button('عرض رمز QR', { kind: 'primary block', type: 'submit', iconName: 'shield' });
  const intro = h(
    'form',
    {
      class: 'stack',
      onSubmit: async (e) => {
        e.preventDefault();
        setBusy(start, true);
        try {
          const setup = await post('/api/auth/totp/setup', { password: password.value });
          mount(box, scanStep(setup, onDone));
        } catch (err) {
          error.textContent = err.message;
        } finally {
          setBusy(start, false);
        }
      },
    },
    alertBox('warn', 'حساب المدير يحتاج تحقق بخطوتين', 'ثبّت تطبيق Google Authenticator أو Microsoft Authenticator على هاتفك، ثم أكمل الخطوات.', 'shield'),
    field('أكّد كلمة المرور', password),
    error,
    start,
  );
  return mount(box, intro);
}

function scanStep(setup, onDone) {
  const code = h('input', { class: 'input code', inputmode: 'numeric', maxlength: 6, autocomplete: 'one-time-code', placeholder: '000000', required: true });
  const error = h('div', { class: 'error-text', role: 'alert' });
  const submit = button('تفعيل', { kind: 'primary block', type: 'submit', iconName: 'check' });
  return h(
    'form',
    {
      class: 'stack',
      onSubmit: async (e) => {
        e.preventDefault();
        setBusy(submit, true);
        try {
          onDone(await post('/api/auth/totp/enable', { code: code.value }));
        } catch (err) {
          error.textContent = err.message;
          code.value = '';
        } finally {
          setBusy(submit, false);
        }
      },
    },
    h('p', {}, '١) امسح الرمز بتطبيق المصادقة:'),
    h('div', { class: 'qr-box' }, h('img', { src: setup.qr, alt: 'رمز QR للتحقق بخطوتين', width: 196, height: 196 })),
    h('p', { class: 'muted small' }, 'أو أدخل المفتاح يدوياً:'),
    h('div', { class: 'code-sample' }, setup.secret),
    h('p', {}, '٢) اكتب الرمز المكوّن من ٦ أرقام الظاهر في التطبيق:'),
    code,
    error,
    submit,
  );
}

export function renderOnboarding(root, me, onDone) {
  const step = me.flags.must_change_password ? passwordStep(me, onDone) : totpStep(me, onDone);
  mount(root, shell(step));
  const first = root.querySelector('input');
  if (first) first.focus();
}
