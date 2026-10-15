// Reading a prescription: photograph -> (optional) hide patient data -> read.
import { get, upload } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { navigate } from '../lib/router.js';
import { alertBox, button, field, pageHead, progressBar, setBusy, showError, toast } from '../lib/ui.js';
import { suggestInput } from '../components/suggest.js';

const MAX_EDGE = 3000;

async function decode(file) {
  if ('createImageBitmap' in window) {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      /* fall back to <img> */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

function capturePanel(onFile) {
  const camera = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'hidden' });
  const gallery = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', class: 'hidden' });
  const take = (input) => input.files && input.files[0] && onFile(input.files[0]);
  camera.addEventListener('change', () => take(camera));
  gallery.addEventListener('change', () => take(gallery));
  const hero = h(
    'div',
    { class: 'capture-hero' },
    h('div', { class: 'big-icon' }, icon('camera')),
    h('h2', {}, 'صوّر الروشتة أو ارفع صورتها'),
    h('p', { class: 'muted' }, 'يتعرّف رُشد على خط الطبيب، ويطابق الأدوية، ويكتب طريقة الاستخدام بالعربي.'),
    h(
      'div',
      { class: 'capture-actions' },
      button('تصوير الروشتة', { kind: 'primary lg', iconName: 'camera', onClick: () => camera.click() }),
      button('اختيار صورة', { size: 'lg', iconName: 'image', onClick: () => gallery.click() }),
    ),
    h('p', { class: 'small muted' }, 'أو اسحب الصورة وأفلتها هنا'),
    camera,
    gallery,
  );
  hero.addEventListener('dragover', (e) => {
    e.preventDefault();
    hero.classList.add('drag');
  });
  hero.addEventListener('dragleave', () => hero.classList.remove('drag'));
  hero.addEventListener('drop', (e) => {
    e.preventDefault();
    hero.classList.remove('drag');
    const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith('image/'));
    if (file) onFile(file);
  });
  const tips = h(
    'div',
    { class: 'tips' },
    [
      ['sun', 'إضاءة جيدة بدون ظلال أو فلاش مباشر'],
      ['fit', 'اجعل الروشتة تملأ الصورة ومستوية'],
      ['eyeOff', 'يمكنك إخفاء اسم المريض قبل القراءة'],
      ['lock', 'الصور تُحفظ مشفرة ولا يراها إلا المخولون'],
    ].map(([ic, text]) => h('div', { class: 'tip' }, icon(ic), h('span', {}, text))),
  );
  return h('div', {}, hero, tips);
}

