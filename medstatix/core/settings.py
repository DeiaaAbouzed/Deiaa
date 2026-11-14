"""Global user settings (figure style, palette, language). Persisted with QSettings by the UI."""
from dataclasses import dataclass, asdict


@dataclass
class Settings:
    language: str = "ar"            # ar | en
    theme: str = "light"            # light | dark
    fig_style: str = "Prism"        # Prism | Classic | Nature | ggplot | Minimal
    palette: str = "Prism"          # Prism | Okabe-Ito | Grayscale | NEJM | Lancet | Pastel
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

    def as_dict(self):
        return asdict(self)


SETTINGS = Settings()
