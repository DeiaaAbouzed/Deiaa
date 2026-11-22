# MedStatix Pro

**Advanced medical & pharmaceutical biostatistics for the desktop. | منصة الإحصاء الحيوي الطبي والصيدلي المتقدم**

MedStatix Pro brings together what researchers usually spread across SPSS, GraphPad Prism, R, Stata, MedCalc and G*Power. It has 53 validated analyses, a smart advisor that picks the right test and explains the result in Arabic or English, figures in the style of top (Q1) journals, and Word/Excel tables ready for publication.

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

## Analysis catalogue (53)

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
| Bayesian | JZS Bayes factor t-tests (independent, paired, one-sample), Bayesian correlation, Bayesian ANOVA (BIC) |
| Charts | Heatmap, volcano, radar, Kaplan–Meier, forest |
| Sample size | **G*Power-style a priori / post hoc / sensitivity**, t-tests, proportions, ANOVA, correlation, log-rank (Schoenfeld), diagnostic sensitivity (Buderer), Mead's resource equation for animal studies |

## New in v2.2: a better full paper, optional Claude writing, automatic references
- **Writing mode** (Write the full paper → Output tab): *Templates only*, or *Claude* with your Anthropic API key. Claude
  writes Highlights, Abstract, Introduction, Results text, Discussion and Conclusion from your data and references only.
  Numbers that are not in your data are flagged `[check: …]`, unknown citations become `[ref]`, the Methods stay as built
  from the data, and an AI-use declaration is added.
- **Automatic references**: when the list has fewer than 15, the app searches PubMed (model, compound, each measured
  pathway) and adds them; a reference list is always written.
- Results come from the multi-marker summary (one section), per-test tables go to *Supplementary material*, one
  statistics paragraph, marker-specific Discussion sentences, IQR on median bar charts.

## New in v2.1.1: the newest tools on the toolbar
Next to **⭐ Recommendations** on the toolbar: **📚 Full paper**, **🖼 Improve images** (Ctrl+Shift+I), **📝 Pro comment**
(Ctrl+Shift+C, after the AI reader) and a **✨ New tools** menu that also holds the folder histopathology report, brush
teaching of congestion and the **Expert mode** switch. Open/save, export, Settings and Language sit on a second toolbar row.

## New in v2.1: Write the full paper
`report/paper.py`, `report/refs.py`, `report/markers_kb.py`, `ui/paper_ui.py`: a complete manuscript (abstract → declarations, tables, legends, figures) from the study data and fixed templates, without a language model; author-only statements are highlighted prompts. PubMed search (E-utilities), RIS import/export, EndNote temporary citations or Vancouver/APA lists.

## New in v2.0
- **Expert mode** (Settings or the Research images tab): wider histology/IHC adjustment ranges, every tool on blots/gels, enlargement to ×8, write-dpi-only export. All edits stay logged and disclosed.
- **Professional histopathology comments** (`report/histo_comment.py`): pathologist-style description with 0–3 grades on stated criteria, figure legend (EN/AR), and a batch `histopathology_report.txt` with group statistics.

## New in v1.9: Research images studio
A tab for every figure that is not a histology slide: photographs, Western blots/gels, graphs and screenshots, scans and fluorescence images (`imaging/general.py`, `ui/figure_studio.py`). Type detection, one-click recipes (blots: linear only, no clipping), global adjustments, straightening, border removal, print sizing by column width and dpi with a readiness report, faithful enlargement (Lanczos + unsharp + iterative back-projection, ≤ ×4) with the real dpi written to the file, RGB/greyscale/CMYK export, folder processing with edit logs and methods text.

