// Training center: is the AI getting better, what has it learned, and the pharmacy's own model.
import { download, get, post } from '../lib/api.js';
import { append, h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { ENGINE_MODES } from '../lib/labels.js';
import { navigate } from '../lib/router.js';
import { ADMIN, hasRole } from '../lib/state.js';
import { alertBox, badge, button, empty, field, fmtDateTime, fmtNum, fmtPct, fmtUsd, pageHead, progressBar, showError, stepUp, toast } from '../lib/ui.js';
import { learningCurve } from '../components/chart.js';

function kpi(label, value, delta = null) {
  return h('div', { class: 'kpi' }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, value), delta);
}

function delta(text, direction) {
  return h('div', { class: `delta ${direction}` }, direction === 'up' ? icon('arrowUp') : direction === 'down' ? icon('arrowDown') : null, text);
}

const JOB_STATUS = {
  queued: ['في الانتظار', ''],
  running: ['قيد التدريب', 'info'],
  cancelling: ['جاري الإيقاف', 'warn'],
  done: ['اكتمل', 'good'],
  failed: ['فشل', 'bad'],
  cancelled: ['أُوقف', ''],
};

export default async function trainingView(root) {
  const data = await get('/api/training/overview');
  const admin = hasRole(ADMIN);
  let pollTimer = null;

  // ---------- KPIs ----------
  const acc = data.accuracy;
  let accDelta = null;
  if (acc.last_30d !== null && acc.previous_30d !== null) {
    const points = (acc.last_30d - acc.previous_30d) * 100;
    const dir = points > 0.05 ? 'up' : points < -0.05 ? 'down' : '';
    accDelta = delta(`${points >= 0 ? '+' : ''}${new Intl.NumberFormat('ar-EG', { maximumFractionDigits: 1 }).format(points)} نقطة عن الشهر السابق`, dir);
  } else if (acc.last_30d !== null) {
    accDelta = delta(`على ${fmtNum(acc.n_30d)} روشتة`, '');
  }
  const c = data.counts;
  const kpis = h(
    'div',
    { class: 'kpis' },
    kpi('دقة قراءة أسماء الأدوية (٣٠ يوماً)', fmtPct(acc.last_30d), accDelta),
    kpi('روشتات جاهزة للتدريب', fmtNum(c.training_ready), delta(`+${fmtNum(c.verified_7d)} هذا الأسبوع`, c.verified_7d ? 'up' : '')),
    kpi('أطباء تعلّم خطهم', fmtNum(data.learning.doctors_known)),
    kpi('تصحيحات يتذكرها', fmtNum(data.learning.corrections)),
    kpi('تنتظر المراجعة', fmtNum(c.needs_review), c.needs_review ? h('a', { class: 'delta', href: '#/review' }, 'ابدأ المراجعة') : null),
    kpi('تكلفة القراءة السحابية هذا الشهر', fmtUsd(data.cost.month_usd), delta(data.cost.avg_per_read ? `متوسط ${fmtUsd(data.cost.avg_per_read)} للروشتة` : `${fmtNum(data.cost.reads_month)} قراءة`, '')),
  );

  // ---------- doctors ----------
  const doctors = data.doctors.length
    ? h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'table' },
          h('thead', {}, h('tr', {}, h('th', {}, 'الطبيب'), h('th', {}, 'التخصص'), h('th', { class: 'num' }, 'روشتات معتمدة'), h('th', { class: 'num' }, 'دقة القراءة'))),
          h('tbody', {}, data.doctors.map((d) => h('tr', {}, h('td', {}, d.name), h('td', {}, d.specialty || '—'), h('td', { class: 'num' }, fmtNum(d.verified)), h('td', { class: 'num' }, fmtPct(d.accuracy))))),
        ),
      )
    : empty('لم يتعلم النظام خط أي طبيب بعد', 'doctor');

  // ---------- local model ----------
  const localBox = h('div', { class: 'stack' });
  const engine = data.engine;
  const mode = ENGINE_MODES[engine.mode] || { label: engine.mode, hint: '' };

  async function renderLocal() {
    clearTimeout(pollTimer);
    const [jobs, models, readiness] = await Promise.all([
      get('/api/training/jobs'),
      get('/api/training/models'),
      admin ? get('/api/training/readiness') : Promise.resolve(null),
    ]);
    const running = jobs.find((j) => ['queued', 'running', 'cancelling'].includes(j.status));
    const latest = jobs[0];
    const parts = [];

    if (readiness) {
      const ok = readiness.ready;
      const enough = readiness.samples >= readiness.min_samples;
      parts.push(
        h(
          'div',
          { class: 'grid-2' },
          h(
            'div',
            { class: 'card flat stack' },
            h('strong', {}, 'جاهزية الخادم للتدريب'),
            ok ? badge('مكتبات التدريب مثبتة', 'good', 'check') : badge('مكتبات التدريب غير مثبتة', 'warn', 'alert'),
            h('span', { class: 'small' }, readiness.cuda ? `كارت شاشة: ${readiness.gpu} (${fmtNum(readiness.gpu_memory_gb)} GB)` : 'لا يوجد كارت شاشة (GPU) - التدريب على المعالج بطيء جداً'),
            h('span', { class: 'small muted ltr' }, readiness.base_model),
          ),
          h(
            'div',
            { class: 'card flat stack' },
            h('strong', {}, 'بيانات التدريب'),
            h('span', {}, `${fmtNum(readiness.samples)} روشتة معتمدة (الحد الأدنى ${fmtNum(readiness.min_samples)}، والأفضل +٥٠٠)`),
            progressBar(Math.min(1, readiness.samples / 500)),
            enough ? null : h('span', { class: 'small muted' }, 'استمر في المراجعة والتغذية لتصل للحد الأدنى.'),
          ),
        ),
      );
      if (!running) {
        const startBtn = button('بدء تدريب نموذج جديد', { kind: 'primary', iconName: 'cpu', disabled: !ok || !enough });
        startBtn.addEventListener('click', async () => {
          const epochs = h('input', { class: 'input', type: 'number', min: 1, max: 20, value: 3 });
          const confirm = await stepUp('بدء تدريب النموذج المحلي', {
            totp: true,
            extra: { node: field('عدد دورات التدريب (Epochs)', epochs, '٣ مناسبة كبداية'), read: () => Number(epochs.value) || 3 },
          });
          if (!confirm) return;
          try {
            await post('/api/training/jobs', { password: confirm.password, totp: confirm.totp, epochs: confirm.extra });
            toast('بدأ التدريب - يمكنك متابعة التقدم هنا');
            renderLocal();
          } catch (error) {
            showError(error);
          }
        });
        parts.push(h('div', { class: 'row' }, startBtn, ok ? null : h('span', { class: 'small muted' }, 'راجع دليل التدريب لتثبيت المكتبات على خادم به GPU.')));
      }
    }

    if (latest) {
      const [label, kind] = JOB_STATUS[latest.status] || [latest.status, ''];
      parts.push(
        h(
          'div',
          { class: 'card flat stack' },
          h('div', { class: 'row between' }, h('strong', {}, `آخر تدريب #${fmtNum(latest.id)}`), badge(label, kind)),
          ['queued', 'running', 'cancelling'].includes(latest.status) ? progressBar(latest.progress) : null,
          h('span', { class: 'small' }, latest.message || ''),
          h('span', { class: 'small muted' }, `بدأ ${fmtDateTime(latest.started_at || latest.created_at)}${latest.finished_at ? ` · انتهى ${fmtDateTime(latest.finished_at)}` : ''}`),
          admin && running
            ? h('div', {}, button('إيقاف التدريب', { size: 'sm', kind: 'danger', iconName: 'x', onClick: async () => { await post(`/api/training/jobs/${running.id}/cancel`); renderLocal(); } }))
            : null,
        ),
      );
    }

    if (models.length) {
      parts.push(
        h(
          'div',
          { class: 'table-wrap' },
          h(
            'table',
            { class: 'table' },
            h('thead', {}, h('tr', {}, h('th', {}, 'النموذج'), h('th', { class: 'num' }, 'دقته'), h('th', { class: 'num' }, 'دقة السحابة على نفس الروشتات'), h('th', { class: 'num' }, 'تدرّب على'), h('th', {}, ''))),
            h(
              'tbody',
              {},
              models.map((m) =>
                h(
                  'tr',
                  {},
                  h('td', {}, h('div', { class: 'ltr' }, m.name), h('div', { class: 'small muted' }, fmtDateTime(m.created_at))),
                  h('td', { class: 'num' }, fmtPct(m.metrics.acc_drug)),
                  h('td', { class: 'num' }, fmtPct(m.metrics.cloud_acc_drug)),
                  h('td', { class: 'num' }, fmtNum(m.train_count)),
                  h(
                    'td',
                    {},
                    m.is_active
                      ? badge('مُفعَّل', 'good', 'check')
                      : admin
                        ? button('تفعيل', {
                            size: 'sm',
                            onClick: async () => {
                              const confirm = await stepUp(`تفعيل ${m.name}`, { totp: true });
                              if (!confirm) return;
                              try {
                                await post(`/api/training/models/${m.id}/activate`, confirm);
                                toast('تم تفعيل النموذج - اختر وضع القراءة من الإعدادات');
                                renderLocal();
                              } catch (error) {
                                showError(error);
                              }
                            },
                          })
                        : null,
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    } else {
      parts.push(h('p', { class: 'muted small' }, 'لم يتم تدريب أي نموذج محلي بعد.'));
    }
    mount(localBox, parts);
    if (running) pollTimer = setTimeout(renderLocal, 3000);
  }

  // ---------- export ----------
  const exportCard = admin
    ? h(
        'div',
        { class: 'card' },
        h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'تصدير بيانات التدريب'), h('p', {}, 'لتدريب النموذج على جهاز GPU خارجي - ملف مشفر بكلمة مرور، بدون بيانات المرضى المكتوبة'))),
        button('تصدير مشفّر', {
          iconName: 'download',
          onClick: async () => {
            const pass = h('input', { class: 'input', type: 'password', minlength: 12, autocomplete: 'new-password' });
            const confirm = await stepUp('تصدير بيانات التدريب', {
              totp: true,
              extra: { node: field('كلمة مرور ملف التصدير', pass, '١٢ حرفاً على الأقل - احفظها بأمان'), read: () => pass.value },
            });
            if (!confirm) return;
            try {
              await download('POST', '/api/training/export', { json: { password: confirm.password, totp: confirm.totp, export_password: confirm.extra } });
              toast('تم التصدير - يُفك بالأمر: python -m rushd decrypt-export');
            } catch (error) {
              showError(error);
            }
          },
        }),
      )
    : null;

  append(root, [
    pageHead('مركز التدريب', 'كيف يتعلم رُشد من صيدلياتك أسبوعاً بعد أسبوع', button('تغذية النظام', { iconName: 'layers', onClick: () => navigate('feed') })),
    kpis,
    h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'منحنى التعلّم'), h('p', {}, 'نسبة أسماء الأدوية التي قرأها الذكاء الاصطناعي صحيحة قبل مراجعة الصيدلي'))), learningCurve(data.curve)),
    h(
      'div',
      { class: 'grid-2', style: { 'margin-top': '16px' } },
      h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', {}, 'الأطباء الذين تعلّم خطهم')), doctors),
      h(
        'div',
        { class: 'card stack' },
        h('div', { class: 'card-head' }, h('h2', {}, 'محرك القراءة الحالي')),
        h('div', { class: 'row' }, badge(mode.label, 'info', engine.mode === 'cloud' ? 'cloud' : 'cpu'), engine.cloud_ready ? badge('السحابة جاهزة', 'good') : badge('السحابة غير مهيأة', 'warn')),
        h('p', { class: 'small muted' }, mode.hint),
        h('div', { class: 'small' }, 'النموذج: ', h('span', { class: 'ltr' }, engine.model), ` · مستوى التدقيق: ${engine.effort}`),
        engine.local_model ? alertBox('good', `النموذج المحلي المفعّل: ${engine.local_model.name}`, `دقته ${fmtPct(engine.local_model.metrics.acc_drug)}`, 'cpu') : null,
        engine.shadow_n ? h('div', { class: 'small' }, `القياس الخفي للنموذج المحلي: ${fmtPct(engine.shadow_accuracy)} على ${fmtNum(engine.shadow_n)} روشتة`) : null,
        h('div', { class: 'small muted' }, `قاعدة الأدوية: ${fmtNum(data.learning.drugs)} صنف (منها ${fmtNum(data.learning.drugs_learned)} تعلّمها من المراجعات)`),
      ),
    ),
    h(
      'div',
      { class: 'card' },
      h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'نموذجك الخاص (يعمل بدون إنترنت)'), h('p', {}, 'درّب نموذجاً على روشتاتك المعتمدة؛ يُحفظ مشفراً ولا يعمل إلا على خادمك'))),
      localBox,
    ),
    exportCard,
  ]);
  await renderLocal();
  return () => clearTimeout(pollTimer);
}
