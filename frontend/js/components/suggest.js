// Accessible autocomplete for drug and doctor names.
import { debounce, h, mount } from '../lib/dom.js';

export function suggestInput(input, { fetcher, render, onPick, minChars = 2 }) {
  const list = h('div', { class: 'suggest-list hidden', role: 'listbox' });
  const wrap = h('div', { class: 'suggest' }, input, list);
  let items = [];
  let active = -1;
  let seq = 0;
  input.setAttribute('autocomplete', 'off');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-expanded', 'false');

  const close = () => {
    list.classList.add('hidden');
    input.setAttribute('aria-expanded', 'false');
    active = -1;
  };
  const highlight = () => {
    [...list.children].forEach((el, i) => el.classList.toggle('active', i === active));
  };
  const pick = (item) => {
    close();
    onPick(item);
  };

  const search = debounce(async () => {
    const q = input.value.trim();
    if (q.length < minChars) return close();
    const id = ++seq;
    try {
      const found = await fetcher(q);
      if (id !== seq) return;
      items = found || [];
      if (!items.length) return close();
      mount(
        list,
        items.map((item) =>
          h('button', { type: 'button', role: 'option', onMousedown: (e) => e.preventDefault(), onClick: () => pick(item) }, render(item)),
        ),
      );
      list.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
      active = -1;
    } catch {
      close();
    }
  }, 220);

  input.addEventListener('input', search);
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (e) => {
    if (list.classList.contains('hidden')) return;
    if (e.key === 'ArrowDown') {
      active = Math.min(items.length - 1, active + 1);
      highlight();
      e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      active = Math.max(0, active - 1);
      highlight();
      e.preventDefault();
    } else if (e.key === 'Enter' && active >= 0) {
      pick(items[active]);
      e.preventDefault();
    } else if (e.key === 'Escape') {
      close();
    }
  });
  return wrap;
}
