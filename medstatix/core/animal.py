"""Animal-study helpers: randomisation, sample size (Mead's resource equation), outlier tests (Grubbs, ROUT),
ARRIVE 2.0 checklist, and data-entry templates for common pharmacology / toxicology designs."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------- randomisation
def randomize(n_per_group: dict, seed: int | None = None, weights: list | None = None, prefix: str = "A") -> pd.DataFrame:
    """Allocate animals to groups.

    Without weights: complete randomisation with equal (or given) group sizes.
    With weights: stratified (blocked) randomisation — animals are ranked by body weight, cut into blocks of
    k (= number of groups), and each block is randomly spread over the groups, so groups have similar mean weight."""
    rng = np.random.default_rng(seed)
    groups = [g for g, n in n_per_group.items() for _ in range(int(n))]
    N = len(groups)
    ids = [f"{prefix}{i + 1:02d}" for i in range(N)]
    if weights is not None and len(weights) == N:
        names = list(n_per_group)
        k = len(names)
        order = np.argsort(np.asarray(weights, float))
        alloc = [None] * N
        remaining = dict(n_per_group)
        for b in range(0, N, k):
            block = order[b:b + k]
            avail = [g for g in names if remaining[g] > 0]
            rng.shuffle(avail)
            for idx, g in zip(block, avail):
                alloc[idx] = g; remaining[g] -= 1
        for i in range(N):  # any leftovers (unequal groups)
            if alloc[i] is None:
                g = next(g for g in names if remaining[g] > 0); alloc[i] = g; remaining[g] -= 1
        df = pd.DataFrame({"Animal ID": ids, "Body weight": weights, "Group": alloc})
    else:
        perm = rng.permutation(groups)
        df = pd.DataFrame({"Animal ID": ids, "Group": perm})
    df["Cage/order (random)"] = rng.permutation(N) + 1
    return df


def mead(k_groups: int, blocks: int = 1, covariates: int = 0):
    """Mead's resource equation: E = N − B − T should lie between 10 and 20 (T = treatments − 1, B = blocks − 1)."""
    T = k_groups - 1; B = blocks - 1
    nmin = math.ceil((10 + T + B + covariates + 1) / k_groups)
    nmax = math.floor((20 + T + B + covariates + 1) / k_groups)
    return nmin, nmax


def n_for_power(d: float, k_groups: int = 2, alpha: float = 0.05, power: float = 0.8) -> int:
    from statsmodels.stats.power import FTestAnovaPower, TTestIndPower
    if k_groups <= 2:
        return int(math.ceil(TTestIndPower().solve_power(effect_size=d, alpha=alpha, power=power)))
    f = d / 2  # Cohen: f ≈ d/2 for two extreme groups, the rest at the mean (conservative)
    return int(math.ceil(FTestAnovaPower().solve_power(effect_size=f, alpha=alpha, power=power, k_groups=k_groups) / k_groups))


# ---------------------------------------------------------------------------- outliers
def grubbs(values, alpha=0.05):
    """Iterative two-sided Grubbs test. Returns list of (index, value, G, G_crit) flagged as outliers."""
    x = pd.Series(values, dtype=float).dropna()
    out = []
    while len(x) >= 3:
        m, s = x.mean(), x.std(ddof=1)
        if s == 0:
            break
        dev = (x - m).abs()
        idx = dev.idxmax(); G = dev[idx] / s
        n = len(x)
        t = stats.t.ppf(1 - alpha / (2 * n), n - 2)
        Gc = (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))
        if G > Gc:
            out.append((idx, float(x[idx]), float(G), float(Gc))); x = x.drop(idx)
        else:
            break
    return out


