"""Bilingual (Arabic / English) user-interface strings."""
from ..core.settings import SETTINGS

S = {
    "app_tagline": ("Advanced medical & pharmaceutical biostatistics", "الإحصاء الحيوي الطبي والصيدلي المتقدم"),
    "file": ("&File", "&ملف"), "data": ("&Data", "&البيانات"), "analyze": ("&Analyze", "&التحليل"),
    "output": ("&Output", "&المخرجات"), "view": ("&View", "&عرض"), "help": ("&Help", "&مساعدة"),
    "open": ("Open data…", "فتح ملف بيانات…"), "save": ("Save data as…", "حفظ البيانات باسم…"),
    "new": ("New empty dataset", "ملف بيانات جديد"), "paste": ("Paste from clipboard (Excel)", "لصق من الحافظة (إكسل)"),
    "samples": ("Sample datasets", "بيانات نموذجية"), "exit": ("Exit", "خروج"),
    "smart": ("Smart Analyze", "التحليل الذكي"), "wizard": ("Which test?", "أي اختبار أستخدم؟"),
    "export_word": ("Export Word", "تصدير Word"), "export_excel": ("Export Excel", "تصدير Excel"),
    "export_html": ("Export HTML", "تصدير HTML"), "settings": ("Figure and app settings", "إعدادات الرسوم والبرنامج"),
    "language": ("العربية / English", "English / العربية"), "clear_output": ("Clear output", "مسح المخرجات"),
    "tab_data": ("Data", "البيانات"), "tab_vars": ("Variables", "المتغيرات"), "tab_output": ("Results", "النتائج"),
    "tab_figs": ("Figures studio", "استوديو الرسوم"),
    "search": ("Search analyses…", "ابحث عن تحليل…"),
    "run": ("Run", "تشغيل"), "cancel": ("Cancel", "إلغاء"), "ok": ("OK", "موافق"),
    "rows_cols": ("{r} rows × {c} variables", "{r} صف × {c} متغير"),
    "no_data": ("Open or paste a dataset first (File → Open, or Sample datasets).", "افتح أو الصق ملف بيانات أولًا (ملف ← فتح، أو البيانات النموذجية)."),
    "error": ("Analysis error", "خطأ في التحليل"), "done": ("Analysis complete", "اكتمل التحليل"),
    "compute": ("Compute new variable…", "حساب متغير جديد…"), "transform": ("Transform (log, z-score, rank…)…", "تحويل المتغير (لوغاريتم، درجة معيارية…)…"),
    "recode": ("Recode into groups (cut-offs)…", "إعادة الترميز إلى فئات…"), "filter": ("Select cases (filter)…", "اختيار الحالات (تصفية)…"),
    "wide_long": ("Restructure wide → long…", "إعادة الهيكلة من عريض إلى طويل…"), "reset_filter": ("Restore all cases", "استعادة كل الحالات"),
    "add_row": ("Add row", "إضافة صف"), "del_row": ("Delete selected rows", "حذف الصفوف المحددة"),
    "add_col": ("Add variable", "إضافة متغير"), "del_col": ("Delete variable", "حذف متغير"),
    "fig_title": ("Title", "العنوان"), "fig_x": ("X-axis label", "عنوان المحور السيني"), "fig_y": ("Y-axis label", "عنوان المحور الصادي"),
    "fig_ymin": ("Y min", "أدنى Y"), "fig_ymax": ("Y max", "أعلى Y"), "apply": ("Apply", "تطبيق"),
    "restyle": ("Re-draw with current style and palette", "إعادة الرسم بالنمط والألوان الحالية"),
    "export_fig": ("Export figure…", "تصدير الرسم…"), "export_all_figs": ("Export all figures…", "تصدير كل الرسوم…"),
    "palette": ("Journal palette", "ألوان المجلة"), "style": ("Figure style", "نمط الرسم"),
    "plot_type": ("Group plot type", "نوع رسم المجموعات"), "error_bar": ("Error bars", "أشرطة الخطأ"),
    "font": ("Font", "الخط"), "font_size": ("Font size", "حجم الخط"), "width": ("Width (mm)", "العرض (مم)"),
    "height": ("Height (mm)", "الارتفاع (مم)"), "dpi": ("Export resolution (dpi)", "دقة التصدير (نقطة/بوصة)"),
    "show_sig": ("Show significance brackets", "إظهار أقواس الدلالة"), "theme": ("Theme", "المظهر"),
    "ui_lang": ("Interface language", "لغة الواجهة"),
    "outcome_q": ("Outcome (dependent) variable", "المتغير التابع"), "factor_q": ("Group / predictor (optional)", "المجموعة / المتغير المستقل (اختياري)"),
    "smart_desc": ("Choose your variables: the advisor checks variable types, number of groups, normality and variances, "
                   "then selects, runs and explains the correct test.",
                   "اختر المتغيرات: يفحص المساعد نوع المتغيرات وعدد المجموعات والتوزيع الطبيعي وتجانس التباين، ثم يختار الاختبار الصحيح ويشغّله ويفسّره."),
    "wizard_desc": ("Answer a few questions about your study design.", "أجب عن بعض الأسئلة حول تصميم دراستك."),
    "back": ("◀ Back", "رجوع ▶"), "open_analysis": ("Open this analysis", "فتح هذا التحليل"),
    "recommend": ("Recommended", "الموصى به"), "about": ("About", "حول البرنامج"),
    "validation": ("Validation report", "تقرير التحقق من الدقة"), "copy_table": ("Copy", "نسخ"),
    "status_ready": ("Ready", "جاهز"), "none": ("— none —", "— لا يوجد —"),
    "expr_help": ("Expression using variable names, e.g.  (SBP_0 - SBP_8) / SBP_0 * 100   or   log(CRP)",
                  "تعبير يستخدم أسماء المتغيرات، مثل  (SBP_0 - SBP_8) / SBP_0 * 100   أو   log(CRP)"),
    "new_name": ("New variable name", "اسم المتغير الجديد"), "expression": ("Expression", "التعبير"),
    "condition": ("Keep cases where (e.g.  age >= 40 and sex == 'Male')", "الإبقاء على الحالات حيث (مثل  age >= 40 and sex == 'Male')"),
    "variable": ("Variable", "المتغير"), "method": ("Method", "الطريقة"), "cutoffs": ("Cut-offs (comma separated)", "نقاط القطع (مفصولة بفواصل)"),
    "labels": ("Labels (comma separated, optional)", "التسميات (مفصولة بفواصل، اختياري)"),
    "id_var": ("Subject ID variable", "متغير رقم الحالة"), "measures": ("Repeated measure columns", "أعمدة القياسات المتكررة"),
    "type": ("Type", "النوع"), "name": ("Name", "الاسم"), "n_valid": ("Valid n", "العدد الصالح"), "missing": ("Missing", "المفقود"),
    "levels": ("Levels / range", "المستويات / المدى"), "role": ("Detected as", "التصنيف"),
}


def tr(key: str, **kw) -> str:
    en, ar = S.get(key, (key, key))
    s = ar if SETTINGS.language == "ar" else en
    return s.format(**kw) if kw else s


def lbl(obj) -> str:
    """Label for registry objects with .en/.ar attributes."""
    return obj.ar if SETTINGS.language == "ar" else obj.en
