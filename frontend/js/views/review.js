// Review queue: one prescription after another - the fastest way to feed the system.
import { get } from '../lib/api.js';
import { h, mount } from '../lib/dom.js';
import { navigate } from '../lib/router.js';
import { button, empty, fmtNum, pageHead } from '../lib/ui.js';
import { renderPrescription } from './rx.js';

export default async function reviewView(root, _params, query) {
  const container = h('div', {});
  root.append(container);
  let cleanup = null;
  let lastUid = null;

  async function next() {
    if (cleanup) cleanup();
    cleanup = null;
    const batch = query.batch || null;
    let data = await get('/api/review/next', { batch_id: batch, after: lastUid });
    if (!data.uid && lastUid) data = await get('/api/review/next', { batch_id: batch }); // wrap around
    if (!data.uid) {
      mount(
        container,
        pageHead('المراجعة', 'كل روشتة تراجعها تجعل القراءة القادمة أدق'),
        empty('لا توجد روشتات تنتظر المراجعة - عمل رائع!', 'check', button('قراءة روشتة جديدة', { kind: 'primary', iconName: 'camera', onClick: () => navigate('read') })),
      );
      return;
    }
    lastUid = data.uid;
    const holder = h('div', {});
    mount(container, holder);
    cleanup = await renderPrescription(holder, data.uid, {
      reviewInfo: `متبقي في الطابور: ${fmtNum(data.remaining)}`,
      onFinished: (outcome) => {
        if (outcome.action === 'reread') renderAgain(data.uid);
        else next();
      },
    });
  }

  async function renderAgain(uid) {
    if (cleanup) cleanup();
    const holder = h('div', {});
    mount(container, holder);
    cleanup = await renderPrescription(holder, uid, { onFinished: () => next() });
  }

  await next();
  return () => cleanup && cleanup();
}
