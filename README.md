# MedStatix Pro

**Advanced medical & pharmaceutical biostatistics for the desktop. | منصة الإحصاء الحيوي الطبي والصيدلي المتقدم**

MedStatix Pro brings together what researchers usually spread across SPSS, GraphPad Prism, R, Stata, MedCalc and G*Power. It has 44 validated analyses, a smart advisor that picks the right test and explains the result in Arabic or English, figures in the style of top (Q1) journals, and Word/Excel tables ready for publication.

---

## الميزات الرئيسية

| | |
|---|---|
| 🧠 **التحليل الذكي** | تختار المتغير التابع والعامل فقط. يتعرف البرنامج على نوع المتغيرات وعدد المجموعات، ويفحص التوزيع الطبيعي (Shapiro-Wilk) وتجانس التباين (Levene) والتكرارات المتوقعة، ثم يختار الاختبار الصحيح ويشغّله ويشرح سبب الاختيار. |
| 🧭 **أي اختبار أستخدم؟** | معالج أسئلة يحدد الاختبار المناسب حسب تصميم الدراسة. |
| 💬 **تفسير ذكي ثنائي اللغة** | يأتي كل تحليل بتفسير مكتوب بلغة واضحة بالعربية أو الإنجليزية، يشمل حجم الأثر والدلالة السريرية. ويأتي معه نص Methods/Results بالإنجليزية جاهز للنسخ إلى البحث. |
| 🎨 **استوديو الرسوم** | نمط GraphPad Prism، وألوان مجلات Nature وScience وLancet وNEJM وJAMA وJCO وBMJ وCell، وOkabe-Ito المناسبة لعمى الألوان. يمكن تعديل العناوين والمحاور، والتصدير إلى TIFF/PNG/SVG/PDF/EPS بدقة 300 أو 600 أو 1200 dpi. |
| 📝 **تقارير جاهزة للنشر** | جداول بنمط APA (ثلاثة خطوط) إلى Word، وكل الجداول إلى Excel، وتقرير HTML. |
| 📂 **استيراد البيانات** | Excel وCSV وSPSS (.sav) وStata (.dta) وSAS، واللصق المباشر من Excel. |
| 🛠 **إدارة البيانات** | حساب متغيرات جديدة، وتحويل لوغاريتمي أو معياري، وإعادة الترميز، وتصفية الحالات، وتحويل البيانات من الشكل العريض إلى الطويل. |
| 🌍 **واجهة عربية/إنجليزية** | دعم كامل لاتجاه الكتابة من اليمين لليسار، مع وضع فاتح وداكن. |

## Analysis catalogue (44)

