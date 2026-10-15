import { del, download, get, post, postForm, put } from '../lib/api.js';
import { debounce, h, ltr, mount } from '../lib/dom.js';
import { FORMS } from '../lib/labels.js';
import { MANAGERS, hasRole } from '../lib/state.js';
import { badge, button, confirmDialog, empty, field, fmtNum, loading, modal, pageHead, showError, toast } from '../lib/ui.js';

const SOURCES = { seed: 'أساسي', user: 'مضاف', import: 'مستورد', learned: 'تعلّمه النظام', generic: 'اسم علمي' };

function editDrug(drug, onSaved) {
  const brand = h('input', { class: 'input ltr', dir: 'ltr', value: drug ? drug.brand : '', required: true });
  const generic = h('input', { class: 'input ltr', dir: 'ltr', value: drug ? drug.generic : '', placeholder: 'amoxicillin + clavulanic acid' });
  const cls = h('input', { class: 'input ltr', dir: 'ltr', value: drug ? drug.drug_class : '', placeholder: 'NSAID, PPI, Statin...' });
  const strengths = h('input', { class: 'input ltr', dir: 'ltr', value: drug ? drug.strengths.join(' | ') : '', placeholder: '375mg | 625mg | 1g' });
  const aliases = h('input', { class: 'input', value: drug ? drug.aliases.join(' | ') : '', placeholder: 'أسماء بديلة أو بالعربي' });
  const forms = h('select', { class: 'select', multiple: true, size: 6 }, Object.entries(FORMS).map(([v, t]) => h('option', { value: v, selected: drug && drug.forms.includes(v) }, t)));
  const split = (el) => el.value.split('|').map((s) => s.trim()).filter(Boolean);
  modal({
    title: drug ? `تعديل ${drug.brand}` : 'إضافة دواء',
    wide: true,
    body: h(
      'div',
      { class: 'stack' },
      h('div', { class: 'form-grid' }, field('الاسم التجاري', brand), field('المادة الفعالة', generic), field('المجموعة الدوائية', cls)),
      field('التركيزات المتاحة', strengths, 'افصل بينها بـ |'),
      field('أسماء بديلة', aliases, 'تساعد المطابقة؛ افصل بـ |'),
      field('الأشكال الدوائية', forms, 'اضغط Ctrl لاختيار أكثر من شكل'),
    ),
    actions: [
      { label: 'إلغاء', onClick: (close) => close() },
      {
        label: 'حفظ',
        kind: 'primary',
        icon: 'check',
        onClick: async (close) => {
          const body = {
            brand: brand.value.trim(),
            generic: generic.value.trim(),
            drug_class: cls.value.trim(),
            strengths: split(strengths),
            aliases: split(aliases),
            forms: [...forms.selectedOptions].map((o) => o.value),
          };
          try {
            await (drug ? put(`/api/drugs/${drug.id}`, body) : post('/api/drugs', body));
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

export default async function drugsView(root) {
  const manager = hasRole(MANAGERS);
  let q = '';
  let source = '';
  let page = 1;
  const list = h('div', {});
  const search = h('input', { class: 'input', type: 'search', placeholder: 'ابحث بالاسم التجاري أو العلمي أو العربي...', 'aria-label': 'بحث' });
  search.addEventListener('input', debounce(() => { q = search.value; page = 1; load(); }, 300));
  const sourceSelect = h('select', { class: 'select', 'aria-label': 'المصدر', onChange: (e) => { source = e.target.value; page = 1; load(); } }, h('option', { value: '' }, 'كل المصادر'), Object.entries(SOURCES).map(([v, t]) => h('option', { value: v }, t)));

  async function load() {
    mount(list, loading());
    const data = await get('/api/drugs', { q, source, page, page_size: 50 });
    if (!data.items.length) return mount(list, empty('لا توجد نتائج', 'pill'));
    const pages = Math.ceil(data.total / 50);
    mount(
      list,
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'table' },
          h('thead', {}, h('tr', {}, h('th', {}, 'الاسم التجاري'), h('th', {}, 'المادة الفعالة'), h('th', {}, 'المجموعة'), h('th', {}, 'التركيزات'), h('th', {}, 'المصدر'), manager ? h('th', {}, '') : null)),
          h(
            'tbody',
            {},
            data.items.map((d) =>
              h(
                'tr',
                {},
                h('td', {}, h('strong', {}, ltr(d.brand))),
                h('td', {}, ltr(d.generic)),
                h('td', {}, ltr(d.drug_class)),
                h('td', { class: 'small' }, ltr(d.strengths.join(' · '))),
                h('td', {}, badge(SOURCES[d.source] || d.source, d.source === 'learned' ? 'warn' : '')),
                manager
                  ? h(
                      'td',
                      {},
                      h(
                        'div',
                        { class: 'row' },
                        button('تعديل', { size: 'sm', iconName: 'pencil', onClick: () => editDrug(d, load) }),
                        button('', {
                          size: 'sm',
                          kind: 'ghost',
                          iconName: 'trash',
                          title: 'إيقاف',
                          onClick: async () => {
                            if (!(await confirmDialog(`إيقاف ${d.brand} من قاعدة الأدوية؟`))) return;
                            try {
                              await del(`/api/drugs/${d.id}`);
                              load();
                            } catch (error) {
                              showError(error);
                            }
                          },
                        }),
                      ),
                    )
                  : null,
              ),
            ),
          ),
        ),
      ),
      h(
        'div',
        { class: 'row', style: { 'justify-content': 'center', 'margin-top': '12px' } },
        page > 1 ? button('السابق', { size: 'sm', onClick: () => { page -= 1; load(); } }) : null,
        h('span', { class: 'small muted' }, `${fmtNum(data.total)} صنف · صفحة ${fmtNum(page)} من ${fmtNum(pages)}`),
        page < pages ? button('التالي', { size: 'sm', onClick: () => { page += 1; load(); } }) : null,
      ),
    );
  }

  const importInput = h('input', { type: 'file', accept: '.csv,text/csv', class: 'hidden' });
  importInput.addEventListener('change', async () => {
    const file = importInput.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file, file.name);
    try {
      const r = await postForm('/api/drugs/import', form);
      toast(`تمت الإضافة: ${fmtNum(r.created)} · التحديث: ${fmtNum(r.updated)}`);
      load();
    } catch (error) {
      showError(error);
    }
    importInput.value = '';
  });
  const actions = manager
    ? [
        button('إضافة دواء', { kind: 'primary', iconName: 'plus', onClick: () => editDrug(null, load) }),
        button('استيراد CSV', { iconName: 'upload', onClick: () => importInput.click() }),
        button('تصدير CSV', { iconName: 'download', onClick: () => download('GET', '/api/drugs/export').catch(showError) }),
        importInput,
      ]
    : [];
  root.append(
    pageHead('قاعدة الأدوية', 'الأسماء المتداولة في السوق المصري - يطابق عليها القارئ الآلي، وتكبر مع كل مراجعة', ...actions),
    h('div', { class: 'row', style: { 'margin-bottom': '14px' } }, h('div', { class: 'grow' }, search), sourceSelect),
    list,
  );
  await load();
}
