from __future__ import annotations

import matplotlib
from matplotlib import font_manager


PREFERRED_CHINESE_FONTS = [
    "Noto Sans CJK SC",
    "Noto Serif CJK SC",
    "Source Han Sans SC",
    "Source Han Serif SC",
    "Microsoft YaHei",
    "SimHei",
    "PingFang SC",
    "Heiti SC",
    "WenQuanYi Micro Hei",
    "AR PL UKai CN",
    "AR PL UMing CN",
    "Droid Sans Fallback",
]


def configure_matplotlib_chinese_font() -> str | None:
    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    selected_font = next((name for name in PREFERRED_CHINESE_FONTS if name in available_fonts), None)
    if selected_font is None:
        selected_font = next(
            (
                name
                for name in sorted(available_fonts)
                if any(keyword in name.lower() for keyword in ["cjk sc", "simhei", "yahei", "wenquanyi", "ukai", "uming"])
            ),
            None,
        )
    if selected_font is None:
        return None

    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [selected_font] + [
        name for name in matplotlib.rcParams.get("font.sans-serif", []) if name != selected_font
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return selected_font