def rout(values, Q=0.01):
    """ROUT for a column of values (Motulsky & Brown 2006): robust (Cauchy-loss) estimate of the centre,
    robust SD of the residuals (RSDR, 68.27th percentile × n/(n−1)), t = |residual| / RSDR, two-sided p from
    t(n−1), then the Benjamini–Hochberg false-discovery rate Q decides which points are outliers."""
    x = pd.Series(values, dtype=float).dropna()
    n = len(x)
    if n < 3:
        return []
    from scipy.optimize import minimize_scalar
    v = x.values
    scale = np.median(np.abs(v - np.median(v))) * 1.4826 or (np.std(v) or 1.0)
    res = minimize_scalar(lambda c: np.sum(np.log1p(((v - c) / scale) ** 2)), bounds=(v.min(), v.max()), method="bounded")
    c = res.x
    r = np.abs(v - c)
    rsdr = np.percentile(r, 68.27) * n / (n - 1)
    if rsdr == 0:
        return []
    t = r / rsdr
    p = 2 * stats.t.sf(t, n - 1)
    order = np.argsort(p)
    last = 0
    for rank, i in enumerate(order, 1):
        if p[i] <= Q * rank / n:
            last = rank
    flagged = list(order[:last])
    return [(x.index[i], float(v[i]), float(t[i]), float(p[i])) for i in flagged]