## New in v1.8
- **One-click Results section** written from the Journal summary table (English and Arabic): model vs control with fold or % change, each treatment's % recovery and normalisation, dose comparison and an overall synthesis; also in Word and the manuscript draft.
- **Congestion learned from a brush**: paint red cells and look-alike tissue on ~10 images; a colour + multi-scale texture pixel classifier (NumPy MLP) is validated leave-one-image-out and used only when it beats the colour rule (`imaging/rbc_learn.py`, `ui/congestion_ui.py`).
- **Faster teaching of the cell reader**: lasso labelling, uncertainty-based suggestions, tubular/glomerular labels, and a rodent inflammatory gate refitted on the user's labels when it is better on held-out images.
- **Study colour reference in batch processing**: every image matched to one reference image (global Reinhard), drawn marks preserved, disclosed in methods.txt.

## New in v1.7: MedStatix Signature outputs

- **Signature tables** (Settings → Output; APA and SPSS remain available): indigo header band with a crimson rule, light zebra rows, significant p values in bold crimson, in the app and in Word with fitted column widths.
- **Signature figures and palette**: control / sham / vehicle groups in neutral greys, the disease model in crimson, treatments in distinct cool hues; white-edged points, hairline y grid.
- **Journal summary table** (`journal_table`): markers × groups, mean ± SD (or median (IQR)) with * versus control and # versus the disease model, plus a multi-panel A/B/C figure. Added automatically when Smart Analyze runs on several markers.
- Groups keep the order of the experimental design; captions name the test actually used with its statistic, df, p and effect size.

## New in v1.6: AI reader for rodent tissue

- **Scale bar (1.6.1)**: pixel size from a saved calibration per objective or read from the bar already on the image; automatic round length, position, black/white style with or without a box; batch processing adds a calibrated bar to every saved image (never a second one).