function preparePanel(bitmap, { onCancel }) {
  let rotation = 0;
  let boxes = [];
  let drawing = null;
  let redactMode = false;
  let enhance = false;
  let doctor = null;

  const canvas = h('canvas', { 'aria-label': 'معاينة الروشتة' });
  const ctx = canvas.getContext('2d');
  const wrap = h('div', { class: 'canvas-wrap' }, canvas);

  function draw() {
    const rotated = rotation % 180 !== 0;
    const w = rotated ? bitmap.height : bitmap.width;
    const ht = rotated ? bitmap.width : bitmap.height;
    const scale = Math.min(1, MAX_EDGE / Math.max(w, ht));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(ht * scale);
    ctx.save();
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate((rotation * Math.PI) / 180);
    const dw = bitmap.width * scale;
    const dh = bitmap.height * scale;
    ctx.drawImage(bitmap, -dw / 2, -dh / 2, dw, dh);
    ctx.restore();
    ctx.fillStyle = '#000';
    for (const b of [...boxes, ...(drawing ? [drawing] : [])]) {
      ctx.fillRect(b.x * canvas.width, b.y * canvas.height, b.w * canvas.width, b.h * canvas.height);
    }
  }

  const point = (e) => {
    const rect = canvas.getBoundingClientRect();
    return { x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height };
  };
  canvas.addEventListener('pointerdown', (e) => {
    if (!redactMode) return;
    canvas.setPointerCapture(e.pointerId);
    const p = point(e);
    drawing = { x: p.x, y: p.y, w: 0, h: 0, ox: p.x, oy: p.y };
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drawing) return;
    const p = point(e);
    drawing.x = Math.min(p.x, drawing.ox);
    drawing.y = Math.min(p.y, drawing.oy);
    drawing.w = Math.abs(p.x - drawing.ox);
    drawing.h = Math.abs(p.y - drawing.oy);
    draw();
  });
  canvas.addEventListener('pointerup', () => {
    if (drawing && drawing.w > 0.01 && drawing.h > 0.005) boxes.push({ x: drawing.x, y: drawing.y, w: drawing.w, h: drawing.h });
    drawing = null;
    draw();
    undo.disabled = !boxes.length;
  });

  const redactBtn = button('إخفاء بيانات المريض', { size: 'sm', iconName: 'eyeOff' });
  redactBtn.addEventListener('click', () => {
    redactMode = !redactMode;
    wrap.classList.toggle('redact', redactMode);
    redactBtn.classList.toggle('primary', redactMode);
    hint.classList.toggle('hidden', !redactMode);
  });
  const undo = button('تراجع', { size: 'sm', iconName: 'undo', disabled: true, onClick: () => { boxes.pop(); undo.disabled = !boxes.length; draw(); } });
  const rotate = button('تدوير', {
    size: 'sm',
    iconName: 'rotate',
    onClick: () => {
      rotation = (rotation + 90) % 360;
      boxes = []; // boxes were drawn on the previous orientation
      undo.disabled = true;
      draw();
    },
  });
  const enhanceBtn = button('تحسين الوضوح', { size: 'sm', iconName: 'contrast' });
  enhanceBtn.addEventListener('click', () => {
    // Preview only; the server applies the real contrast enhancement.
    enhance = !enhance;
    enhanceBtn.classList.toggle('primary', enhance);
    canvas.style.setProperty('filter', enhance ? 'contrast(1.3) brightness(1.06)' : 'none');
  });
  const hint = h('p', { class: 'small muted hidden' }, 'ارسم مستطيلاً فوق اسم المريض أو أي بيانات شخصية لإخفائها قبل الرفع.');

  const doctorInput = h('input', { class: 'input', placeholder: 'اختياري - يسرّع القراءة ويزيد دقتها', 'aria-label': 'الطبيب' });
  const doctorNote = h('span', { class: 'small muted' });
  doctorInput.addEventListener('input', () => {
    doctor = null;
    doctorNote.textContent = '';
  });
  const doctorField = suggestInput(doctorInput, {
    fetcher: (q) => get('/api/doctors', { q, limit: 8 }),
    render: (d) => [h('span', {}, d.name), h('span', { class: 'gen' }, d.verified_count ? `تعلّم ${d.verified_count} روشتة` : d.specialty || '')],
    onPick: (d) => {
      doctor = d;
      doctorInput.value = d.name;
      doctorNote.textContent = d.verified_count ? `✓ سيستعين القارئ بـ ${d.verified_count} روشتة سابقة لهذا الطبيب` : '';
    },
  });

  const progressBox = h('div', { class: 'hidden stack' });
  const readBtn = button('اقرأ الروشتة الآن', { kind: 'primary lg block', iconName: 'sparkles' });
  readBtn.addEventListener('click', async () => {
    setBusy(readBtn, true, 'جاري الرفع...');
    progressBox.classList.remove('hidden');
    try {
      // Re-encoding here also strips EXIF (GPS, phone model) before anything leaves the device.
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
      const form = new FormData();
      form.append('image', blob, 'prescription.jpg');
      form.append('redactions', JSON.stringify(boxes));
      form.append('enhance', String(enhance));
      if (doctor) form.append('doctor_id', String(doctor.id));
      const result = await upload('/api/prescriptions', form, (f) => mount(progressBox, h('span', { class: 'small muted' }, 'رفع الصورة المشفّر...'), progressBar(f)));
      if (result.duplicate) toast('هذه الروشتة مرفوعة من قبل - تم فتحها');
      navigate(`rx/${result.uid}`);
    } catch (error) {
      showError(error);
      setBusy(readBtn, false);
      progressBox.classList.add('hidden');
    }
  });

  draw();
  return h(
    'div',
    { class: 'preview-layout' },
    h('div', {}, wrap, h('div', { class: 'canvas-toolbar' }, rotate, redactBtn, undo, enhanceBtn), hint),
    h(
      'div',
      { class: 'card stack' },
      h('h2', {}, 'جاهز للقراءة'),
      field('الطبيب', h('div', { class: 'stack' }, doctorField, doctorNote)),
      alertBox('info', 'الخصوصية أولاً', 'الصورة تُشفَّر فور وصولها للخادم، وما تخفيه هنا لا يُحفظ ولا يُرسل.', 'shield'),
      readBtn,
      progressBox,
      button('اختيار صورة أخرى', { kind: 'ghost', iconName: 'image', onClick: onCancel }),
    ),
  );
}

export default async function readView(root) {
  const body = h('div', {});
  const showCapture = () =>
    mount(
      body,
      capturePanel(async (file) => {
        if (file.size > 25 * 1024 * 1024) return showError({ message: 'حجم الصورة كبير جداً' });
        try {
          const bitmap = await decode(file);
          mount(body, preparePanel(bitmap, { onCancel: showCapture }));
        } catch {
          showError({ message: 'تعذر فتح الصورة - جرّب صورة JPG أو PNG' });
        }
      }),
    );
  showCapture();
  root.append(pageHead('قراءة روشتة', 'من الصورة إلى قائمة أدوية مراجَعة في ثوانٍ'), body);
}
