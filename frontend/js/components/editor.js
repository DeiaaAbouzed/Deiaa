// The review screen: photo on one side, the AI reading as editable cards on the other.
// Verifying is the moment the system learns, so this is built for speed:
// confident lines need no action, doubtful ones are highlighted with alternatives.
import { del, get, post } from '../lib/api.js';
import { h, ltr, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { FLAGS, FORMS, FREQUENCIES, TIMINGS, WARNING_LEVELS } from '../lib/labels.js';
import { instructions } from '../lib/sig.js';
import { ADMIN, MANAGERS, hasRole, state as appState } from '../lib/state.js';
import { alertBox, badge, button, confirmDialog, field, fmtPct, levelBadge, modal, setBusy, showError, toast } from '../lib/ui.js';
import { printLabels } from './labels-print.js';
import { suggestInput } from './suggest.js';
import { imageViewer } from './viewer.js';

const SIG_KEYS = ['dose_amount', 'dose_unit', 'times_per_day', 'interval_hours', 'timing', 'duration_days', 'route', 'prn', 'stat'];

function normalizeItem(item, aiIndex) {
  return {
    brand: item.brand || item.read_name || '',
    drug_id: item.drug_id || null,
    generic: item.generic || '',
    drug_class: item.drug_class || '',
    strength: item.strength || '',
    form: item.form || '',
    quantity: item.quantity || '',
    sig_text: item.sig_text || '',
    line_text: item.line_text || '',
    sig: Object.fromEntries(SIG_KEYS.map((k) => [k, item.sig ? item.sig[k] ?? null : null])),
    instructions_ar: item.instructions_ar || '',
    level: item.level || 'high',
    confidence: item.confidence ?? null,
    candidates: item.candidates || [],
    flags: item.flags || [],
    read_name: item.read_name || '',
    illegible: item.illegible || '',
    ai_index: aiIndex,
    edited: false,
  };
}

function liveInstructions(item) {
  return item.edited || !item.instructions_ar ? instructions(item.sig, item.form) : item.instructions_ar;
}

function select(options, value, onChange, label) {
  const el = h('select', { class: 'select', 'aria-label': label, onChange: (e) => onChange(e.target.value) });
  for (const [v, text] of options) el.append(h('option', { value: v, selected: String(value ?? '') === String(v) }, text));
  return el;
}

export function prescriptionEditor(detail, { onDone, reviewInfo = null }) {
  const canEdit = Boolean(detail.can_verify);
  const source = detail.verified_result || detail.ai_result || { items: [] };
  const fromVerified = Boolean(detail.verified_result);
  const st = {
    items: (source.items || []).map((item, i) => normalizeItem(item, fromVerified ? item.ai_index ?? null : i)),
    doctor: {
      id: (detail.doctor && detail.doctor.id) || (source.doctor_match && source.doctor_match.id) || null,
      name: (detail.doctor && detail.doctor.name) || (source.doctor && source.doctor.name) || '',
      specialty: (source.doctor && source.doctor.specialty) || '',
    },
    patient: { name: (source.patient && source.patient.name) || '', age: (source.patient && source.patient.age) || '' },
    notes: fromVerified ? source.notes || '' : '',
    use_for_training: detail.use_for_training !== false,
    academy_approved: Boolean(detail.academy_approved),
  };

  const itemsBox = h('div', { class: 'stack' });
  const viewer = imageViewer(`/api/prescriptions/${detail.uid}/image`);

  // ---------- item cards ----------
  function renderItems() {
    mount(
      itemsBox,
      st.items.length ? st.items.map((item, i) => itemCard(item, i)) : alertBox('warn', 'لا توجد أدوية في القراءة', 'أضف الأدوية يدوياً أو ارفض الروشتة إن لم تكن صالحة.'),
      canEdit ? button('إضافة دواء', { iconName: 'plus', onClick: addItem }) : null,
    );
  }

  function addItem() {
    const item = normalizeItem({ level: 'high' }, null);
    item.edited = true;
    item._editing = true;
    st.items.push(item);
    renderItems();
    const inputs = itemsBox.querySelectorAll('.rx-item');
    const last = inputs[inputs.length - 1];
    if (last) last.querySelector('input')?.focus();
  }

  function itemCard(item, index) {
    const card = h('article', { class: `rx-item ${item.level}`, 'aria-label': `الدواء ${index + 1}` });
    const render = () => {
      const chips = [
        item.strength ? badge(ltr(item.strength), 'info') : null,
        item.form ? badge(FORMS[item.form] || item.form) : null,
        item.quantity ? badge(`الكمية: ${item.quantity}`) : null,
      ];
      // Only plausible look-alikes: a weak fuzzy match is noise, not help.
      const floor = item.level === 'low' ? 60 : 78;
      const alternatives = item.candidates.filter((c) => c.drug_id !== item.drug_id && c.score >= floor).slice(0, 3);
      mount(
        card,
        h(
          'div',
          { class: 'rx-top' },
          h('span', { class: 'rx-index' }, String(index + 1)),
          h('div', { class: 'grow' }, h('div', { class: 'rx-name' }, item.brand || '—'), item.generic ? h('div', { class: 'rx-generic' }, item.generic) : null),
          item.edited ? badge('عدّلها الصيدلي', 'info', 'pencil') : levelBadge(item.level),
        ),
        h('div', { class: 'rx-meta' }, chips, item.flags.filter((f) => FLAGS[f]).map((f) => badge(FLAGS[f], f === 'learned_correction' || f === 'new_drug' ? 'good' : 'warn'))),
        item.line_text ? h('div', { class: 'rx-written' }, 'مكتوب في الروشتة: ', ltr(item.line_text)) : null,
        item.illegible ? h('div', { class: 'small muted' }, `جزء غير مقروء: ${item.illegible}`) : null,
        liveInstructions(item) ? h('div', { class: 'rx-instructions' }, icon('tag'), h('span', {}, liveInstructions(item))) : null,
        canEdit && alternatives.length && !item.edited
          ? h(
              'div',
              { class: 'rx-alts' },
              h('span', { class: 'muted' }, 'ربما تقصد:'),
              alternatives.map((c) =>
                h('button', { type: 'button', class: 'chip', onClick: () => replaceDrug(item, c) }, ltr(c.brand)),
              ),
            )
          : null,
        canEdit
          ? h(
              'div',
              { class: 'row', style: { 'margin-top': '10px' } },
              button(item._editing ? 'إغلاق التعديل' : 'تعديل', { size: 'sm', iconName: 'pencil', onClick: () => { item._editing = !item._editing; render(); } }),
              button('حذف', { size: 'sm', kind: 'ghost', iconName: 'trash', onClick: () => { st.items.splice(index, 1); renderItems(); } }),
            )
          : null,
        item._editing ? editForm(item, render) : null,
      );
    };
    render();
    return card;
  }

  function replaceDrug(item, candidate) {
    item.brand = candidate.brand;
    item.drug_id = candidate.drug_id;
    item.generic = candidate.generic;
    item.drug_class = candidate.drug_class;
    item.flags = item.flags.filter((f) => f !== 'not_in_database' && f !== 'ambiguous_name');
    item.edited = true;
    item.level = 'high';
    renderItems();
  }

  function editForm(item, rerender) {
    const preview = h('div', { class: 'rx-instructions' }, icon('tag'), h('span', {}, liveInstructions(item) || '—'));
    const touch = () => {
      item.edited = true;
      preview.lastChild.textContent = liveInstructions(item) || '—';
    };
    const brand = h('input', { class: 'input ltr', dir: 'ltr', value: item.brand, 'aria-label': 'اسم الدواء', placeholder: 'Augmentin' });
    brand.addEventListener('input', () => {
      item.brand = brand.value;
      item.drug_id = null;
      item.generic = '';
      touch();
    });
    const brandField = suggestInput(brand, {
      fetcher: (q) => get('/api/drugs/suggest', { q, doctor_id: st.doctor.id }),
      render: (d) => [ltr(d.brand), h('span', { class: 'gen' }, d.generic)],
      onPick: (d) => {
        item.brand = d.brand;
        item.drug_id = d.drug_id;
        item.generic = d.generic;
        item.drug_class = d.drug_class;
        brand.value = d.brand;
        strengths.replaceChildren(...(d.strengths || []).map((s) => h('option', { value: s })));
        touch();
      },
    });
    const listId = `str-${Math.random().toString(36).slice(2)}`;
    const strengths = h('datalist', { id: listId });
    const strength = h('input', { class: 'input ltr', dir: 'ltr', value: item.strength, list: listId, 'aria-label': 'التركيز' });
    strength.addEventListener('input', () => { item.strength = strength.value; touch(); });
    const form = select([['', '—'], ...Object.entries(FORMS)], item.form, (v) => { item.form = v; touch(); }, 'الشكل الدوائي');
    const sigText = h('input', { class: 'input ltr', dir: 'ltr', value: item.sig_text, placeholder: '1x3 p.c. 5 days', 'aria-label': 'الجرعة كما كُتبت' });
    sigText.addEventListener('input', () => { item.sig_text = sigText.value; touch(); });
    const amount = h('input', { class: 'input', type: 'number', min: 0, step: 0.25, value: item.sig.dose_amount ?? '', 'aria-label': 'كمية الجرعة' });
    amount.addEventListener('input', () => { item.sig.dose_amount = amount.value === '' ? null : Number(amount.value); touch(); });
    const freq = select(FREQUENCIES, item.sig.times_per_day ?? '', (v) => { item.sig.times_per_day = v === '' ? null : Number(v); item.sig.interval_hours = null; touch(); }, 'عدد المرات');
    const timing = select([['', '—'], ...Object.entries(TIMINGS)], item.sig.timing, (v) => { item.sig.timing = v || null; touch(); }, 'التوقيت');
    const duration = h('input', { class: 'input', type: 'number', min: 0, step: 1, value: item.sig.duration_days ?? '', 'aria-label': 'المدة بالأيام' });
    duration.addEventListener('input', () => { item.sig.duration_days = duration.value === '' ? null : Number(duration.value); touch(); });
    const prn = h('input', { type: 'checkbox', checked: item.sig.prn });
    prn.addEventListener('change', () => { item.sig.prn = prn.checked; touch(); });
    return h(
      'div',
      { class: 'rx-edit stack' },
      h('div', { class: 'form-grid' }, field('اسم الدواء', brandField), field('التركيز', h('div', {}, strength, strengths)), field('الشكل', form)),
      field('الجرعة كما كُتبت', sigText),
      h('div', { class: 'form-grid' }, field('كمية الجرعة', amount), field('عدد المرات', freq), field('التوقيت', timing), field('المدة (أيام)', duration)),
      h('label', { class: 'check' }, prn, 'عند اللزوم فقط'),
      preview,
      h('div', { class: 'row' }, button('تم', { kind: 'primary', size: 'sm', iconName: 'check', onClick: () => { item._editing = false; item.level = 'high'; rerender(); } })),
    );
  }

  // ---------- doctor & patient ----------
  const doctorInput = h('input', { class: 'input', value: st.doctor.name, placeholder: 'اسم الطبيب كما في الروشتة', 'aria-label': 'الطبيب' });
  const doctorHint = h('span', { class: 'small muted' });
  const updateDoctorHint = () => {
    doctorHint.textContent = st.doctor.id ? '✓ طبيب معروف - النظام يتعلم خطه' : st.doctor.name ? 'سيتم إنشاء ملف جديد لهذا الطبيب' : '';
  };
  doctorInput.addEventListener('input', () => {
    st.doctor.name = doctorInput.value;
    st.doctor.id = null;
    updateDoctorHint();
  });
  const doctorField = suggestInput(doctorInput, {
    fetcher: (q) => get('/api/doctors', { q, limit: 8 }),
    render: (d) => [h('span', {}, d.name), h('span', { class: 'gen' }, d.specialty || '')],
    onPick: (d) => {
      st.doctor = { id: d.id, name: d.name, specialty: d.specialty };
      doctorInput.value = d.name;
      updateDoctorHint();
    },
  });
  updateDoctorHint();
  const patientName = h('input', { class: 'input', value: st.patient.name, autocomplete: 'off', 'aria-label': 'اسم المريض' });
  patientName.addEventListener('input', () => { st.patient.name = patientName.value; });
  const patientAge = h('input', { class: 'input', value: st.patient.age, autocomplete: 'off', 'aria-label': 'السن' });
  patientAge.addEventListener('input', () => { st.patient.age = patientAge.value; });
  const notes = h('textarea', { class: 'textarea', value: st.notes, placeholder: 'ملاحظات الصيدلي (اختياري)' });
  notes.addEventListener('input', () => { st.notes = notes.value; });
  const training = h('input', { type: 'checkbox', checked: st.use_for_training });
  training.addEventListener('change', () => { st.use_for_training = training.checked; });
  const academy = h('input', { type: 'checkbox', checked: st.academy_approved });
  academy.addEventListener('change', () => { st.academy_approved = academy.checked; });

  // ---------- actions ----------
  const verifyBtn = button(fromVerified ? 'حفظ التعديلات' : 'اعتماد الروشتة', { kind: 'primary', iconName: 'check' });
  async function verify() {
    if (!st.items.length) return toast('أضف دواءً واحداً على الأقل', 'bad');
    if (st.items.some((i) => !i.brand.trim())) return toast('يوجد دواء بدون اسم', 'bad');
    setBusy(verifyBtn, true, 'جاري الحفظ...');
    try {
      const payload = {
        items: st.items.map((i) => ({
          brand: i.brand.trim(),
          drug_id: i.drug_id,
          strength: i.strength,
          form: i.form || null,
          quantity: i.quantity,
          sig_text: i.sig_text,
          line_text: i.line_text,
          ai_index: i.ai_index,
          ...Object.fromEntries(SIG_KEYS.map((k) => [k, i.sig[k] === '' ? null : i.sig[k]])),
          prn: Boolean(i.sig.prn),
          stat: Boolean(i.sig.stat),
        })),
        doctor: st.doctor.id ? { id: st.doctor.id } : st.doctor.name.trim() ? { name: st.doctor.name.trim(), specialty: st.doctor.specialty || '' } : null,
        patient: { name: st.patient.name, age: st.patient.age },
        notes: st.notes,
        use_for_training: st.use_for_training,
        academy_approved: st.academy_approved,
        add_unknown_drugs: true,
      };
      const result = await post(`/api/prescriptions/${detail.uid}/verify`, payload);
      const acc = result.acc_drug;
      toast(acc !== null && acc !== undefined ? `تم الاعتماد وتعلّم النظام منها ✓ (دقة القراءة الآلية ${fmtPct(acc)})` : 'تم الاعتماد ✓');
      onDone({ action: 'verified', result });
    } catch (error) {
      showError(error);
    } finally {
      setBusy(verifyBtn, false);
    }
  }
  verifyBtn.addEventListener('click', verify);

  async function reject() {
    const reason = h('select', { class: 'select' }, ['ليست روشتة', 'غير مقروءة إطلاقاً', 'صورة مكررة', 'أخرى'].map((r) => h('option', { value: r }, r)));
    modal({
      title: 'رفض الروشتة',
      body: h('div', { class: 'stack' }, h('p', {}, 'لن تُستخدم الروشتة المرفوضة في التدريب.'), field('السبب', reason)),
      actions: [
        { label: 'إلغاء', onClick: (close) => close() },
        {
          label: 'رفض',
          kind: 'danger',
          onClick: async (close) => {
            try {
              await post(`/api/prescriptions/${detail.uid}/reject`, { reason: reason.value });
              close();
              toast('تم رفض الروشتة');
              onDone({ action: 'rejected' });
            } catch (error) {
              showError(error);
            }
          },
        },
      ],
    });
  }

  async function reread() {
    if (!(await confirmDialog('ستتم قراءة الروشتة من جديد (قد يحتسب ذلك تكلفة إضافية). متابعة؟'))) return;
    try {
      await post(`/api/prescriptions/${detail.uid}/retry`);
      onDone({ action: 'reread' });
    } catch (error) {
      showError(error);
    }
  }

  async function remove() {
    if (!(await confirmDialog('سيتم حذف الروشتة وصورتها نهائياً. هل أنت متأكد؟', { danger: true, confirm: 'حذف نهائي' }))) return;
    try {
      await del(`/api/prescriptions/${detail.uid}`);
      toast('تم الحذف');
      onDone({ action: 'deleted' });
    } catch (error) {
      showError(error);
    }
  }

  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canEdit) {
      e.preventDefault();
      verify();
    }
  };
  document.addEventListener('keydown', onKey);

  // ---------- layout ----------
  const result = detail.ai_result || {};
  const overall = result.overall_confidence;
  const overallLevel = overall >= 0.85 ? 'high' : overall >= 0.6 ? 'medium' : 'low';
  const meterFill = h('span', { class: overallLevel });
  meterFill.style.setProperty('width', `${Math.round((overall || 0) * 100)}%`);
  const engineLabel = detail.engine === 'local' ? 'النموذج المحلي' : detail.engine === 'claude' ? 'الذكاء السحابي' : 'إدخال يدوي';
  const summary = h(
    'div',
    { class: 'summary-bar' },
    overall !== undefined && overall !== null ? h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'ثقة القراءة'), h('div', { class: 'meter' }, meterFill), h('strong', {}, fmtPct(overall))) : null,
    badge(engineLabel, 'info', detail.engine === 'local' ? 'cpu' : 'cloud'),
    detail.passes === 2 ? badge('قراءة ثانية بخط الطبيب', 'good', 'sparkles') : null,
    fromVerified ? badge(`معتمدة${source.verified_by ? ` - ${source.verified_by}` : ''}`, 'good', 'check') : null,
    reviewInfo ? h('span', { class: 'small muted', style: { 'margin-inline-start': 'auto' } }, reviewInfo) : null,
  );
  const warnings = (source.warnings || []).map((w) => {
    const level = WARNING_LEVELS[w.level] || WARNING_LEVELS.moderate;
    return alertBox(level.kind, level.label, w.message);
  });

  const panel = h(
    'div',
    { class: 'stack' },
    summary,
    result.is_prescription === false ? alertBox('warn', 'يبدو أن الصورة ليست روشتة طبية', 'تأكد من الصورة أو ارفضها.') : null,
    !fromVerified && result.notes ? alertBox('info', 'ملاحظة القارئ الآلي', result.notes, 'sparkles') : null,
    warnings,
    itemsBox,
    h(
      'div',
      { class: 'card' },
      h('div', { class: 'card-head' }, h('h3', {}, 'الطبيب والمريض')),
      h('div', { class: 'stack' }, field('الطبيب', h('div', { class: 'stack' }, doctorField, doctorHint)), h('div', { class: 'form-grid' }, field('اسم المريض', patientName, 'اختياري'), field('السن', patientAge, 'اختياري')), field('ملاحظات', notes)),
    ),
    canEdit
      ? h(
          'div',
          { class: 'card flat stack' },
          h('label', { class: 'check' }, training, 'استخدمها في تدريب النظام (موصى به)'),
          hasRole(MANAGERS) ? h('label', { class: 'check' }, academy, 'إتاحتها في أكاديمية تدريب الصيادلة (تأكد من إخفاء بيانات المريض)') : null,
        )
      : null,
    h(
      'div',
      { class: 'sticky-actions' },
      canEdit ? verifyBtn : null,
      button('طباعة الملصقات', { iconName: 'printer', onClick: () => printLabels(st.items.map((i) => ({ ...i, instructions_ar: liveInstructions(i) })), { patient: st.patient.name, ...appState.me.app }) }),
      canEdit && detail.status !== 'rejected' ? button('رفض', { kind: 'ghost', iconName: 'x', onClick: reject }) : null,
      canEdit ? button('إعادة القراءة', { kind: 'ghost', iconName: 'refresh', onClick: reread }) : null,
      hasRole(ADMIN) ? button('حذف', { kind: 'ghost danger', iconName: 'trash', onClick: remove }) : null,
    ),
  );

  renderItems();
  const element = h('div', { class: 'editor' }, h('div', { class: 'viewer-col' }, viewer.element), panel);
  return {
    element,
    destroy: () => {
      document.removeEventListener('keydown', onKey);
      viewer.destroy();
    },
  };
}