def outlier_report(df: pd.DataFrame, value: str, group: str | None, method="ROUT", Q=0.01, alpha=0.05) -> pd.DataFrame:
    rows = []
    groups = [(None, df)] if not group else list(df.groupby(group, sort=False))
    for g, sub in groups:
        vals = sub[value]
        found = rout(vals, Q) if method == "ROUT" else grubbs(vals, alpha)
        for idx, v, stat, extra in found:
            rows.append({"Row": int(idx) + 1, "Group": g if g is not None else "", "Value": v,
                         ("t (RSDR)" if method == "ROUT" else "G"): round(stat, 3),
                         ("p" if method == "ROUT" else "G critical"): round(extra, 4),
                         "Decision": "flagged"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------- ARRIVE 2.0
ARRIVE = [
    ("E", "1. Study design", "تصميم الدراسة", "Groups compared, control group(s), experimental unit (animal, litter, cage)."),
    ("E", "2. Sample size", "حجم العينة", "Number of animals per group and in total; how the sample size was decided (e.g. power or Mead's equation)."),
    ("E", "3. Inclusion and exclusion criteria", "معايير الإدخال والاستبعاد", "Criteria set a priori; animals/data excluded and why; n analysed per group."),
    ("E", "4. Randomisation", "التوزيع العشوائي", "Whether and how randomisation was used to allocate animals; strategy to minimise confounders (order, cage)."),
    ("E", "5. Blinding", "التعمية", "Who was aware of group allocation at each stage (allocation, conduct, outcome assessment, analysis)."),
    ("E", "6. Outcome measures", "مقاييس النتائج", "Define all outcomes; specify the primary outcome for hypothesis-testing studies."),
    ("E", "7. Statistical methods", "الطرق الإحصائية", "Software, tests for each analysis, methods to check assumptions and alternatives if not met."),
    ("E", "8. Experimental animals", "حيوانات التجربة", "Species, strain, sex, age, weight, source, health/immune status."),
    ("E", "9. Experimental procedures", "الإجراءات التجريبية", "What, how, when, where and why for each group (doses, route, anaesthesia, euthanasia)."),
    ("E", "10. Results", "النتائج", "Summary/descriptive statistics for each group with a measure of variability; effect size with a CI."),
    ("R", "11. Abstract", "الملخص", "Accurate summary of objectives, animals, methods and key findings."),
    ("R", "12. Background", "الخلفية", "Scientific background and rationale, relevance of the animal model."),
    ("R", "13. Objectives", "الأهداف", "Clear research question / hypotheses."),
    ("R", "14. Ethical statement", "البيان الأخلاقي", "Ethical review committee, approval number, relevant licences and guidelines."),
    ("R", "15. Housing and husbandry", "الإيواء والرعاية", "Conditions: cages, bedding, light cycle, temperature, food, water, enrichment."),
    ("R", "16. Animal care and monitoring", "رعاية الحيوانات ومراقبتها", "Interventions to reduce pain/suffering, humane end points, adverse events."),
    ("R", "17. Interpretation / scientific implications", "التفسير", "Interpret results with the study limitations and the literature."),
    ("R", "18. Generalisability / translation", "قابلية التعميم", "Relevance to other species or experimental conditions, including humans."),
    ("R", "19. Protocol registration", "تسجيل البروتوكول", "Whether a protocol was prepared/registered and where."),
    ("R", "20. Data access", "إتاحة البيانات", "Statement on whether and where the data are available."),
    ("R", "21. Declaration of interests", "تضارب المصالح", "Conflicts of interest and funding sources."),
]


# ---------------------------------------------------------------------------- templates
TEMPLATES = {
    "oxidative": {"en": "Oxidative stress panel", "ar": "مؤشرات الإجهاد التأكسدي",
                  "measures": ["MDA (nmol/g)", "GSH (mg/g)", "SOD (U/mg)", "CAT (U/mg)", "NO (µmol/g)"]},
    "liver": {"en": "Liver function", "ar": "وظائف الكبد",
              "measures": ["ALT (U/L)", "AST (U/L)", "ALP (U/L)", "Albumin (g/dL)", "Total bilirubin (mg/dL)"]},
    "kidney": {"en": "Kidney function", "ar": "وظائف الكلى",
               "measures": ["Urea (mg/dL)", "Creatinine (mg/dL)", "Uric acid (mg/dL)", "KIM-1 (ng/mL)"]},
    "cytokines": {"en": "Inflammatory cytokines", "ar": "السيتوكينات الالتهابية",
                  "measures": ["TNF-α (pg/mL)", "IL-1β (pg/mL)", "IL-6 (pg/mL)", "IL-10 (pg/mL)"]},
    "apoptosis": {"en": "Apoptosis markers", "ar": "مؤشرات الموت الخلوي المبرمج",
                  "measures": ["Caspase-3 (ng/mg)", "Bax (relative)", "Bcl-2 (relative)", "Bax/Bcl-2 ratio"]},
    "histoscore": {"en": "Histopathology scoring (0–4)", "ar": "تقييم الهستوباثولوجي (0–4)",
                   "measures": ["Necrosis score", "Inflammation score", "Congestion score", "Fibrosis score"], "ordinal": True},
    "organweight": {"en": "Body and organ weights", "ar": "أوزان الجسم والأعضاء",
                    "measures": ["Initial body weight (g)", "Final body weight (g)", "Organ weight (g)", "Relative organ weight (%)"]},
    "ld50": {"en": "Acute toxicity (LD50, probit)", "ar": "السمية الحادة (LD50 بطريقة probit)", "special": "ld50"},
    "doseresp": {"en": "Dose–response (EC50/IC50)", "ar": "العلاقة بين الجرعة والاستجابة (EC50/IC50)", "special": "doseresp"},
}

DEFAULT_GROUPS = ["Control", "Toxicant", "Toxicant + Drug (low)", "Toxicant + Drug (high)", "Drug alone"]


def make_template(key: str, groups: list[str], n: int) -> pd.DataFrame:
    t = TEMPLATES[key]
    if t.get("special") == "ld50":
        return pd.DataFrame({"dose_mg_kg": [np.nan] * 6, "n": [n] * 6, "dead": [np.nan] * 6})
    if t.get("special") == "doseresp":
        return pd.DataFrame({"concentration": [np.nan] * 8, "response_%": [np.nan] * 8, "replicate": [1] * 8})
    rows = []
    for gi, g in enumerate(groups):
        for i in range(n):
            rows.append({"Group": g, "Animal": f"G{gi + 1}-{i + 1:02d}", **{m: np.nan for m in t["measures"]}})
    df = pd.DataFrame(rows)
    df["Group"] = pd.Categorical(df["Group"], categories=groups, ordered=True)
    return df
