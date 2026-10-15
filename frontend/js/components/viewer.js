// Zoom / pan / rotate viewer for the prescription photo (mouse, touch and keyboard).
import { h } from '../lib/dom.js';
import { iconButton } from '../lib/ui.js';

export function imageViewer(src, alt = 'صورة الروشتة') {
  const img = h('img', { alt, draggable: 'false' });
  const box = h('div', { class: 'viewer', tabindex: '0', 'aria-label': 'عارض الصورة: اسحب للتحريك واستخدم + و - للتكبير' });
  let scale = 1;
  let x = 0;
  let y = 0;
  let rotation = 0;
  let natural = { w: 1, h: 1 };
  const pointers = new Map();
  let pinch = null;

  const apply = () => img.style.setProperty('transform', `translate(${x}px, ${y}px) scale(${scale})`);

  function fit() {
    const bw = box.clientWidth || 400;
    const bh = box.clientHeight || 500;
    scale = Math.min(bw / natural.w, bh / natural.h);
    x = (bw - natural.w * scale) / 2;
    y = (bh - natural.h * scale) / 2;
    apply();
  }

  function zoomAt(factor, cx, cy) {
    const next = Math.min(8, Math.max(0.1, scale * factor));
    const ratio = next / scale;
    x = cx - (cx - x) * ratio;
    y = cy - (cy - y) * ratio;
    scale = next;
    apply();
  }

  const center = () => [box.clientWidth / 2, box.clientHeight / 2];

  async function load(source) {
    img.src = source;
    await img.decode().catch(() => {});
    natural = { w: img.naturalWidth || 1, h: img.naturalHeight || 1 };
    requestAnimationFrame(fit);
  }

  async function rotate() {
    // Bake the rotation into a fresh image so zoom/pan maths stay simple.
    rotation = (rotation + 90) % 360;
    const canvas = document.createElement('canvas');
    canvas.width = natural.h;
    canvas.height = natural.w;
    const ctx = canvas.getContext('2d');
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(img, -natural.w / 2, -natural.h / 2);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    const previous = img.src;
    await load(URL.createObjectURL(blob));
    if (previous.startsWith('blob:')) URL.revokeObjectURL(previous);
  }

  box.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = box.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - rect.left, e.clientY - rect.top);
  }, { passive: false });

  box.addEventListener('pointerdown', (e) => {
    box.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    box.classList.add('grabbing');
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) };
    }
  });
  box.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2 && pinch) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const rect = box.getBoundingClientRect();
      zoomAt(dist / pinch.dist, (a.x + b.x) / 2 - rect.left, (a.y + b.y) / 2 - rect.top);
      pinch.dist = dist;
    } else if (pointers.size === 1) {
      x += e.clientX - prev.x;
      y += e.clientY - prev.y;
      apply();
    }
  });
  const end = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) box.classList.remove('grabbing');
  };
  box.addEventListener('pointerup', end);
  box.addEventListener('pointercancel', end);
  box.addEventListener('dblclick', (e) => {
    const rect = box.getBoundingClientRect();
    zoomAt(2, e.clientX - rect.left, e.clientY - rect.top);
  });
  box.addEventListener('keydown', (e) => {
    const step = 40;
    if (e.key === '+' || e.key === '=') zoomAt(1.25, ...center());
    else if (e.key === '-') zoomAt(0.8, ...center());
    else if (e.key === '0') fit();
    else if (e.key === 'ArrowLeft') x += step;
    else if (e.key === 'ArrowRight') x -= step;
    else if (e.key === 'ArrowUp') y += step;
    else if (e.key === 'ArrowDown') y -= step;
    else return;
    e.preventDefault();
    apply();
  });

  const tools = h(
    'div',
    { class: 'viewer-tools' },
    iconButton('zoomIn', 'تكبير', () => zoomAt(1.3, ...center()), ''),
    iconButton('zoomOut', 'تصغير', () => zoomAt(1 / 1.3, ...center()), ''),
    iconButton('fit', 'ملاءمة الحجم', fit, ''),
    iconButton('rotate', 'تدوير', rotate, ''),
  );
  box.append(img, tools);
  let lastWidth = 0;
  const resizeObserver = new ResizeObserver(() => {
    // Refit only when the width changes: mobile browsers resize the height while scrolling.
    if (Math.abs(box.clientWidth - lastWidth) > 1) {
      lastWidth = box.clientWidth;
      fit();
    }
  });
  resizeObserver.observe(box);
  load(src);
  return { element: box, destroy: () => resizeObserver.disconnect() };
}
