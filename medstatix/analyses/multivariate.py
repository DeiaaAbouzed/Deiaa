"""Multivariate exploration: PCA and hierarchical clustering."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster

from ..core.data import numeric
from ..core.result import Result, AnalysisError
from ..plots import figures as F
from .registry import register, P


@register("pca", "multivariate", "Principal component analysis (PCA)", "تحليل المكونات الرئيسية PCA",
          [P("variables", "Variables", "المتغيرات", "vars_num"), P("group", "Colour by group (optional)", "التلوين حسب مجموعة (اختياري)", "var_cat", optional=True)],
          "Standardized PCA with eigenvalues, explained variance, loadings, scree plot and biplot.",
          "تحليل المكونات الرئيسية مع القيم الذاتية والتباين المفسر والتشبعات ورسم Scree وBiplot.")
def pca(df, variables, group=None):
    if len(variables) < 2:
        raise AnalysisError("Select at least 2 variables.")
    d = pd.DataFrame({v: numeric(df, v) for v in variables})
    if group:
        d["_g"] = df[group]
    d = d.dropna()
    X = d[variables].to_numpy(float)
    Z = (X - X.mean(0)) / X.std(0, ddof=1)
    U, S, Vt = np.linalg.svd(Z, full_matrices=False)
    eig = S ** 2 / (len(Z) - 1)
    var = eig / eig.sum() * 100
    loadings = Vt.T * np.sqrt(eig)
    scores = Z @ Vt.T
    res = Result("Principal component analysis", f"{len(variables)} variables, n = {len(d)} (correlation matrix)")
    res.table(pd.DataFrame({"Component": [f"PC{i+1}" for i in range(len(eig))], "Eigenvalue": eig, "% variance": var,
                            "Cumulative %": np.cumsum(var)}), "Total variance explained")
    lt = pd.DataFrame(loadings[:, :min(4, len(eig))], index=variables, columns=[f"PC{i+1}" for i in range(min(4, len(eig)))])
    lt.index.name = "Variable"
    res.table(lt, "Component loadings (correlations of variables with components)")
    nk = int((eig > 1).sum())
    res.interpret(f"{nk} component(s) have eigenvalue > 1 (Kaiser criterion), explaining {np.cumsum(var)[max(nk-1,0)]:.1f}% of total variance.",
                  f"{nk} مكون/مكونات لها قيمة ذاتية أكبر من 1 (معيار كايزر) وتفسر {np.cumsum(var)[max(nk-1,0)]:.1f}% من التباين الكلي.")
    res.figure(F.scree_plot(eig), "Scree plot.")
    res.figure(F.pca_biplot(scores, loadings, variables, groups=list(d["_g"]) if group else None, pc_var=(var[0], var[1])), "PCA biplot.")
    return res


@register("cluster", "multivariate", "Hierarchical cluster analysis", "التحليل العنقودي الهرمي",
          [P("variables", "Variables", "المتغيرات", "vars_num"), P("label", "Case labels (optional)", "تسميات الحالات (اختياري)", "var_any", optional=True),
           P("method", "Linkage", "طريقة الربط", "choice", ["ward", "average", "complete", "single"], "ward"),
           P("k", "Number of clusters", "عدد العناقيد", "int", default=3)],
          "Agglomerative clustering on standardized variables (Euclidean) with dendrogram.", "تجميع هرمي مع رسم الشجرة.")
def cluster(df, variables, label=None, method="ward", k=3):
    d = pd.DataFrame({v: numeric(df, v) for v in variables})
    labels = df[label].astype(str) if label else pd.Series([str(i + 1) for i in range(len(df))], index=df.index)
    d = d.dropna()
    Z = ((d - d.mean()) / d.std()).to_numpy()
    L = linkage(Z, method=method, metric="euclidean")
    cl = fcluster(L, k, criterion="maxclust")
    res = Result("Hierarchical cluster analysis", f"{method} linkage, Euclidean distance on z-scores, k = {k}")
    prof = d.assign(Cluster=cl).groupby("Cluster").mean()
    prof.insert(0, "n", pd.Series(cl).value_counts().sort_index().values)
    res.table(prof, "Cluster profiles (means)")
    res.interpret("Cluster membership is exploratory; validate the number of clusters (dendrogram gap, silhouette) and describe each profile clinically.",
                  "عضوية العناقيد استكشافية؛ تحقق من عدد العناقيد وصف كل عنقود سريريًا.")
    from ..plots.figures import styled, new_figure
    with styled():
        fig, ax = new_figure(w_mm=170, h_mm=90)
        dendrogram(L, labels=labels.loc[d.index].tolist(), ax=ax, color_threshold=L[-(k - 1), 2] if k > 1 else 0, leaf_font_size=7)
        ax.set_ylabel("Distance")
        fig.tight_layout()
    res.figure(fig, "Dendrogram.")
    return res