- **Calibration from the figure itself**: the scale bar drawn on a photomicrograph is found, its length measured and its label read (5–1000 µm); nuclei are then detected at the model's working resolution (0.25 µm/px). At 10× and 20× this finds 5–40 times more nuclei than v1.5.
- **Drawn marks are ignored**: arrows, arrowheads, stars, letters and the scale-bar box are masked out of every measurement, and one-click enhancement keeps them unchanged (disclosed in the methods text).
- **Tissue profiles**: *Rat/mouse kidney*, *Other rodent tissue* and *Human/other*. The rodent profiles add a calibrated inflammatory-cell filter (logistic model on the built-in probability and the local density of dark nuclei) trained on 22 rat kidney and skeletal-muscle H&E images with weak labels (the pathologist's arrows and "normal" legends). Leave-one-image-out: AUC 0.86 vs 0.81; false positives in normal muscle ~2 vs ~690 per mm², in normal kidney ~450 vs ~3300 per mm²; recall at the arrows 0.53–0.55 vs 0.87–0.90. Only the model weights are distributed, never the images.
- **Glomeruli** (kidney profile, ≥ 20×): recognised from Bowman's space; tuft and Bowman's space areas are reported and glomerular nuclei are excluded from the inflammatory cells.
- **Smart advisor**: histopathological lesion scores (integer grades) are analysed with Kruskal–Wallis + Dunn (or Mann–Whitney), reported as median (IQR), instead of chi-square; with unequal variances, normality is judged on group-standardised residuals and Welch ANOVA + Games–Howell is used.

## New in v1.5

- **SPSS and GraphPad Prism files:** open and save `.sav` (value labels and variable labels are kept) and `.pzfx` (Column, Grouped, XY and summary-data tables; one Prism Column table per outcome on export).
- **SPSS-style tables** (Settings → Table style) next to APA tables, and a **Word validation report** (Help → Validation) with 53 checks against R, metafor, BayesFactor and G*Power plus a formula-equivalence table for SPSS and Prism.
- **Bayesian statistics:** JZS Bayes factors for t-tests (independent, paired, one-sample) with a prior-robustness plot, Bayesian correlation and BIC-based Bayesian ANOVA (validated against the R package BayesFactor).
- **G*Power-style power analysis:** a priori, post hoc and sensitivity for t, F (ANOVA, regression), χ², correlation and two proportions, with the H0/H1 distribution plot and the power curve.
- **Chart library:** heatmap (z-scored group means or correlation, clustered), volcano plot (fold change vs FDR), radar chart, Kaplan–Meier and custom forest plot.
- **Automatic assumption checks:** when normality fails after a t-test, ANOVA or Pearson correlation, the matching non-parametric test (Mann–Whitney, Wilcoxon, Kruskal–Wallis + Dunn, Spearman) is added with an explanation in English and Arabic (can be turned off in Settings).
- **R bridge:** Tools → *Verify last analysis in R* re-runs it in R (t-tests, ANOVA, non-parametric tests, correlation, regression, `lmerTest` mixed models, `geepack` GEE) and *R console* runs any R code on the current data. Requires R to be installed.
- **Image integrity:** *Open in Photopea* (panels and text only, with a warning) and *Check image returned from Photopea*, which finds the image inside the figure and separates added labels from local changes of the tissue; a **duplicate / re-used image detector** (rotated, mirrored, cropped or rescaled copies across images and copy-move cloning inside one image).
- **Analysis assistant (Ctrl+K):** type a request in Arabic or English ("قارن MDA بين المجموعات", "correlation between ALT and AST", "heatmap") and it runs the analysis, the figure and the text. It works offline.
- **Teach the AI reader on your slides:** label nuclei on your own images (for example rat liver or kidney); the nucleus-type network is fine-tuned from its built-in weights and only activated when grouped cross-validation shows it is at least as good. Labels stay on the computer.
- **In-app update:** checks GitHub releases at startup (optional) or from Help → Check for updates, downloads the installer and restarts.

## New in v1.4: AI image reader

- **Nuclei found by deep learning:** the pretrained StarDist 2D "versatile H&E" model (Schmidt et al., MICCAI 2018; BSD-3) runs offline through ONNX Runtime. Its output matches the reference TensorFlow implementation (F1 0.998–1.0 on the sample images). Low-magnification images are enlarged automatically so that nuclei reach the size the model was trained on.
- **Nucleus types:** a small neural network trained on the CoNSeP dataset (Graham et al., Medical Image Analysis 2019) classifies each nucleus as inflammatory, epithelial, spindle or other. On the 14 held-out CoNSeP test images, inflammatory cells reach precision 0.78, recall 0.73 and F1 0.77. Accuracy is lower on other tissues and species, which is why every result is a suggestion.
- **Suggested labels:** inflammatory cells, inflammatory infiltrate foci, congestion (RBC-rich areas), optional vacuoles/fat (experimental) and, for IHC, DAB-positive nuclei graded per cell with thresholds set from the negative nuclei of the same image. Each suggestion carries a confidence. Delete the wrong ones and press Accept: labels and arrows are placed automatically and the confirmed counts go to the data sheet.
- **Plain-language reading** in English and Arabic, plus a Methods paragraph with references, added to the results and the Word report.
- The models only read the image; they never change pixels. Training data (MoNuSeg, TNBC, CoNSeP) are for research use; cite the references in publications.

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

`tests/test_validation.py` compares the engine with published reference outputs: R (`t.test`, `aov`, `TukeyHSD`, `kruskal.test`, `fisher.test`, `cor.test`, `lm`, `glm`, `survdiff`, `coxph`, `power.t.test`, `power.prop.test`), metafor (`rma` REML/DL on the BCG data), Shrout & Fleiss (1979) for ICC, and Dobson's beetle data for probit/logit. Since v1.5 it also checks the JZS Bayes factors (R BayesFactor) and sample sizes from G*Power 3.1. **53/53 checks pass.** A smoke test also runs every analysis end to end. Inside the app, open *Help → Validation report*.

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
- `dist\installer\MedStatixPro-Setup-1.4.0.exe`, an installer with Start-menu and desktop shortcuts

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
