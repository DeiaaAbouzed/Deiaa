"""Bridge to R (optional). When R is installed, an analysis run in MedStatix can be re-run in R on the same data, so
the two outputs can be compared side by side, and any R script can be run on the current data set.

Nothing here is required: if Rscript is not found the menu entries explain how to install R (https://cran.r-project.org)."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile


def find_rscript():
    p = shutil.which("Rscript")
    if p:
        return p
    pats = [r"C:\Program Files\R\R-*\bin\Rscript.exe", r"C:\Program Files\R\R-*\bin\x64\Rscript.exe",
            "/Library/Frameworks/R.framework/Resources/bin/Rscript", "/usr/local/bin/Rscript", "/opt/homebrew/bin/Rscript"]
    for pat in pats:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def _q(name):
    return "`" + str(name).replace("`", "") + "`"


def _alt(kw):
    return {"two-sided": "two.sided", "greater": "greater", "less": "less"}.get(kw.get("alternative", "two-sided"), "two.sided")


def r_code(aid, kw):
    """R code reproducing a MedStatix analysis on data frame `d` (already loaded). None if not supported."""
    g = kw.get("group"); o = kw.get("outcome")
    if aid == "ttest_ind":
        return (f"d${_q(g)} <- factor(d${_q(g)})\n"
                f"print(t.test({_q(o)} ~ {_q(g)}, data = d, var.equal = TRUE, alternative = '{_alt(kw)}'))\n"
                f"print(t.test({_q(o)} ~ {_q(g)}, data = d, alternative = '{_alt(kw)}'))   # Welch\n")
    if aid == "ttest_paired":
        return f"print(t.test(d${_q(kw['var1'])}, d${_q(kw['var2'])}, paired = TRUE, alternative = '{_alt(kw)}'))\n"
    if aid == "ttest_one":
        return f"print(t.test(d${_q(kw['variable'])}, mu = {float(kw.get('mu', 0))}, alternative = '{_alt(kw)}'))\n"
    if aid == "mannwhitney":
        return f"d${_q(g)} <- factor(d${_q(g)})\nprint(wilcox.test({_q(o)} ~ {_q(g)}, data = d, alternative = '{_alt(kw)}', exact = FALSE))\n"
    if aid == "wilcoxon":
        return f"print(wilcox.test(d${_q(kw['var1'])}, d${_q(kw['var2'])}, paired = TRUE, exact = FALSE))\n"
    if aid == "anova1":
        return (f"d${_q(g)} <- factor(d${_q(g)})\nfit <- aov({_q(o)} ~ {_q(g)}, data = d)\nprint(summary(fit))\n"
                f"print(oneway.test({_q(o)} ~ {_q(g)}, data = d))   # Welch ANOVA\nprint(TukeyHSD(fit))\n")
    if aid == "kruskal":
        return f"d${_q(g)} <- factor(d${_q(g)})\nprint(kruskal.test({_q(o)} ~ {_q(g)}, data = d))\n"
    if aid == "correlation":
        v = kw["variables"]; m = kw.get("method", "Pearson").lower()
        return "".join(f"print(cor.test(d${_q(a)}, d${_q(b)}, method = '{m}'))\n"
                       for i, a in enumerate(v) for b in v[i + 1:])
    if aid == "linreg":
        return f"print(summary(lm({_q(o)} ~ {' + '.join(_q(p) for p in kw['predictors'])}, data = d)))\n"
    if aid == "logreg":
        return f"print(summary(glm({_q(o)} ~ {' + '.join(_q(p) for p in kw['predictors'])}, data = d, family = binomial)))\n"
    if aid == "chisq" and kw.get("row") and kw.get("col"):
        return f"tab <- table(d${_q(kw['row'])}, d${_q(kw['col'])})\nprint(tab)\nprint(chisq.test(tab, correct = FALSE))\nprint(fisher.test(tab))\n"
    if aid == "mixed":
        fx = _q(kw["time"]) + (f" * {_q(kw['group'])}" if kw.get("group") else "")
        return ("if (!requireNamespace('lmerTest', quietly = TRUE)) stop('Install lmerTest: install.packages(\"lmerTest\")')\n"
                f"d${_q(kw['time'])} <- factor(d${_q(kw['time'])})\n"
                f"fit <- lmerTest::lmer({_q(o)} ~ {fx} + (1 | {_q(kw['subject'])}), data = d, REML = TRUE)\n"
                "print(summary(fit))\nprint(anova(fit))\n")
    if aid == "gee":
        fam = "binomial" if kw.get("family", "").startswith("Binary") else "poisson"
        return ("if (!requireNamespace('geepack', quietly = TRUE)) stop('Install geepack: install.packages(\"geepack\")')\n"
                f"d <- d[order(d${_q(kw['subject'])}), ]\n"
                f"fit <- geepack::geeglm({_q(o)} ~ {' + '.join(_q(p) for p in kw['predictors'])}, id = {_q(kw['subject'])}, "
                f"data = d, family = {fam}, corstr = 'exchangeable')\nprint(summary(fit))\n")
    return None


def run_r(code, df=None, timeout=180):
    """Run R code (with the data frame saved as `d`). Returns (ok, output text)."""
    rs = find_rscript()
    if not rs:
        return False, "R was not found. Install R from https://cran.r-project.org and restart MedStatix."
    with tempfile.TemporaryDirectory() as tmp:
        script = "options(width = 120)\n"
        if df is not None:
            csv = os.path.join(tmp, "data.csv")
            df.to_csv(csv, index=False)
            script += f"d <- read.csv('{csv.replace(os.sep, '/')}', check.names = FALSE, stringsAsFactors = FALSE)\n"
        script += code
        path = os.path.join(tmp, "script.R")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        try:
            p = subprocess.run([rs, "--vanilla", path], capture_output=True, text=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return False, "R did not finish within the time limit."
        out = (p.stdout or "") + (("\n" + p.stderr) if p.returncode else "")
        return p.returncode == 0, out.strip()
