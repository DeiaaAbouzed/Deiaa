// Feeding the system in bulk: many photos at once, or an already-labelled archive.
import { get, upload } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { navigate } from '../lib/router.js';
import { alertBox, button, empty, field, fmtDateTime, fmtNum, pageHead, progressBar, setBusy, showError, toast } from '../lib/ui.js';

const JSONL_SAMPLE = `{"file": "rx001.jpg", "doctor": {"name": "د. أحمد علي", "specialty": "باطنة"},
 "items": [{"brand": "Augmentin", "strength": "1g", "form": "tablet", "sig_text": "1x2 7 days"},
           {"brand": "Panadol", "strength": "500mg", "sig_text": "1x3 prn"}]}`;
const CSV_SAMPLE = `file,doctor,brand,strength,form,sig_text
rx001.jpg,د. أحمد علي,Augmentin,1g,tablet,1x2 7 days
rx001.jpg,د. أحمد علي,Panadol,500mg,tablet,1x3 prn`;

function dropzone(text, accept, multiple, onFiles) {
  const input = h('input', { type: 'file', accept, multiple, class: 'hidden' });
  const zone = h('div', { class: 'dropzone', tabindex: '0', role: 'button' }, icon('upload'), h('strong', {}, text), h('span', { class: 'small muted' }, 'اضغط للاختيار أو اسحب الملفات هنا'), input);
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && input.click());
  input.addEventListener('change', () => onFiles([...input.files]));
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('drag');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('drag');
    onFiles([...(e.dataTransfer?.files || [])]);
  });
  return zone;
}

function stackbar(counts) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const seg = (cls, n) => {
    if (!n) return null;
    const el = h('span', { class: cls, title: fmtNum(n) });
    el.style.setProperty('width', `${(100 * n) / total}%`);
    return el;
  };
  return h(
    'div',
    { class: 'stackbar', role: 'img', 'aria-label': `معتمدة ${counts.verified}، للمراجعة ${counts.needs_review}، قيد القراءة ${counts.queued + counts.processing}، فشلت ${counts.failed}` },
    seg('s-verified', counts.verified),
    seg('s-review', counts.needs_review),
    seg('s-queued', counts.queued + counts.processing),
    seg('s-failed', counts.failed),
  );
}

