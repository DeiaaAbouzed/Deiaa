import { get, post, put } from '../lib/api.js';
import { debounce, h, ltr, mount } from '../lib/dom.js';
import { navigate } from '../lib/router.js';
import { badge, button, empty, field, fmtNum, fmtPct, loading, modal, pageHead, showError, timeAgo, toast } from '../lib/ui.js';

function editDoctor(doctor, onSaved) {
  const name = h('input', { class: 'input', value: doctor ? doctor.name : '' });
  const specialty = h('input', { class: 'input', value: doctor ? doctor.specialty : '' });
  const clinic = h('input', { class: 'input', value: doctor ? doctor.clinic : '' });
  const phone = h('input', { class: 'input ltr', dir: 'ltr', value: doctor ? doctor.phone : '' });
  const notes = h('textarea', { class: 'textarea', value: doctor ? doctor.notes : '' });
  modal({
    title: doctor ? 'تعديل بيانات الطبيب' : 'إضافة طبيب',
    body: h('div', { class: 'stack' }, field('الاسم', name), h('div', { class: 'form-grid' }, field('التخصص', specialty), field('الهاتف', phone)), field('العيادة', clinic), field('ملاحظات عن خطه', notes)),
    actions: [
      { label: 'إلغاء', onClick: (close) => close() },
      {
        label: 'حفظ',
        kind: 'primary',
        onClick: async (close) => {
          const body = { name: name.value, specialty: specialty.value, clinic: clinic.value, phone: phone.value, notes: notes.value };
          try {
            await (doctor ? put(`/api/doctors/${doctor.id}`, body) : post('/api/doctors', body));
            close();
            toast('تم الحفظ');
            onSaved();
          } catch (error) {
            showError(error);
          }
        },
      },
    ],
  });
}

async function showDoctor(id, reload) {
  const d = await get(`/api/doctors/${id}`);
  const others = (await get('/api/doctors', { limit: 200 })).filter((o) => o.id !== d.id);
  const target = h('select', { class: 'select' }, others.map((o) => h('option', { value: o.id }, o.name)));
  const handle = modal({
    title: d.name,
    wide: true,
    body: h(
      'div',
      { class: 'stack' },
      h('div', { class: 'row' }, d.specialty ? badge(d.specialty, 'info') : null, badge(`${fmtNum(d.verified_count)} روشتة معتمدة`), badge(`دقة القراءة ${fmtPct(d.accuracy)}`, 'good'), badge(`${fmtNum(d.learned_corrections)} تصحيح محفوظ`)),
      d.clinic ? h('p', {}, d.clinic) : null,
      d.notes ? h('p', { class: 'muted' }, d.notes) : null,
      h('h3', {}, 'الأدوية التي يكتبها كثيراً'),
      d.top_drugs.length ? h('div', { class: 'row' }, d.top_drugs.map((t) => badge([ltr(t.brand), ` × ${fmtNum(t.count)}`]))) : h('p', { class: 'muted' }, 'لا توجد بيانات بعد'),
      h(
        'div',
        { class: 'row' },
        button('روشتاته', { iconName: 'clock', onClick: () => { handle.close(); navigate(`history?doctor=${d.id}`); } }),
        button('تعديل', { iconName: 'pencil', onClick: () => { handle.close(); editDoctor(d, reload); } }),
      ),
      others.length
        ? h(
            'details',
            {},
            h('summary', {}, 'دمج مع ملف طبيب مكرر'),
            h('div', { class: 'stack', style: { 'margin-top': '10px' } }, h('p', { class: 'small muted' }, 'يُنقل كل ما تعلّمه النظام عن هذا الملف إلى الملف المختار، ثم يُحذف هذا الملف.'), field('دمج في', target), button('دمج', {
              kind: 'danger',
              iconName: 'merge',
              onClick: async () => {
                try {
                  await post(`/api/doctors/${d.id}/merge`, { into_id: Number(target.value) });
                  handle.close();
                  toast('تم الدمج');
                  reload();
                } catch (error) {
                  showError(error);
                }
              },
            })),
          )
        : null,
    ),
  });
}

export default async function doctorsView(root) {
  let q = '';
  const list = h('div', {});
  const search = h('input', { class: 'input', type: 'search', placeholder: 'ابحث باسم الطبيب...', 'aria-label': 'بحث' });
  search.addEventListener('input', debounce(() => { q = search.value; load(); }, 300));

  async function load() {
    mount(list, loading());
    const doctors = await get('/api/doctors', { q, limit: 200 });
    if (!doctors.length) return mount(list, empty('لا يوجد أطباء بعد - تُضاف ملفاتهم تلقائياً عند اعتماد الروشتات', 'doctor'));
    mount(
      list,
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'table' },
          h('thead', {}, h('tr', {}, h('th', {}, 'الطبيب'), h('th', {}, 'التخصص'), h('th', { class: 'num' }, 'روشتات معتمدة'), h('th', { class: 'num' }, 'دقة القراءة'), h('th', {}, 'آخر روشتة'))),
          h(
            'tbody',
            {},
            doctors.map((d) =>
              h('tr', { class: 'clickable', tabindex: '0', onClick: () => showDoctor(d.id, load), onKeydown: (e) => e.key === 'Enter' && showDoctor(d.id, load) }, h('td', {}, h('strong', {}, d.name)), h('td', {}, d.specialty || '—'), h('td', { class: 'num' }, fmtNum(d.verified_count)), h('td', { class: 'num' }, fmtPct(d.accuracy)), h('td', { class: 'small muted' }, timeAgo(d.last_seen_at))),
            ),
          ),
        ),
      ),
    );
  }
  root.append(
    pageHead('الأطباء', 'لكل طبيب ملف يتعلم منه النظام خطه وأدويته المعتادة', button('إضافة طبيب', { kind: 'primary', iconName: 'plus', onClick: () => editDoctor(null, load) })),
    h('div', { style: { 'margin-bottom': '14px' } }, search),
    list,
  );
  await load();
}
