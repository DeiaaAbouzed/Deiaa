// One prescription: live reading progress, then the review editor.
import { get, post } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { navigate } from '../lib/router.js';
import { alertBox, button, pageHead, showError, statusBadge } from '../lib/ui.js';
import { prescriptionEditor } from '../components/editor.js';

const PHASES = [
  'قراءة رأس الروشتة والتعرّف على الطبيب...',
  'تحليل خط اليد سطراً بسطر...',
  'مطابقة الأسماء مع قاعدة الأدوية المصرية...',
  'التحقق من التركيزات والجرعات...',
  'فحص التكرار والتداخلات الدوائية...',
];

export function scanningView(uid) {
  const phase = h('span', {}, PHASES[0]);
  const steps = h('div', { class: 'steps' }, PHASES.map((_, i) => h('span', { class: i === 0 ? 'on' : '' })));
  let i = 0;
  const timer = setInterval(() => {
    i = Math.min(PHASES.length - 1, i + 1);
    phase.textContent = PHASES[i];
    [...steps.children].forEach((s, n) => s.classList.toggle('on', n <= i));
  }, 2600);
  const element = h(
    'div',
    { class: 'stack' },
    h('div', { class: 'scan-stage' }, h('img', { src: `/api/prescriptions/${uid}/image`, alt: 'الروشتة قيد القراءة' })),
    h('div', { class: 'scan-status', role: 'status', 'aria-live': 'polite' }, h('strong', {}, 'الذكاء الاصطناعي يقرأ الروشتة'), phase, steps),
  );
  return { element, stop: () => clearInterval(timer) };
}

/**
 * Renders a prescription into `container`; resolves to a cleanup function.
 * `onFinished(action)` lets the review queue move on to the next one.
 */
export async function renderPrescription(container, uid, { onFinished = null, reviewInfo = null } = {}) {
  let disposed = false;
  let pollTimer = null;
  let scan = null;
  let editor = null;

  const finish = (outcome) => {
    if (onFinished) onFinished(outcome);
    else if (outcome.action === 'deleted') navigate('history');
    else show();
  };

  async function show() {
    if (disposed) return;
    let detail;
    try {
      detail = await get(`/api/prescriptions/${uid}`);
    } catch (error) {
      mount(container, alertBox('bad', 'تعذر فتح الروشتة', error.message));
      return;
    }
    if (disposed) return;
    if (['queued', 'processing'].includes(detail.status)) {
      if (!scan) {
        scan = scanningView(uid);
        mount(container, pageHead('جاري القراءة', 'عادة تستغرق بين ١٠ و٤٠ ثانية'), scan.element);
      }
      pollTimer = setTimeout(show, 1500);
      return;
    }
    if (scan) {
      scan.stop();
      scan = null;
    }
    if (editor) editor.destroy();
    if (detail.status === 'failed') {
      mount(
        container,
        pageHead('تعذرت القراءة', null, statusBadge('failed')),
        alertBox('bad', detail.error || 'حدث خطأ أثناء القراءة'),
        h(
          'div',
          { class: 'row', style: { 'margin-top': '14px' } },
          button('إعادة المحاولة', {
            kind: 'primary',
            iconName: 'refresh',
            onClick: async () => {
              try {
                await post(`/api/prescriptions/${uid}/retry`);
                show();
              } catch (error) {
                showError(error);
              }
            },
          }),
          detail.can_verify
            ? button('إدخال يدوي', {
                iconName: 'pencil',
                onClick: () => {
                  editor = prescriptionEditor(detail, { onDone: finish, reviewInfo });
                  mount(container, pageHead('إدخال يدوي', 'اكتب الأدوية من الصورة - ستحصل على الملصقات العربية وتنبيهات الأمان كالمعتاد'), editor.element);
                },
              })
            : null,
          button('قراءة روشتة أخرى', { iconName: 'camera', onClick: () => navigate('read') }),
        ),
      );
      return;
    }
    editor = prescriptionEditor(detail, { onDone: finish, reviewInfo });
    const title = detail.status === 'verified' ? 'روشتة معتمدة' : detail.status === 'rejected' ? 'روشتة مرفوضة' : 'راجع القراءة واعتمدها';
    const subtitle = detail.status === 'needs_review' ? 'السطور الخضراء واضحة، والصفراء والحمراء تحتاج نظرتك. اضغط Ctrl+Enter للاعتماد.' : null;
    mount(container, pageHead(title, subtitle, statusBadge(detail.status)), editor.element);
  }

  await show();
  return () => {
    disposed = true;
    clearTimeout(pollTimer);
    if (scan) scan.stop();
    if (editor) editor.destroy();
  };
}

export default async function rxView(root, params) {
  const container = h('div', {});
  root.append(container);
  return renderPrescription(container, params.uid, {
    onFinished: (outcome) => {
      if (outcome.action === 'deleted') navigate('history');
      else navigate(`rx/${params.uid}`); // show the verified / re-read state in place
    },
  });
}
