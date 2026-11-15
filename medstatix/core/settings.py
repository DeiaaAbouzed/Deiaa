"""Global user settings (figure style, palette, language). Persisted with QSettings by the UI."""
from dataclasses import dataclass, asdict


@dataclass
class Settings:
    language: str = "ar"            # ar | en
    theme: str = "light"            # light | dark
    fig_style: str = "Signature"    # Signature | Prism | Classic | Nature | ggplot | Minimal
    palette: str = "MedStatix Signature"  # MedStatix Signature | Prism | Okabe-Ito | Grayscale | NEJM | Lancet | Pastel
    group_plot: str = "Scatter + mean ± SD"  # see plots.GROUP_PLOT_TYPES
    error_bar: str = "SD"           # SD | SEM | 95% CI
    font_family: str = "Arial"
    font_size: float = 11.0
    fig_width_mm: float = 90.0
    fig_height_mm: float = 75.0
    export_dpi: int = 600
    show_significance: bool = True
    alpha: float = 0.05
    decimals: int = 3
    journal: str = ""               # target journal preset ("" = none), see report/journals.py
    table_style: str = "Signature"  # Signature | APA | SPSS
    auto_fallback: bool = True      # add the non-parametric alternative when assumptions fail
    ai_user_model: bool = True      # use the nucleus classifier fine-tuned on the user's own slides when present
    check_updates: bool = True      # check GitHub releases at startup
    interp_lang: str = "same"       # Word export interpretation language: same | en | ar | both

    def as_dict(self):
        return asdict(self)


SETTINGS = Settings()
