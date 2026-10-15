// Academy: pharmacists practise reading real (verified, approved) prescriptions.
import { get, post } from '../lib/api.js';
import { h, ltr, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { FREQUENCIES } from '../lib/labels.js';
import { MANAGERS, hasRole } from '../lib/state.js';
import { alertBox, badge, button, empty, fmtNum, fmtPct, loading, pageHead, setBusy, showError } from '../lib/ui.js';
import { imageViewer } from '../components/viewer.js';

const DIFFICULTIES = [
  ['any', 'أي مستوى'],
  ['easy', 'سهل'],
  ['medium', 'متوسط'],
  ['hard', 'صعب - خطوط حيّرت الذكاء الاصطناعي'],
];

export default async function academyView(root) {
  const body = h('div', {});
  let viewer = null;
  let timer = null;

  const stopTimers = () => {
    clearInterval(timer);
    if (viewer) viewer.destroy();
    viewer = null;
  };

  async function home() {
    stopTimers();
    mount(body, loading());
    const [me, board, pool] = await Promise.all([
      get('/api/academy/me'),
      get('/api/academy/leaderboard'),
      hasRole(MANAGERS) ? get('/api/academy/pool') : Promise.resolve(null),
    ]);
    let difficulty = 'any';
    const tabs = h(
      'div',
      { class: 'tabs' },
      DIFFICULTIES.map(([value, label]) =>
        h('button', { type: 'button', class: value === difficulty ? 'active' : '', onClick: (e) => { difficulty = value; [...tabs.children].forEach((b) => b.classList.toggle('active', b === e.currentTarget)); } }, label),
      ),
    );
    mount(
      body,
      h(
        'div',
        { class: 'grid-2' },
        h(
          'div',
          { class: 'card stack' },
          h('h2', {}, 'تحدي قراءة روشتة'),
          h('p', { class: 'muted' }, 'روشتة حقيقية من صيدلياتنا (بعد إخفاء بيانات المريض). اقرأها واكتب الأدوية، ثم قارن إجابتك بما اعتمده الصيدلي.'),
          tabs,
          button('ابدأ التحدي', { kind: 'primary lg', iconName: 'book', onClick: () => startQuiz(difficulty) }),
          me.attempts ? h('div', { class: 'row' }, badge(`محاولاتك: ${fmtNum(me.attempts)}`), badge(`متوسط درجتك: ${fmtPct((me.percent || 0) / 100)}`, 'info')) : null,
          pool ? alertBox('info', `بنك التدريب: ${fmtNum(pool.total)} روشتة`, `سهل ${fmtNum(pool.easy)} · متوسط ${fmtNum(pool.medium)} · صعب ${fmtNum(pool.hard)} - أضف المزيد بتفعيل خيار الأكاديمية عند اعتماد الروشتات.`) : null,
        ),
        h(
          'div',
          { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', {}, 'لوحة الشرف (٣٠ يوماً)'), icon('award')),
          board.length
            ? h(
                'div',
                { class: 'table-wrap' },
                h(
                  'table',
                  { class: 'table' },
                  h('thead', {}, h('tr', {}, h('th', {}, '#'), h('th', {}, 'الاسم'), h('th', { class: 'num' }, 'النقاط'), h('th', { class: 'num' }, 'الدقة'), h('th', { class: 'num' }, 'محاولات'))),
                  h(
                    'tbody',
                    {},
                    board.map((r, i) => h('tr', { class: r.me ? 'me' : '' }, h('td', {}, fmtNum(i + 1)), h('td', {}, r.name, r.me ? badge('أنت', 'info') : null), h('td', { class: 'num' }, fmtNum(r.points)), h('td', { class: 'num' }, fmtPct(r.percent / 100)), h('td', { class: 'num' }, fmtNum(r.attempts)))),
                  ),
                ),
              )
            : empty('كن أول من يدخل لوحة الشرف!', 'award'),
        ),
      ),
    );
  }

  async function startQuiz(difficulty) {
    let attempt;
    try {
      attempt = await post('/api/academy/start', { difficulty });
    } catch (error) {
      showError(error);
      return;
    }
    stopTimers();
    viewer = imageViewer(`/api/academy/attempts/${attempt.attempt_id}/image`, 'روشتة التحدي');
    const started = Date.now();
    const clock = h('span', { class: 'badge' }, icon('timer'), '0:00');
    timer = setInterval(() => {
      const s = Math.floor((Date.now() - started) / 1000);
      clock.lastChild.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    }, 1000);

    const rows = [];
    const answersBox = h('div', {});
    for (let i = 0; i < Math.max(1, attempt.items_count); i += 1) {
      const brand = h('input', { class: 'input ltr', dir: 'ltr', placeholder: 'اسم الدواء', 'aria-label': `الدواء ${i + 1}` });
      const strength = h('input', { class: 'input ltr', dir: 'ltr', placeholder: 'التركيز', 'aria-label': 'التركيز' });
      const freq = h('select', { class: 'select', 'aria-label': 'عدد المرات' }, FREQUENCIES.map(([v, t]) => h('option', { value: v }, t)));
      rows.push({ brand, strength, freq });
      answersBox.append(h('div', { class: 'quiz-answer' }, h('span', { class: 'rx-index' }, String(i + 1)), h('div', { class: 'form-grid' }, brand, strength, freq)));
    }
    const submit = button('تسليم الإجابة', { kind: 'primary', iconName: 'check' });
    submit.addEventListener('click', async () => {
      setBusy(submit, true);
      try {
        const answers = rows.map((r) => ({ brand: r.brand.value.trim(), strength: r.strength.value.trim(), times_per_day: r.freq.value ? Number(r.freq.value) : null }));
        const result = await post(`/api/academy/attempts/${attempt.attempt_id}/submit`, { answers });
        clearInterval(timer);
        showResult(result, attempt, answersPanel);
      } catch (error) {
        showError(error);
        setBusy(submit, false);
      }
    });
    const answersPanel = h(
      'div',
      { class: 'card stack' },
      h('div', { class: 'row between' }, h('h2', {}, `اكتب الأدوية (${fmtNum(attempt.items_count)})`), clock),
      attempt.specialty ? h('p', { class: 'muted small' }, `تخصص الطبيب: ${attempt.specialty}`) : null,
      answersBox,
      submit,
    );
    mount(body, h('div', { class: 'editor' }, h('div', { class: 'viewer-col' }, viewer.element), answersPanel));
    rows[0].brand.focus();
  }

  function showResult(result, attempt, panel) {
    const pct = result.percent;
    const kind = pct >= 85 ? 'good' : pct >= 60 ? 'warn' : 'bad';
    const praise = pct >= 85 ? 'ممتاز! عين صيدلي خبير' : pct >= 60 ? 'جيد - راجع الأخطاء أدناه' : 'تحتاج تدريباً أكثر على هذا الخط';
    mount(
      panel,
      h('div', { class: 'row between' }, h('div', {}, h('div', { class: 'score-ring' }, fmtPct(pct / 100)), h('div', { class: 'muted' }, praise)), badge(`${fmtNum(result.seconds)} ثانية`, '', 'timer')),
      alertBox(kind, `النتيجة ${fmtNum(result.score)} من ${fmtNum(result.max_score)}`),
      h(
        'div',
        {},
        result.details.map((d) =>
          h(
            'div',
            { class: 'result-line' },
            h('span', { class: d.name_ok ? 'ok' : 'no' }, icon(d.name_ok ? 'check' : 'x')),
            h(
              'div',
              { class: 'grow' },
              h('div', {}, h('strong', {}, ltr(d.expected.brand)), d.expected.strength ? [' ', ltr(d.expected.strength)] : null),
              d.expected.line_text ? h('div', { class: 'small muted' }, 'مكتوب: ', ltr(d.expected.line_text)) : null,
              d.expected.instructions_ar ? h('div', { class: 'small' }, d.expected.instructions_ar) : null,
              h('div', { class: 'small' }, 'إجابتك: ', d.answer ? ltr([d.answer.brand, d.answer.strength].filter(Boolean).join(' ')) : '—'),
              h('div', { class: 'row small' }, d.strength_ok === null ? null : badge(d.strength_ok ? 'التركيز ✓' : 'التركيز ✗', d.strength_ok ? 'good' : 'bad'), d.freq_ok === null ? null : badge(d.freq_ok ? 'عدد المرات ✓' : 'عدد المرات ✗', d.freq_ok ? 'good' : 'bad')),
            ),
          ),
        ),
      ),
      result.extra_answers.length ? alertBox('warn', 'أدوية زائدة غير موجودة في الروشتة', result.extra_answers.join('، ')) : null,
      h('div', { class: 'row' }, button('روشتة أخرى', { kind: 'primary', iconName: 'refresh', onClick: () => startQuiz('any') }), button('العودة', { onClick: home })),
    );
  }

  root.append(pageHead('أكاديمية رُشد', 'درّب عينك على قراءة خطوط الأطباء - على روشتات حقيقية مراجَعة'), body);
  await home();
  return stopTimers;
}