| Category | Analyses |
|---|---|
| Descriptive | Descriptives (mean, SD, SEM, CI, median, IQR, skewness, kurtosis), frequencies with Wilson CI, normality (Shapiro-Wilk, K-S Lilliefors, D'Agostino, Anderson-Darling, Q-Q), outliers (Grubbs, Tukey, robust MAD) |
| Compare groups | Student/Welch t, paired t, one-sample t, Mann-Whitney, Wilcoxon, one-way ANOVA + Welch + post hoc (Tukey, Bonferroni, Holm, Šidák, **Dunnett**, **Games-Howell**, LSD), Kruskal-Wallis + Dunn, two/three-way ANOVA (Type II/III) with interaction plot, ANCOVA with adjusted means |
| Repeated / clustered | RM-ANOVA (Mauchly, Greenhouse-Geisser, Huynh-Feldt), Friedman, linear mixed models (REML), GEE |
| Categorical | χ², Yates, likelihood ratio, Fisher's exact (also R×C), linear-by-linear, OR/RR/RD/NNT, McNemar, Mantel-Haenszel + Breslow-Day, goodness of fit, proportion calculator |
| Correlation | Pearson, Spearman, Kendall with CIs, heatmap, partial correlation |
| Regression | Linear (β, VIF, diagnostics, HC3), logistic (crude and adjusted OR, Nagelkerke, Hosmer-Lemeshow, AUC, EPV), ordinal, Poisson/negative binomial |
| Survival | Kaplan-Meier with risk table, log-rank, Breslow, Tarone-Ware, median and RMST, Cox PH (Efron) with Schoenfeld test and Harrell's C |
| Diagnostic | ROC (DeLong CI and comparison, Youden cut-off), 2×2 accuracy (Se, Sp, PPV, NPV, LR±, DOR) |
| Agreement | Cohen's κ (weighted), Fleiss' κ, ICC (all 6 forms), Bland-Altman, Cronbach's α |
| Pharmacology & toxicology | **Probit/logit LD50 with Fieller limits**, **4PL EC50/IC50** (Prism-style), Michaelis-Menten, **non-compartmental PK** (Cmax, Tmax, AUC, t½, CL/F, Vz/F) |
| Multivariate | PCA (scree, biplot), hierarchical clustering |
| Meta-analysis | FE/RE (REML, DL), OR/RR/MD/SMD/generic, I², τ², prediction interval, Egger, leave-one-out, forest and funnel plots |
| Sample size | t-tests, proportions, ANOVA, correlation, log-rank (Schoenfeld), diagnostic sensitivity (Buderer), Mead's resource equation for animal studies |

## Histology & IHC studio (v1.1)

A tab for preparing histopathology and immunohistochemistry images for Q1 journals, built around image integrity:

- **Global, disclosed enhancement only:** white balance, brightness/contrast, gamma, saturation, stain normalisation (Reinhard; Macenko for H&E), and mild edge-preserving denoising. There is no local retouching and no generative/AI pixel synthesis. The original image is always kept.
- **Integrity check after every change:** rank-normalised SSIM, edge correlation, nuclear-mask Dice, and a local-edit detector that fits the global colour mapping and flags clustered departures from it (cloning, painting, erasing, local blur). The verdict is shown in green or red.
- **Edit log and Methods paragraph:** exported as JSON and text, ready to paste into the manuscript.
- **Annotation of real structures:** arrows, labels (presets such as inflammatory cells, fibrosis, congestion, necrosis), circles, rectangles, freehand outlines, and a calibrated scale bar (µm/px). There is also a multi-panel composer with A/B/C labels.
- **Quantification:**
  - IHC DAB: % positive area, pixel H-score, % positive nuclei, cell H-score.
  - Fibrosis/collagen % for Masson trichrome, Sirius red and Van Gieson.
  - Inflammatory-cell *suggestions* that the user accepts or rejects one by one.
  - RBC-rich (congestion) area.
  - Measurements are taken on native stain colours and can be sent to the dataset for statistics.

Validation (`tests/test_imaging.py`, real public H&E and IHC images): all 9 legitimate pipelines pass on both H&E images. All 4 kinds of local manipulation are flagged. Fibrosis matches synthetic ground truth exactly.

## Validation

`tests/test_validation.py` compares the engine with published reference outputs: R (`t.test`, `aov`, `TukeyHSD`, `kruskal.test`, `fisher.test`, `cor.test`, `lm`, `glm`, `survdiff`, `coxph`, `power.t.test`, `power.prop.test`), metafor (`rma` REML/DL on the BCG data), Shrout & Fleiss (1979) for ICC, and Dobson's beetle data for probit/logit. **45/45 checks pass.** A smoke test also runs every analysis end to end. Inside the app, open *Help → Validation report*.

```
python -m pytest tests -q
```

## Run from source

```bash
pip install -r requirements.txt
python run_medstatix.py
```

## Build the Windows installer

**Option A, on a Windows PC:** install Python 3.12 (64-bit) and, optionally, [Inno Setup 6](https://jrsoftware.org/isinfo.php), then double-click `build\build_windows.bat`. You get:
- `dist\MedStatixPro\MedStatixPro.exe`, a portable app with no Python needed
- `dist\installer\MedStatixPro-Setup-1.1.0.exe`, an installer with Start-menu and desktop shortcuts

**Option B, automatically on GitHub:** push this folder to a GitHub repository. The workflow `.github/workflows/build-windows.yml` builds the installer and a portable ZIP on Windows. Run it from the *Actions* tab, or push a tag such as `v1.0.0` to publish a release.

macOS and Linux: the same command `pyinstaller build/medstatix.spec` produces a native app.

## Project layout

```
medstatix/
  analyses/      44 analyses, declared in a registry (dialogs are generated automatically)
  core/          data import, result model, settings, smart advisor
  plots/         journal-style figure engine (Prism look, journal palettes)
  report/        Word / Excel / HTML / figure export
  ui/            PySide6 desktop interface (Arabic/English, light/dark)
tests/           validation against reference software
build/           PyInstaller spec, Windows build script, Inno Setup installer
```
