// Arabic labels for the values the API uses.

export const ROLES = {
  admin: 'مدير النظام',
  trainer: 'مدرب',
  pharmacist: 'صيدلي',
  trainee: 'متدرب',
};

export const STATUSES = {
  queued: { label: 'في الانتظار', kind: '' },
  processing: { label: 'جاري القراءة', kind: 'info' },
  needs_review: { label: 'تحتاج مراجعة', kind: 'warn' },
  verified: { label: 'معتمدة', kind: 'good' },
  rejected: { label: 'مرفوضة', kind: '' },
  failed: { label: 'فشلت القراءة', kind: 'bad' },
};

export const FORMS = {
  tablet: 'أقراص',
  chewable_tablet: 'أقراص للمضغ',
  effervescent: 'فوار',
  capsule: 'كبسولات',
  syrup: 'شراب',
  suspension: 'معلق',
  drops: 'نقط بالفم',
  sachet: 'أكياس',
  lozenge: 'أقراص استحلاب',
  ampoule: 'أمبول (حقن)',
  vial: 'فيال (حقن)',
  infusion: 'محلول وريدي',
  prefilled_syringe: 'سرنجة جاهزة',
  pen: 'قلم حقن',
  suppository: 'لبوس',
  vaginal_tablet: 'أقراص مهبلية',
  cream: 'كريم',
  ointment: 'مرهم',
  gel: 'جل',
  lotion: 'لوشن',
  shampoo: 'شامبو',
  oral_gel: 'جل للفم',
  eye_drops: 'قطرة عين',
  eye_ointment: 'مرهم عين',
  ear_drops: 'قطرة أذن',
  nasal_spray: 'بخاخ أنف',
  nasal_drops: 'نقط أنف',
  inhaler: 'بخاخ استنشاق',
  nebulizer: 'جلسات استنشاق',
  mouthwash: 'غسول فم',
  solution: 'محلول',
  other: 'أخرى',
};

export const TIMINGS = {
  before_meal: 'قبل الأكل',
  after_meal: 'بعد الأكل',
  with_meal: 'مع الأكل',
  empty_stomach: 'على الريق',
  bedtime: 'قبل النوم',
  morning: 'صباحاً',
  evening: 'مساءً',
};

export const FREQUENCIES = [
  ['', '—'],
  ['1', 'مرة يومياً'],
  ['2', 'مرتين يومياً'],
  ['3', '٣ مرات يومياً'],
  ['4', '٤ مرات يومياً'],
  ['6', '٦ مرات يومياً'],
  ['0.5', 'يوم بعد يوم'],
  ['0.143', 'مرة أسبوعياً'],
];

export const FLAGS = {
  not_in_database: 'غير موجود في قاعدة الأدوية',
  strength_unusual: 'تركيز غير معتاد لهذا الدواء',
  form_unusual: 'شكل دوائي غير معتاد',
  ambiguous_name: 'اسم قريب من دواء آخر',
  learned_correction: 'تعلّمها النظام من تصحيح سابق',
  new_drug: 'أضيف لقاعدة الأدوية',
};

export const LEVELS = {
  high: { label: 'ثقة عالية', kind: 'good', icon: 'check' },
  medium: { label: 'راجعها', kind: 'warn', icon: 'alert' },
  low: { label: 'غير واضحة', kind: 'bad', icon: 'x' },
};

export const WARNING_LEVELS = {
  contraindicated: { label: 'ممنوع', kind: 'bad' },
  major: { label: 'مهم', kind: 'bad' },
  moderate: { label: 'تنبيه', kind: 'warn' },
};

export const ENGINE_MODES = {
  cloud: { label: 'سحابي (Claude)', hint: 'أعلى دقة من اليوم الأول؛ الصور تُرسل مشفرة للخدمة السحابية.' },
  local: { label: 'محلي بالكامل', hint: 'لا يخرج شيء من الخادم - يحتاج نموذجاً مدرَّباً ومفعَّلاً.' },
  local_first: { label: 'محلي أولاً', hint: 'النموذج المحلي يقرأ، والسحابة تُستشار فقط عند الشك.' },
  shadow: { label: 'سحابي + قياس المحلي', hint: 'السحابة تقرأ، والنموذج المحلي يُختبر في الخلفية لقياس دقته.' },
};

export const EFFORTS = { low: 'سريع', medium: 'متوازن (موصى به)', high: 'مدقق', xhigh: 'مدقق جداً', max: 'أقصى تدقيق' };

export const AUDIT_ACTIONS = {
  login_success: 'تسجيل دخول',
  login_failed: 'محاولة دخول فاشلة',
  account_locked: 'قفل حساب',
  logout: 'تسجيل خروج',
  password_changed: 'تغيير كلمة المرور',
  password_change_failed: 'فشل تغيير كلمة المرور',
  password_reset: 'إعادة تعيين كلمة مرور',
  totp_enabled: 'تفعيل التحقق بخطوتين',
  totp_disabled: 'إيقاف التحقق بخطوتين',
  totp_reset: 'إعادة ضبط التحقق بخطوتين',
  session_revoked: 'إنهاء جلسة',
  sessions_revoked: 'إنهاء كل الجلسات',
  user_created: 'إنشاء مستخدم',
  user_updated: 'تعديل مستخدم',
  user_unlocked: 'فك قفل مستخدم',
  branch_created: 'إضافة فرع',
  prescription_uploaded: 'رفع روشتة',
  prescription_viewed: 'عرض روشتة',
  prescription_verified: 'اعتماد روشتة',
  prescription_reverified: 'تعديل روشتة معتمدة',
  prescription_rejected: 'رفض روشتة',
  prescription_deleted: 'حذف روشتة',
  batch_uploaded: 'رفع دفعة',
  archive_imported: 'استيراد أرشيف',
  drug_created: 'إضافة دواء',
  drug_updated: 'تعديل دواء',
  drug_deactivated: 'إيقاف دواء',
  drugs_imported: 'استيراد أدوية',
  doctor_saved: 'حفظ طبيب',
  doctor_updated: 'تعديل طبيب',
  doctor_merged: 'دمج أطباء',
  training_started: 'بدء تدريب',
  training_cancelled: 'إيقاف تدريب',
  model_trained: 'اكتمال تدريب نموذج',
  model_activated: 'تفعيل نموذج',
  model_deactivated: 'إيقاف النموذج المحلي',
  dataset_exported: 'تصدير بيانات التدريب',
  model_exported: 'تصدير نموذج محلي',
  model_imported: 'استيراد نموذج محلي',
  step_up: 'تأكيد الهوية لإجراء حساس',
  settings_changed: 'تغيير الإعدادات',
  audit_verified: 'فحص سجل الأمان',
};
