// Live preview of the Arabic patient instruction while the pharmacist edits.
// Mirrors backend/rushd/ai/sig.py (the server's text is what gets saved).

const AR = '٠١٢٣٤٥٦٧٨٩';
export const arDigits = (s) => String(s).replace(/(\d)\.(\d)/g, '$1٫$2').replace(/\d/g, (d) => AR[d]);
const fmt = (n) => arDigits(Number(n).toString());

const UNITS = {
  tablet: ['قرص', 'قرصين', 'أقراص', true],
  capsule: ['كبسولة', 'كبسولتين', 'كبسولات', false],
  drop: ['نقطة', 'نقطتين', 'نقط', false],
  puff: ['بخة', 'بختين', 'بخات', false],
  sachet: ['كيس', 'كيسين', 'أكياس', true],
  suppository: ['لبوس', 'لبوسين', 'لبوس', true],
  ampoule: ['حقنة', 'حقنتين', 'حقن', false],
  vial: ['فيال', 'فيالين', 'فيالات', true],
  teaspoon: ['معلقة صغيرة', 'معلقتين صغيرتين', 'معالق صغيرة', false],
  tablespoon: ['معلقة كبيرة', 'معلقتين كبيرتين', 'معالق كبيرة', false],
};

export const FORM_DEFAULTS = {
  tablet: ['tablet', 'oral'], chewable_tablet: ['tablet', 'oral'], effervescent: ['tablet', 'oral'],
  capsule: ['capsule', 'oral'], syrup: ['ml', 'oral'], suspension: ['ml', 'oral'], drops: ['drop', 'oral'],
  sachet: ['sachet', 'oral'], lozenge: ['tablet', 'oral'], ampoule: ['ampoule', 'im'], vial: ['vial', 'im'],
  infusion: ['vial', 'iv'], prefilled_syringe: ['ampoule', 'sc'], pen: ['ampoule', 'sc'],
  suppository: ['suppository', 'rectal'], vaginal_tablet: ['tablet', 'vaginal'], cream: ['application', 'topical'],
  ointment: ['application', 'topical'], gel: ['application', 'topical'], lotion: ['application', 'topical'],
  shampoo: ['application', 'topical'], oral_gel: ['application', 'oral'], eye_drops: ['drop', 'eye'],
  eye_ointment: ['application', 'eye'], ear_drops: ['drop', 'ear'], nasal_spray: ['puff', 'nose'],
  nasal_drops: ['drop', 'nose'], inhaler: ['puff', 'inhalation'], nebulizer: ['ml', 'inhalation'],
  mouthwash: ['ml', 'oral'], solution: ['ml', 'oral'],
};

const ROUTES = {
  oral: '', eye: 'في العين', ear: 'في الأذن', nose: 'في الأنف', topical: 'دهان موضعي على المكان المصاب',
  inhalation: 'استنشاق', im: 'بالعضل', iv: 'بالوريد', sc: 'تحت الجلد', rectal: 'شرجي', vaginal: 'مهبلي', sublingual: 'تحت اللسان',
};
const TIMING = { before_meal: 'قبل الأكل', after_meal: 'بعد الأكل', with_meal: 'مع الأكل', empty_stomach: 'على الريق', bedtime: 'قبل النوم', morning: 'صباحاً', evening: 'مساءً' };

function dose(amount, unit) {
  if (!unit) return amount ? fmt(amount) : '';
  if (unit === 'ml') return amount ? `${fmt(amount)} مل` : '';
  if (unit === 'application') return '';
  const [one, two, many, masculine] = UNITS[unit] || [unit, unit, unit, true];
  if (amount === null || amount === undefined || amount === '') return one;
  const a = Number(amount);
  if (a === 0.25) return `ربع ${one}`;
  if (a === 0.5) return `نصف ${one}`;
  if (a === 1) return `${one} ${masculine ? 'واحد' : 'واحدة'}`;
  if (a === 1.5) return `${one} ونصف`;
  if (a === 2) return two;
  if (Number.isInteger(a) && a >= 3 && a <= 10) return `${fmt(a)} ${many}`;
  return `${fmt(a)} ${one}`;
}

function freq(s) {
  if (s.stat) return 'جرعة واحدة فوراً';
  const t = s.times_per_day === null || s.times_per_day === undefined || s.times_per_day === '' ? null : Number(s.times_per_day);
  let parts = [];
  if (t !== null) {
    if (Math.abs(t - 0.5) < 1e-6) parts.push('يوم بعد يوم');
    else if (Math.abs(t - 1 / 7) < 0.01) parts.push('مرة واحدة أسبوعياً');
    else if (t === 1) parts.push('مرة واحدة يومياً');
    else if (t === 2) parts.push('مرتين يومياً');
    else parts.push(`${fmt(t)} ${Number.isInteger(t) ? 'مرات' : 'مرة'} يومياً`);
    const interval = s.interval_hours || ([2, 3, 4, 6].includes(t) ? 24 / t : null);
    if (interval && interval < 24 && t >= 2) parts.push(`(كل ${fmt(interval)} ${interval > 10 || interval === 1 ? 'ساعة' : 'ساعات'})`);
  }
  if (s.prn) parts = ['عند اللزوم', ...(parts.length ? [`بحد أقصى ${parts[0]}`] : [])];
  return parts.join(' ');
}

function duration(days) {
  if (!days) return '';
  const d = Number(days);
  const special = { 1: 'يوم واحد', 2: 'يومين', 7: 'أسبوع', 14: 'أسبوعين', 21: '٣ أسابيع', 30: 'شهر', 60: 'شهرين', 90: '٣ شهور' };
  if (special[d]) return `لمدة ${special[d]}`;
  if (Number.isInteger(d) && d >= 3 && d <= 10) return `لمدة ${fmt(d)} أيام`;
  return `لمدة ${fmt(d)} يوماً`;
}

export function instructions(sig, form) {
  const [unitDefault, routeDefault] = FORM_DEFAULTS[form] || [null, null];
  const s = { ...sig };
  s.dose_unit = s.dose_unit || unitDefault;
  s.route = s.route || routeDefault;
  if ((s.dose_amount === null || s.dose_amount === undefined || s.dose_amount === '') && (s.times_per_day || s.prn || s.stat) && !['ml', 'application', null, undefined].includes(s.dose_unit)) {
    s.dose_amount = 1;
  }
  return [dose(s.dose_amount, s.dose_unit), ROUTES[s.route] || '', freq(s), TIMING[s.timing] || '', duration(s.duration_days)]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}
