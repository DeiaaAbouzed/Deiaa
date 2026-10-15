import { get, put } from '../lib/api.js';
import { h, ltr } from '../lib/dom.js';
import { EFFORTS, ENGINE_MODES } from '../lib/labels.js';
import { alertBox, badge, button, field, fmtUsd, pageHead, setBusy, showError, toast } from '../lib/ui.js';

export default async function settingsView(root) {
  const data = await get('/api/settings');
  const v = data.values;
  const s = data.status;

  const mode = h('select', { class: 'select' }, data.options.engine_modes.map((m) => h('option', { value: m, selected: m === v.engine_mode }, ENGINE_MODES[m]?.label || m)));
  const modeHint = h('p', { class: 'small muted' }, ENGINE_MODES[v.engine_mode]?.hint || '');
  mode.addEventListener('change', () => { modeHint.textContent = ENGINE_MODES[mode.value]?.hint || ''; });
  const cloud = h('input', { type: 'checkbox', checked: v.cloud_enabled });
  const model = h('select', { class: 'select ltr', dir: 'ltr' }, data.options.models.map((m) => h('option', { value: m, selected: m === v.ai_model }, m)));
  const effort = h('select', { class: 'select' }, data.options.efforts.map((e) => h('option', { value: e, selected: e === v.ai_effort }, EFFORTS[e] || e)));
  const secondPass = h('input', { type: 'checkbox', checked: v.second_pass });
  const threshold = h('input', { class: 'input', type: 'number', min: 0, max: 1, step: 0.05, value: v.second_pass_threshold });
  const localThreshold = h('input', { class: 'input', type: 'number', min: 0, max: 1, step: 0.05, value: v.local_confidence_threshold });
  const budget = h('input', { class: 'input', type: 'number', min: 0, step: 1, value: v.monthly_budget_usd });
  const quota = h('input', { class: 'input', type: 'number', min: 1, step: 1, value: v.reads_per_user_per_day });
  const pharmacy = h('input', { class: 'input', value: v.pharmacy_name, placeholder: 'صيدليات ...' });
  const footer = h('input', { class: 'input', value: v.label_footer });
  const academy = h('input', { type: 'checkbox', checked: v.academy_enabled });

  const save = button('حفظ الإعدادات', { kind: 'primary', iconName: 'check' });
  save.addEventListener('click', async () => {
    setBusy(save, true);
    try {
      await put('/api/settings', {
        changes: {
          engine_mode: mode.value,
          cloud_enabled: cloud.checked,
          ai_model: model.value,
          ai_effort: effort.value,
          second_pass: secondPass.checked,
          second_pass_threshold: Number(threshold.value),
          local_confidence_threshold: Number(localThreshold.value),
          monthly_budget_usd: Number(budget.value),
          reads_per_user_per_day: Number(quota.value),
          pharmacy_name: pharmacy.value,
          label_footer: footer.value,
          academy_enabled: academy.checked,
        },
      });
      toast('تم حفظ الإعدادات');
    } catch (error) {
      showError(error);
    } finally {
      setBusy(save, false);
    }
  });

  root.append(
    pageHead('الإعدادات', 'تحكم في محرك القراءة والتكلفة والخصوصية', save),
    h(
      'div',
      { class: 'grid-2' },
      h(
        'div',
        { class: 'card stack' },
        h('h2', {}, 'محرك القراءة'),
        field('وضع القراءة', mode),
        modeHint,
        h('label', { class: 'check' }, cloud, 'السماح بالقراءة السحابية'),
        field('نموذج الذكاء الاصطناعي', model, 'Opus 5.5 الأدق، Sonnet 5.5 نصف التكلفة'),
        field('مستوى التدقيق', effort),
        h('label', { class: 'check' }, secondPass, 'قراءة ثانية بأمثلة خط الطبيب عند الشك'),
        field('حد الشك للقراءة الثانية', threshold, 'من ٠ إلى ١'),
        field('حد ثقة النموذج المحلي قبل استشارة السحابة', localThreshold),
      ),
      h(
        'div',
        { class: 'stack' },
        h(
          'div',
          { class: 'card stack' },
          h('h2', {}, 'التكلفة والاستخدام'),
          field('الحد الشهري للتكلفة السحابية (دولار)', budget, '٠ = بدون حد'),
          h('p', { class: 'small muted' }, `المستهلك هذا الشهر: ${fmtUsd(s.month_spend_usd)}`),
          field('الحد اليومي للقراءات لكل مستخدم', quota),
        ),
        h(
          'div',
          { class: 'card stack' },
          h('h2', {}, 'الصيدلية والملصقات'),
          field('اسم الصيدلية (يظهر على الملصق)', pharmacy),
          field('سطر أسفل الملصق', footer),
          h('label', { class: 'check' }, academy, 'تفعيل أكاديمية تدريب الصيادلة'),
        ),
        h(
          'div',
          { class: 'card stack' },
          h('h2', {}, 'حالة الأمان'),
          h('div', { class: 'row' }, s.cloud_key_configured ? badge('مفتاح الخدمة السحابية مُعد', 'good', 'check') : badge('مفتاح الخدمة السحابية غير مُعد', 'warn', 'alert')),
          h('div', { class: 'row' }, s.cookie_secure ? badge('اتصال HTTPS مُفعّل', 'good', 'lock') : badge('الكوكيز بدون HTTPS - للتجربة فقط', 'bad', 'alert')),
          h('div', { class: 'row' }, s.require_2fa_for_admins ? badge('التحقق بخطوتين إلزامي للمديرين', 'good', 'shield') : badge('التحقق بخطوتين غير إلزامي', 'warn')),
          h('div', { class: 'small' }, 'بصمة مفتاح التشفير: ', ltr(s.key_fingerprint)),
          alertBox('info', 'مفاتيح التشفير وواجهة Claude لا تُعدّل من هنا', 'تُضبط فقط على الخادم (ملفات الأسرار ومتغيرات البيئة) حتى لا يمكن سرقتها من المتصفح.', 'lock'),
        ),
      ),
    ),
  );
}
