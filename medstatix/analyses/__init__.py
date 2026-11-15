"""Importing this package registers every analysis in REGISTRY."""
from . import (describe, compare, repeated, categorical, correlation, regression, survival,  # noqa: F401
               diagnostic, pharmtox, multivariate, meta, power, gpower, bayes, charts, journal)
from .registry import REGISTRY, CATEGORIES, run  # noqa: F401
