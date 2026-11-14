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

## New in v1.3

- **One-click publication-ready histology and IHC images:** pick the stain (H&E, IHC-DAB, Masson, Sirius red, PAS or auto), the source (microscope camera, phone photo through the eyepiece, or auto) and the strength (light, standard, strong). The app crops the black eyepiece ring of phone photos, removes noise and uneven illumination, whitens the slide background, sets black point, mid-tones and saturation to the stain's target, adds mild local contrast and sharpening, and verifies every stage with the integrity check. A before/after slider sits under the image; manual controls are under "Advanced". Quantification is always done on the illumination-corrected original, never on cosmetic edits.
- **Batch histology → statistics:** process a whole folder (groups from sub-folders or file-name prefixes), save the processed images, before/after pictures and edit logs, and send the measurements per image straight to the data sheet.
- **Project files (.msx):** data, every analysis with its settings, edited figures, captions and the histology state in one file; re-run all analyses on corrected data in one click.
- **Target-journal presets:** Elsevier, Springer, Nature Portfolio, Wiley, PLOS, Cell Press, MDPI (column widths, font, dpi, formats).
- **Manuscript builder (Word):** Statistical analysis paragraph, a Results section that cites the numbered tables and figures, APA tables, figure legends and figures at journal size; optional histology methods and an Arabic translation for theses.
- **Statistical report for reviewers:** effect sizes with 95% CI, assumption checks, sensitivity (minimum detectable effect) and a non-parametric robustness check for every analysis.
- **Multi-panel figures:** charts and histology images on one page with A, B, C labels at journal width.
- **Animal-study toolkit:** complete or weight-stratified randomisation, Mead's equation and power-based sample size, Grubbs and ROUT outliers with logged exclusion, and the ARRIVE 2.0 checklist exported to Word.
- **Study templates:** oxidative stress, liver and kidney function, cytokines, apoptosis, histopathology scores, organ weights, LD50 and dose-response entry sheets.
- **Bilingual interpretation:** export the interpretation in English, Arabic or both.

## New in v1.2

- **Prism-style figure editor:** chart type (scatter, bar, box, violin), colour per group and palettes, point size/shape, fonts, axes (range, log), group order, size in mm. Significance: significant pairs, all pairs, versus a reference group or a custom selection; brackets are stacked automatically so they never overlap; stars, exact p or both; standard or GraphPad thresholds; ns on/off; symbols mode (* / #) for many groups.
- **Recommendations after loading data:** a ranked list of the most suitable analyses, each with the reason and a one-click run.
- **Captions:** every table and figure gets an automatic, editable caption, numbered across the whole output.
- **Export:** every statistics figure and histology image at 150, 300, 600 or 1200 dpi as TIFF, PNG, JPEG, PDF, SVG or EPS, optionally at journal column width.
- **Histology image inspection:** 10 checks (uneven illumination, colour cast, exposure/contrast, clipping, mid-tones, faded stain, noise, focus with soft areas, stain vs reference H&E, folds/debris), a 0–100 quality score, problem areas shown on the image, and suggested global corrections the user ticks and applies (or one-click auto-enhance). Every result is verified by the integrity check stage by stage; blur, clipping and folds are only flagged because they cannot be honestly corrected. New global tools: flat-field shading correction (second-order surface fitted to background) and mild unsharp masking.

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
- `dist\installer\MedStatixPro-Setup-1.3.1.exe`, an installer with Start-menu and desktop shortcuts

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
