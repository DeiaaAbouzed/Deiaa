// Printable Arabic patient labels - one per medication.
import { h, mount } from '../lib/dom.js';

export function printLabels(items, { patient = '', pharmacy_name = '', label_footer = '' } = {}) {
  const area = document.getElementById('print-area');
  const today = new Intl.DateTimeFormat('ar-EG', { dateStyle: 'medium' }).format(new Date());
  mount(
    area,
    h(
      'div',
      { class: 'labels' },
      items.map((item) =>
        h(
          'div',
          { class: 'label-card' },
          h('div', { class: 'l-head' }, h('span', {}, pharmacy_name || 'الصيدلية'), h('span', {}, today)),
          patient ? h('div', {}, `المريض: ${patient}`) : null,
          h('div', { class: 'l-drug', dir: 'ltr' }, [item.brand, item.strength].filter(Boolean).join(' ')),
          h('div', { class: 'l-sig' }, item.instructions_ar || '—'),
          label_footer ? h('div', { class: 'l-foot' }, label_footer) : null,
        ),
      ),
    ),
  );
  window.print();
}
