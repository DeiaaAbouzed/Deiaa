"""Validation of MedStatix Pro against published reference values (R, SPSS, metafor, Shrout & Fleiss).

Run:  python -m pytest tests/ -q      or      python tests/test_validation.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")

from medstatix.analyses import run  # noqa: E402
from medstatix.core.data import make_sample_datasets  # noqa: E402

RESULTS = []


def check(name, got, ref, tol, source):
    ok = abs(float(got) - float(ref)) <= tol
    RESULTS.append((name, float(got), float(ref), tol, "PASS" if ok else "FAIL", source))
    assert ok, f"{name}: got {got}, expected {ref} ± {tol}"


def tval(res, table_idx, row, col):
    return res.tables[table_idx].content.iloc[row][col]


SLEEP = pd.DataFrame({"extra": [0.7, -1.6, -0.2, -1.2, -0.1, 3.4, 3.7, 0.8, 0.0, 2.0,
                                1.9, 0.8, 1.1, 0.1, -0.1, 4.4, 5.5, 1.6, 4.6, 3.4],
                      "group": ["1"] * 10 + ["2"] * 10})
MPG = [21.0, 21.0, 22.8, 21.4, 18.7, 18.1, 14.3, 24.4, 22.8, 19.2, 17.8, 16.4, 17.3, 15.2, 10.4, 10.4, 14.7, 32.4, 30.4, 33.9,
       21.5, 15.5, 15.2, 13.3, 19.2, 27.3, 26.0, 30.4, 15.8, 19.7, 15.0, 21.4]
WT = [2.620, 2.875, 2.320, 3.215, 3.440, 3.460, 3.570, 3.190, 3.150, 3.440, 3.440, 4.070, 3.730, 3.780, 5.250, 5.424, 5.345,
      2.200, 1.615, 1.835, 2.465, 3.520, 3.435, 3.840, 3.845, 1.935, 2.140, 1.513, 3.170, 2.770, 3.570, 2.780]
AM = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1]
MTCARS = pd.DataFrame({"mpg": MPG, "wt": WT, "am": AM})
DS = make_sample_datasets()


def test_welch_t():  # R: t.test(extra ~ group, data = sleep)
    r = run("ttest_ind", SLEEP, outcome="extra", group="group")
    check("Welch t (sleep)", tval(r, 1, 1, "t"), -1.8608, 0.0005, "R t.test(sleep)")
    check("Welch df (sleep)", tval(r, 1, 1, "df"), 17.776, 0.001, "R t.test(sleep)")
    check("Welch p (sleep)", tval(r, 1, 1, "p"), 0.07939, 0.00002, "R t.test(sleep)")


def test_paired_t():  # R: t.test(sleep$extra[1:10], sleep$extra[11:20], paired=TRUE)
    d = pd.DataFrame({"a": SLEEP.extra[:10].values, "b": SLEEP.extra[10:].values})
    r = run("ttest_paired", d, var1="a", var2="b")
    check("Paired t (sleep)", tval(r, 1, 0, "t"), -4.0621, 0.0005, "R t.test paired")
    check("Paired p (sleep)", tval(r, 1, 0, "p"), 0.002833, 0.000005, "R t.test paired")


def test_anova_tukey():  # R: aov(weight ~ group, PlantGrowth); TukeyHSD
    r = run("anova1", DS["PlantGrowth (ANOVA)"], outcome="weight", group="group", posthoc="Tukey HSD")
    check("ANOVA F (PlantGrowth)", tval(r, 1, 0, "F"), 4.846088, 0.0001, "R aov")
    check("ANOVA p (PlantGrowth)", tval(r, 1, 0, "p"), 0.01591, 0.00002, "R aov")
    ph = r.tables[4].content
    check("Tukey p trt1-ctrl", ph.iloc[0]["p (adj.)"], 0.3908711, 0.0005, "R TukeyHSD")
    check("Tukey p trt2-ctrl", ph.iloc[1]["p (adj.)"], 0.1979960, 0.0005, "R TukeyHSD")
    check("Tukey p trt2-trt1", ph.iloc[2]["p (adj.)"], 0.0120064, 0.0002, "R TukeyHSD")


def test_kruskal():  # R: kruskal.test(weight ~ group, PlantGrowth)
    r = run("kruskal", DS["PlantGrowth (ANOVA)"], outcome="weight", group="group")
    check("Kruskal H", tval(r, 1, 0, "H (χ²)"), 7.9882, 0.0005, "R kruskal.test")
    check("Kruskal p", tval(r, 1, 0, "p"), 0.01842, 0.00005, "R kruskal.test")


def test_fisher():  # R: fisher.test(matrix(c(3,1,1,3),2)) — tea tasting
    d = pd.DataFrame({"guess": ["Milk"] * 4 + ["Tea"] * 4, "truth": ["Milk"] * 3 + ["Tea"] + ["Milk"] + ["Tea"] * 3})
    r = run("chisq", d, row="guess", col="truth")
    t = r.tables[1].content
    check("Fisher exact p (tea)", t[t.Test == "Fisher's exact test"].p.iloc[0], 0.4857, 0.0001, "R fisher.test")


def test_correlation():  # R: cor.test(mtcars$mpg, mtcars$wt)
    r = run("correlation", MTCARS, variables=["mpg", "wt"], method="Pearson")
    t = r.tables[0].content
    check("Pearson r", t.iloc[0]["r"], -0.8676594, 1e-6, "R cor.test")
    check("Pearson CI lower", t.iloc[0]["95% CI lower"], -0.9338264, 1e-5, "R cor.test")
    check("Pearson CI upper", t.iloc[0]["95% CI upper"], -0.7440872, 1e-5, "R cor.test")


def test_linreg():  # R: lm(mpg ~ wt, mtcars)
    r = run("linreg", MTCARS, outcome="mpg", predictors=["wt"])
    check("lm intercept", tval(r, 1, 0, "B"), 37.2851, 0.0001, "R lm")
    check("lm slope", tval(r, 1, 1, "B"), -5.3445, 0.0001, "R lm")
    check("lm R²", tval(r, 0, 0, "R²"), 0.7528, 0.0001, "R lm")


def test_logreg():  # R: glm(am ~ wt, binomial, mtcars)
    r = run("logreg", MTCARS, outcome="am", predictors=["wt"], univariable=False)
    check("glm intercept", tval(r, 0, 0, "B"), 12.040, 0.001, "R glm")
    check("glm slope (wt)", tval(r, 0, 1, "B"), -4.024, 0.001, "R glm")
    check("glm AIC", tval(r, 1, 0, "AIC"), 23.176, 0.001, "R glm")


def test_km_logrank_cox():  # R survival: survdiff / coxph on aml
    aml = DS["AML survival (Cox/KM)"]
    r = run("km", aml, time="time", event="status", group="x")
    lr = r.tables[2].content
    check("Log-rank χ² (aml)", lr.iloc[0]["χ²"], 3.396, 0.001, "R survdiff")
    check("Log-rank p (aml)", lr.iloc[0]["p"], 0.0653, 0.0001, "R survdiff")
    check("Median survival Maintained", r.tables[0].content.iloc[0]["Median survival"], 31, 1e-9, "R survfit")
    check("Median survival Nonmaintained", r.tables[0].content.iloc[1]["Median survival"], 23, 1e-9, "R survfit")
    c = run("cox", aml, time="time", event="status", predictors=["x"])
    check("Cox coef (aml)", tval(c, 0, 0, "B"), 0.9155, 0.0001, "R coxph (Efron)")
    check("Cox SE (aml)", tval(c, 0, 0, "SE"), 0.5119, 0.0001, "R coxph (Efron)")


def test_icc():  # Shrout & Fleiss (1979) Table 2
    sf = pd.DataFrame([[9, 2, 5, 8], [6, 1, 3, 2], [8, 4, 6, 8], [7, 1, 2, 6], [10, 5, 6, 9], [6, 2, 4, 7]], columns=list("ABCD"))
    r = run("icc", sf, raters=list("ABCD"))
    t = r.tables[0].content.set_index("Type")["ICC"]
    for k, v in {"ICC(1,1)": 0.17, "ICC(2,1)": 0.29, "ICC(3,1)": 0.71, "ICC(1,k)": 0.44, "ICC(2,k)": 0.62, "ICC(3,k)": 0.91}.items():
        check(k + " (Shrout-Fleiss)", t[k], v, 0.006, "Shrout & Fleiss 1979")


def test_kappa():  # Textbook example: 20/5/10/15 → κ = 0.40
    a = ["Y"] * 25 + ["N"] * 25
    b = ["Y"] * 20 + ["N"] * 5 + ["Y"] * 10 + ["N"] * 15
    r = run("kappa", pd.DataFrame({"r1": a, "r2": b}), raters=["r1", "r2"])
    check("Cohen's kappa", tval(r, 1, 0, "Kappa"), 0.40, 1e-9, "Cohen 1960 worked example")


def test_probit():  # Bliss beetle data — R glm probit
    b = DS["Beetle mortality (probit LD50)"].copy()
    b["logdose"] = [1.6907, 1.7242, 1.7552, 1.7842, 1.8113, 1.8369, 1.8610, 1.8839]
    r = run("probit", b, dose="logdose", n="n", responders="dead", log_dose="Dose already in log10")
    check("Probit intercept (beetle)", tval(r, 1, 0, "Estimate"), -34.935, 0.01, "R glm probit / Dobson")
    check("Probit slope (beetle)", tval(r, 1, 1, "Estimate"), 19.728, 0.01, "R glm probit / Dobson")
    r2 = run("probit", b, dose="logdose", n="n", responders="dead", log_dose="Dose already in log10", link="Logit")
    check("Logit slope (beetle)", tval(r2, 1, 1, "Estimate"), 34.270, 0.01, "R glm logit / Dobson")


def test_meta_bcg():  # metafor dat.bcg, log RR
    bcg = pd.DataFrame({"trial": range(1, 14),
                        "tpos": [4, 6, 3, 62, 33, 180, 8, 505, 29, 17, 186, 5, 27],
                        "tneg": [119, 300, 228, 13536, 5036, 1361, 2537, 87886, 7470, 1699, 50448, 2493, 16886],
                        "cpos": [11, 29, 11, 248, 47, 372, 10, 499, 45, 65, 141, 3, 29],
                        "cneg": [128, 274, 209, 12619, 5761, 1079, 619, 87892, 7232, 1600, 27197, 2338, 17825]})
    bcg["tn"] = bcg.tpos + bcg.tneg
    bcg["cn"] = bcg.cpos + bcg.cneg
    r = run("meta", bcg, study="trial", effect_type="Risk ratio (2×2 counts)", c1="tpos", c2="tn", c3="cpos", c4="cn", method="REML")
    est = np.log(r.tables[1].content.iloc[1]["Pooled effect"])
    check("Meta REML log RR (BCG)", est, -0.7145, 0.0005, "metafor rma REML")
    check("Meta REML τ² (BCG)", r.tables[2].content.iloc[0]["τ²"], 0.3132, 0.0005, "metafor rma REML")
    r = run("meta", bcg, study="trial", effect_type="Risk ratio (2×2 counts)", c1="tpos", c2="tn", c3="cpos", c4="cn", method="DerSimonian-Laird")
    check("Meta DL log RR (BCG)", np.log(r.tables[1].content.iloc[1]["Pooled effect"]), -0.7141, 0.0005, "metafor rma DL")
    check("Meta DL τ² (BCG)", r.tables[2].content.iloc[0]["τ²"], 0.3088, 0.0005, "metafor rma DL")
    check("Meta I² (BCG)", r.tables[2].content.iloc[0]["I² (%)"], 92.12, 0.05, "metafor rma DL")


def test_power():  # R pwr / power.t.test / power.prop.test
    r = run("power", None, design="Two independent means (t-test)", mean_diff=0.5, sd=1, dropout=0)
    check("n per group d = 0.5", r.tables[1].content.iloc[0]["Value"], 64, 0, "R power.t.test (63.77)")
    r = run("power", None, design="Two independent proportions", p1=0.5, p2=0.75, power=0.9, dropout=0)
    check("n per group p .50 vs .75", r.tables[1].content.iloc[0]["Value"], 77, 0, "R power.prop.test (76.65)")


def test_bayes_factor():  # R BayesFactor::ttestBF (default r = √2/2)
    from medstatix.analyses.bayes import jzs_bf_t
    check("JZS BF10 paired t (sleep)", jzs_bf_t(-4.0621, 10, 9), 17.2589, 0.01, "R BayesFactor ttestBF paired")
    check("JZS BF10 independent t (sleep)", jzs_bf_t(-1.8608, 5, 18), 1.2659, 0.01, "R BayesFactor ttestBF")


def test_gpower():  # G*Power 3.1 a priori, α = .05, power = .80, two-tailed
    from medstatix.analyses.gpower import solve_n, FAMILIES as F
    for i, es, k, ref, lab in [(0, .5, 2, 128, "t independent d = 0.5"), (1, .5, 2, 34, "t paired dz = 0.5"),
                               (2, .25, 4, 180, "ANOVA f = 0.25, k = 4"), (3, .15, 3, 77, "Regression f² = 0.15, 3 predictors"),
                               (4, .3, 1, 88, "χ² w = 0.3, df = 1"), (6, .5, 2, 126, "Two proportions h = 0.5")]:
        check(f"G*Power N: {lab}", solve_n(F[i], es, .05, .8, k, 1, 2)[0], ref, 0, "G*Power 3.1.9 (total N)")


def test_all_analyses_run():
    """Smoke test: every analysis runs end-to-end on the simulated trial dataset."""
    t = DS["Clinical trial (simulated)"]
    calls = {
        "descriptives": dict(variables=["age", "SBP_0"], group="group"), "frequencies": dict(variables=["sex"]),
        "normality": dict(variables=["CRP"]), "outliers": dict(variable="CRP"),
        "ttest_one": dict(variable="age", mu=50), "mannwhitney": dict(outcome="CRP", group="group"),
        "wilcoxon": dict(var1="SBP_0", var2="SBP_4"), "anova2": dict(outcome="SBP_8", factor_a="group", factor_b="sex"),
        "ancova": dict(outcome="SBP_8", group="group", covariates=["SBP_0"]),
        "rmanova": dict(measures=["SBP_0", "SBP_4", "SBP_8"]), "friedman": dict(measures=["SBP_0", "SBP_4", "SBP_8"]),
        "mcnemar": dict(var1="MACE", var2="death"), "mantel": dict(exposure="group", outcome="MACE", strata="sex"),
        "gof": dict(variable="sex"), "partial_corr": dict(x="SBP_0", y="SBP_8", controls=["age"]),
        "ordinal": dict(outcome="rater1", predictors=["age"]), "countreg": dict(outcome="rater1", predictors=["age", "group"]),
        "roc": dict(truth="MACE", markers=["biomarker", "CRP"]), "kappa": dict(raters=["rater1", "rater2"], weights="Quadratic"),
        "blandaltman": dict(method1="methodA", method2="methodB"), "cronbach": dict(items=["SBP_0", "SBP_4", "SBP_8"]),
        "pca": dict(variables=["age", "SBP_0", "SBP_4", "SBP_8", "CRP"], group="group"),
        "cluster": dict(variables=["age", "SBP_0", "CRP"]), "logreg": dict(outcome="MACE", predictors=["age", "group", "SBP_0"]),
        "cox": dict(time="time_months", event="death", predictors=["group", "age"]),
    }
    for aid, kw in calls.items():
        res = run(aid, t, **kw)
        assert res.blocks, aid
    long = t.melt(id_vars=["id", "group"], value_vars=["SBP_0", "SBP_4", "SBP_8"], var_name="visit", value_name="SBP")
    assert run("mixed", long, outcome="SBP", subject="id", time="visit", group="group").tables
    assert run("gee", long.assign(high=(long.SBP > 140).astype(int)), outcome="high", subject="id", predictors=["visit", "group"]).tables
    conc = pd.DataFrame({"t": [0, .5, 1, 2, 4, 6, 8, 12, 24], "c": [0, 4.2, 7.9, 9.1, 7.2, 5.4, 4.0, 2.3, 0.45]})
    assert run("nca", conc, time="t", conc="c", dose=100).tables
    dr = pd.DataFrame({"conc": np.repeat([1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4], 3),
                       "resp": [2, 4, 3, 12, 15, 10, 45, 50, 48, 85, 88, 83, 97, 99, 98, 100, 99, 101]})
    r = run("doseresp", dr, dose="conc", response="resp")
    assert 1e-8 < r.tables[0].content.iloc[-1]["Estimate"] < 1e-6
    mm = pd.DataFrame({"S": [0.5, 1, 2, 4, 8, 16, 32], "v": [0.9, 1.6, 2.6, 3.5, 4.2, 4.6, 4.8]})
    assert run("michaelis", mm, substrate="S", velocity="v").tables
    assert run("diag2x2", None).tables and run("proportion_ci", None, x2=5, n2=50).tables
    from medstatix.core.advisor import auto_analyze
    for o, f in [("SBP_8", "group"), ("CRP", "group"), ("MACE", "group"), ("SBP_0", "age"), ("MACE", "biomarker")]:
        res, aid = auto_analyze(t, o, f)
        assert res.tables


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    w = max(len(r[0]) for r in RESULTS)
    print(f"\n{'Check':<{w}}  {'MedStatix':>12}  {'Reference':>12}  Result  Source")
    for n, g, r, t, s, src in RESULTS:
        print(f"{n:<{w}}  {g:>12.5f}  {r:>12.5f}  {s:<6}  {src}")
    print(f"\n{sum(1 for r in RESULTS if r[4] == 'PASS')}/{len(RESULTS)} reference checks passed; {fails} test function(s) failed.")