export default async function feedView(root) {
  const batchesBox = h('div', { class: 'stack' });
  let pollTimer = null;

  async function loadBatches() {
    clearTimeout(pollTimer);
    const batches = await get('/api/batches');
    if (!batches.length) {
      mount(batchesBox, empty('لم تُرفع أي دفعات بعد', 'layers'));
      return;
    }
    let busy = false;
    mount(
      batchesBox,
      batches.map((b) => {
        const c = b.counts;
        busy = busy || c.queued + c.processing > 0;
        return h(
          'div',
          { class: 'card flat' },
          h(
            'div',
            { class: 'row between' },
            h('div', {}, h('strong', {}, b.name), h('div', { class: 'small muted' }, `${fmtDateTime(b.created_at)} · ${b.created_by} · ${b.kind === 'import' ? 'أرشيف مُعلَّم' : 'قراءة آلية'}`)),
            c.needs_review ? button(`مراجعة ${fmtNum(c.needs_review)}`, { size: 'sm', kind: 'primary', iconName: 'inbox', onClick: () => navigate(`review?batch=${b.id}`) }) : null,
          ),
          h('div', { style: { 'margin-top': '10px' } }, stackbar(c)),
          h(
            'div',
            { class: 'row small muted', style: { 'margin-top': '6px' } },
            h('span', {}, h('span', { class: 'dot good' }), ` معتمدة ${fmtNum(c.verified)}`),
            h('span', {}, h('span', { class: 'dot warn' }), ` للمراجعة ${fmtNum(c.needs_review)}`),
            h('span', {}, ` قيد القراءة ${fmtNum(c.queued + c.processing)}`),
            c.failed ? h('span', {}, h('span', { class: 'dot bad' }), ` فشلت ${fmtNum(c.failed)}`) : null,
          ),
        );
      }),
    );
    if (busy) pollTimer = setTimeout(loadBatches, 4000);
  }

  // ---- bulk photos ----
  const batchName = h('input', { class: 'input', placeholder: 'مثال: روشتات فرع المعادي - أكتوبر' });
  const photoStatus = h('div', { class: 'stack' });
  let photos = [];
  const sendPhotos = button('ابدأ القراءة الآلية', { kind: 'primary', iconName: 'sparkles', disabled: true });
  const photoZone = dropzone('صور الروشتات (حتى ٢٠٠ صورة)', 'image/jpeg,image/png,image/webp', true, (files) => {
    photos = files.filter((f) => f.type.startsWith('image/'));
    sendPhotos.disabled = !photos.length;
    mount(photoStatus, h('span', { class: 'small' }, `تم اختيار ${fmtNum(photos.length)} صورة`));
  });
  sendPhotos.addEventListener('click', async () => {
    const form = new FormData();
    photos.forEach((f) => form.append('files', f, f.name));
    form.append('name', batchName.value);
    setBusy(sendPhotos, true, 'جاري الرفع...');
    try {
      const result = await upload('/api/batches', form, (f) => mount(photoStatus, progressBar(f)));
      mount(
        photoStatus,
        alertBox('good', `تم استلام ${fmtNum(result.accepted)} صورة وبدأت قراءتها`, result.rejected.length ? `تم استبعاد ${fmtNum(result.rejected.length)}: ${result.rejected.slice(0, 5).map((r) => `${r.file} (${r.error})`).join('، ')}` : null),
      );
      photos = [];
      loadBatches();
    } catch (error) {
      showError(error);
    } finally {
      setBusy(sendPhotos, false);
      sendPhotos.disabled = !photos.length;
    }
  });

  // ---- labelled archive ----
  const archiveStatus = h('div', { class: 'stack' });
  const archiveZone = dropzone('ملف ZIP يحتوي الصور + labels.jsonl أو labels.csv', '.zip,application/zip', false, async (files) => {
    const file = files[0];
    if (!file) return;
    const form = new FormData();
    form.append('archive', file, file.name);
    form.append('name', file.name);
    try {
      const result = await upload('/api/batches/import', form, (f) => mount(archiveStatus, h('span', { class: 'small' }, 'رفع الأرشيف...'), progressBar(f)));
      mount(
        archiveStatus,
        alertBox('good', `أضيفت ${fmtNum(result.verified)} روشتة معتمدة للتدريب`, `${fmtNum(result.queued)} صورة بدون تسميات أُرسلت للقراءة الآلية${result.problems.length ? ` - ${fmtNum(result.problems.length)} ملف به مشكلة` : ''}`),
      );
      toast('تم الاستيراد');
      loadBatches();
    } catch (error) {
      mount(archiveStatus, alertBox('bad', 'تعذر الاستيراد', error.message));
    }
  });

  root.append(
    pageHead('تغذية النظام', 'كلما غذّيت رُشد بروشتات مراجَعة أكثر، أصبح أدق في قراءة خط أطبائك'),
    alertBox('info', 'كيف يتعلم رُشد؟', 'كل روشتة تعتمدها تصبح مثالاً يتعلم منه: خط كل طبيب، أدويته المعتادة، وأخطاء القراءة وتصحيحاتها. ومع الوقت يمكنك تدريب نموذجك الخاص الذي يعمل بدون إنترنت.', 'sparkles'),
    h(
      'div',
      { class: 'grid-2', style: { 'margin-top': '16px' } },
      h('div', { class: 'card stack' }, h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'رفع دفعة صور'), h('p', {}, 'يقرأها الذكاء الاصطناعي ثم تراجعها أنت بسرعة'))), field('اسم الدفعة', batchName), photoZone, photoStatus, sendPhotos),
      h(
        'div',
        { class: 'card stack' },
        h('div', { class: 'card-head' }, h('div', {}, h('h2', {}, 'استيراد روشتات مكتوبة مسبقاً'), h('p', {}, 'لو عندك روشتات مُفرغة بالفعل تدخل التدريب مباشرة'))),
        archiveZone,
        archiveStatus,
        h('details', {}, h('summary', { class: 'small' }, 'شكل ملف التسميات'), h('p', { class: 'small muted' }, 'labels.jsonl - سطر لكل روشتة:'), h('div', { class: 'code-sample' }, JSONL_SAMPLE), h('p', { class: 'small muted' }, 'أو labels.csv - سطر لكل دواء:'), h('div', { class: 'code-sample' }, CSV_SAMPLE)),
      ),
    ),
    h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', {}, 'الدفعات')), batchesBox),
  );
  await loadBatches();
  return () => clearTimeout(pollTimer);
}
