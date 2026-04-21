from __future__ import annotations

from pathlib import Path
import re
import textwrap
from typing import Any, Iterable, Sequence
import warnings

import matplotlib


matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

from supply_disruption_sim.viz.font_config import configure_matplotlib_chinese_font


CHINESE_FONT_NAME = configure_matplotlib_chinese_font()

THEME = {
    "figure_bg": "#FFFFFF",
    "panel_bg": "#FFFFFF",
    "panel_alt_bg": "#FFFFFF",
    "grid": "#D7E0EA",
    "spine": "#CBD5E1",
    "text": "#12263A",
    "muted": "#5B6B7A",
    "accent": "#D1495B",
    "shadow": "#E7EDF4",
}

QUALITATIVE_COLORS = [
    "#0F766E",
    "#D97706",
    "#5B6CFA",
    "#C44536",
    "#2A9D8F",
    "#7C6A0A",
    "#6C5CE7",
    "#277DA1",
]

POLICY_PROFILE_COLORS = {
    "time_priority_interrupt": "#0F766E",
    "baseline": "#166534",
    "all_policies": "#1D4ED8",
    "no_policy": "#D62828",
    "only_backup_switch": "#F97316",
    "only_substitution": "#A855F7",
    "only_priority_repair": "#0891B2",
    "no_priority_repair": "#0EA5E9",
    "no_backup_switch": "#B45309",
    "no_substitution": "#6366F1",
}

POLICY_PROFILE_LINESTYLES = {
    "time_priority_interrupt": "-",
    "baseline": "-",
    "all_policies": "--",
    "no_policy": "-",
    "only_backup_switch": "-.",
    "only_substitution": ":",
    "only_priority_repair": (0, (5, 1.4)),
    "no_priority_repair": (0, (3, 1.6)),
    "no_backup_switch": (0, (6, 1.6, 1.2, 1.6)),
    "no_substitution": (0, (4, 1.3, 1.1, 1.3)),
}


def apply_plot_defaults() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": THEME["figure_bg"],
            "axes.facecolor": THEME["panel_bg"],
            "axes.edgecolor": THEME["spine"],
            "axes.labelcolor": THEME["muted"],
            "axes.titlecolor": THEME["text"],
            "axes.titlesize": 14,
            "axes.titleweight": "semibold",
            "xtick.color": THEME["muted"],
            "ytick.color": THEME["muted"],
            "grid.color": THEME["grid"],
            "grid.linestyle": "--",
            "grid.linewidth": 0.8,
            "legend.frameon": True,
            "legend.facecolor": "#FFFFFF",
            "legend.edgecolor": THEME["spine"],
            "savefig.facecolor": THEME["figure_bg"],
        }
    )


apply_plot_defaults()


def font_props(*, size: float | None = None, weight: str | None = None) -> dict[str, Any] | None:
    if CHINESE_FONT_NAME is None and size is None and weight is None:
        return None

    properties: dict[str, Any] = {}
    if CHINESE_FONT_NAME is not None:
        properties["family"] = CHINESE_FONT_NAME
    if size is not None:
        properties["size"] = size
    if weight is not None:
        properties["weight"] = weight
    return properties or None


def style_axes(
    ax,
    *,
    title: str | None = None,
    ylabel: str | None = None,
    xlabel: str | None = None,
    grid_axis: str = "y",
) -> None:
    ax.set_facecolor(THEME["panel_bg"])
    ax.grid(True, axis=grid_axis, alpha=0.75, linestyle="--", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(THEME["spine"])
    ax.spines["bottom"].set_color(THEME["spine"])
    ax.tick_params(colors=THEME["muted"], labelsize=10.5)
    if title:
        ax.set_title(title, loc="left", pad=12, fontproperties=font_props(size=14.5, weight="semibold"))
    if ylabel:
        ax.set_ylabel(ylabel, fontproperties=font_props(size=10.8))
    if xlabel:
        ax.set_xlabel(xlabel, fontproperties=font_props(size=10.8))


def add_figure_header(fig, title: str, subtitle: str | None = None) -> None:
    fig.patch.set_facecolor(THEME["figure_bg"])
    title_lines = _wrap_header_text(title, width=_header_wrap_width(fig, chars_per_inch=3.9, minimum=28, maximum=76))
    subtitle_lines = (
        _wrap_header_text(subtitle, width=_header_wrap_width(fig, chars_per_inch=5.5, minimum=36, maximum=110))
        if subtitle
        else []
    )
    title_text = "\n".join(title_lines)
    subtitle_text = "\n".join(subtitle_lines)
    title_y = 0.986
    title_line_step = 0.05
    subtitle_gap = 0.018
    subtitle_line_step = 0.028
    fig.suptitle(
        title_text,
        x=0.055,
        y=title_y,
        ha="left",
        color=THEME["text"],
        fontproperties=font_props(size=21, weight="bold"),
        linespacing=1.08,
    )
    if subtitle_text:
        subtitle_y = title_y - title_line_step * len(title_lines) - subtitle_gap
        fig.text(
            0.055,
            subtitle_y,
            subtitle_text,
            ha="left",
            va="top",
            color=THEME["muted"],
            fontproperties=font_props(size=12.4),
            linespacing=1.12,
        )
        header_bottom = subtitle_y - subtitle_line_step * len(subtitle_lines)
    else:
        header_bottom = title_y - title_line_step * len(title_lines)
    setattr(fig, "_codex_header_layout_top", max(0.7, min(0.92, header_bottom - 0.03)))


def finish_figure(
    fig,
    output_path: str | Path,
    *,
    dpi: int = 180,
    top: float = 0.92,
    facecolor: str | None = None,
    tight: bool = True,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if tight:
        layout_top = min(top, float(getattr(fig, "_codex_header_layout_top", top)))
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Tight layout not applied.*", category=UserWarning)
            fig.tight_layout(rect=(0, 0, 1, layout_top))
    fig.savefig(output, dpi=dpi, facecolor=facecolor or THEME["figure_bg"], pad_inches=0.08)
    plt.close(fig)
    return output

def legend_style(
    ax,
    *,
    ncol: int = 1,
    loc: str = "best",
    bbox_to_anchor: tuple[float, float] | None = None,
    fontsize: float = 10,
) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    legend = ax.legend(
        loc=loc,
        bbox_to_anchor=bbox_to_anchor,
        ncol=ncol,
        frameon=True,
        fancybox=True,
        framealpha=0.95,
        borderpad=0.45,
        borderaxespad=0.0 if bbox_to_anchor is not None else 0.4,
        handlelength=2.1,
        handletextpad=0.6,
        labelspacing=0.45,
        columnspacing=0.9,
        fontsize=fontsize,
        prop=font_props(size=fontsize),
    )
    if legend is not None:
        legend.get_frame().set_linewidth(0.9)
        legend.get_frame().set_facecolor("#FFFFFF")
        legend.get_frame().set_edgecolor(THEME["spine"])


def integer_ticks(ax) -> None:
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))


def add_value_labels(ax, *, padding: float = 0.03, suffix: str = "") -> None:
    for patch in getattr(ax, "patches", []):
        height = patch.get_height()
        if height <= 0:
            continue
        x = patch.get_x() + patch.get_width() / 2.0
        y = patch.get_y() + height
        ax.text(
            x,
            y + max(height * padding, 0.05),
            f"{height:.0f}{suffix}",
            ha="center",
            va="bottom",
            fontsize=9.2,
            color=THEME["muted"],
            fontproperties=font_props(size=9.2),
        )


def annotate_series_endpoint(
    ax,
    x_value: Any,
    y_value: float,
    text: str,
    *,
    color: str,
    x_offset: int | None = None,
    y_offset: int | None = None,
) -> None:
    x_ratio, y_ratio = _normalized_point_position(ax, x_value, y_value)
    if x_offset is None:
        x_offset = -34 if x_ratio >= 0.9 else (-24 if x_ratio >= 0.76 else 8)
    if y_offset is None:
        if y_ratio <= 0.12:
            y_offset = 14
        elif y_ratio <= 0.2:
            y_offset = 10
        elif y_ratio >= 0.84:
            y_offset = -10
        else:
            y_offset = 0
    vertical_alignment = "center"
    if y_offset > 0:
        vertical_alignment = "bottom"
    elif y_offset < 0:
        vertical_alignment = "top"
    ax.annotate(
        text,
        xy=(x_value, y_value),
        xytext=(x_offset, y_offset),
        textcoords="offset points",
        color=color,
        ha="right" if x_offset < 0 else "left",
        va=vertical_alignment,
        bbox={
            "facecolor": "#FFFFFF",
            "edgecolor": color,
            "boxstyle": "round,pad=0.22",
            "alpha": 0.92,
        },
        fontproperties=font_props(size=8.8),
        annotation_clip=False,
    )


def annotate_series_endpoints(
    ax,
    endpoints: Sequence[tuple[Any, float, str, str]],
    *,
    min_gap_px: float = 32.0,
    fixed_x_offset: int | None = None,
) -> None:
    if not endpoints:
        return

    x_axis_min = ax.get_xlim()[0]
    lower_bound = ax.transAxes.transform((0.0, 0.0))[1] + 10.0
    upper_bound = ax.transAxes.transform((0.0, 1.0))[1] - 10.0
    dpi = float(ax.figure.dpi) if ax.figure is not None else 180.0

    display_entries: list[dict[str, Any]] = []
    for x_value, y_value, text, color in endpoints:
        _, y_ratio = _normalized_point_position(ax, x_value, y_value)
        x_ratio, _ = _normalized_point_position(ax, x_value, y_value)
        base_x_offset = (
            float(fixed_x_offset)
            if fixed_x_offset is not None
            else (-34 if x_ratio >= 0.9 else (-24 if x_ratio >= 0.76 else 8))
        )
        if y_ratio <= 0.12:
            base_y_offset = 14.0
        elif y_ratio <= 0.2:
            base_y_offset = 10.0
        elif y_ratio >= 0.84:
            base_y_offset = -10.0
        else:
            base_y_offset = 0.0
        display_y = float(ax.transData.transform((x_axis_min, y_value))[1])
        display_entries.append(
            {
                "endpoint": (x_value, y_value, text, color),
                "display_y": display_y,
                "base_x_offset": base_x_offset,
                "base_y_offset": base_y_offset,
            }
        )

    display_entries.sort(key=lambda entry: entry["display_y"])
    adjusted_positions = [entry["display_y"] for entry in display_entries]
    for index in range(1, len(adjusted_positions)):
        adjusted_positions[index] = max(adjusted_positions[index], adjusted_positions[index - 1] + min_gap_px)
    if adjusted_positions:
        if adjusted_positions[-1] > upper_bound:
            shift_down = adjusted_positions[-1] - upper_bound
            adjusted_positions = [position - shift_down for position in adjusted_positions]
        for index in range(len(adjusted_positions) - 2, -1, -1):
            adjusted_positions[index] = min(adjusted_positions[index], adjusted_positions[index + 1] - min_gap_px)
        if adjusted_positions[0] < lower_bound:
            shift_up = lower_bound - adjusted_positions[0]
            adjusted_positions = [position + shift_up for position in adjusted_positions]

    for entry, adjusted_display_y in zip(display_entries, adjusted_positions):
        x_value, y_value, text, color = entry["endpoint"]
        y_delta_points = (adjusted_display_y - entry["display_y"]) * 72.0 / dpi
        annotate_series_endpoint(
            ax,
            x_value,
            y_value,
            text,
            color=color,
            x_offset=int(round(entry["base_x_offset"])),
            y_offset=int(round(entry["base_y_offset"] + y_delta_points)),
        )

def _header_wrap_width(fig, *, chars_per_inch: float, minimum: int, maximum: int) -> int:
    figure_width = float(fig.get_size_inches()[0]) if fig is not None else 12.0
    estimated = int(round(figure_width * chars_per_inch))
    return max(minimum, min(maximum, estimated))


def _normalized_point_position(ax, x_value: Any, y_value: float) -> tuple[float, float]:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    x_numeric = _coerce_x_numeric(x_value)
    x_ratio = 0.5 if x_max == x_min else (x_numeric - x_min) / (x_max - x_min)
    y_ratio = 0.5 if y_max == y_min else (float(y_value) - y_min) / (y_max - y_min)
    return max(0.0, min(1.0, x_ratio)), max(0.0, min(1.0, y_ratio))


def _coerce_x_numeric(x_value: Any) -> float:
    if isinstance(x_value, (pd.Timestamp,)):
        return float(mdates.date2num(pd.Timestamp(x_value).to_pydatetime()))
    if hasattr(x_value, "to_pydatetime"):
        return float(mdates.date2num(pd.Timestamp(x_value).to_pydatetime()))
    return float(x_value)


def compute_time_focus_window(
    frame: pd.DataFrame,
    *,
    value_columns: Sequence[str],
    scenario_start: pd.Timestamp | None = None,
    date_column: str = "date",
    pre_days: int = 4,
    post_days: int = 8,
    min_window_days: int = 18,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if frame.empty or date_column not in frame.columns:
        return None

    working = frame.copy()
    working[date_column] = pd.to_datetime(working[date_column])
    working = working.sort_values(date_column).reset_index(drop=True)
    min_date = pd.Timestamp(working[date_column].min())
    max_date = pd.Timestamp(working[date_column].max())
    if pd.isna(min_date) or pd.isna(max_date):
        return None

    anchor_dates: list[pd.Timestamp] = []
    for column in value_columns:
        if column not in working.columns:
            continue
        values = pd.to_numeric(working[column], errors="coerce").fillna(0.0)
        normalized_name = str(column).lower()
        if any(token in normalized_name for token in ["service_level", "rate", "fulfillment"]):
            interest_mask = values < 0.999
        else:
            interest_mask = values.abs() > 1e-9
        change_mask = values.diff().abs().fillna(0.0) > 1e-9
        dates = working.loc[interest_mask | change_mask, date_column].tolist()
        anchor_dates.extend(pd.Timestamp(value) for value in dates)

    focus_start = pd.Timestamp(scenario_start) if scenario_start is not None else min_date
    focus_end = max(anchor_dates) if anchor_dates else max_date

    start = max(min_date, focus_start - pd.Timedelta(days=pre_days))
    end = min(max_date, focus_end + pd.Timedelta(days=post_days))
    if end <= start:
        end = min(max_date, start + pd.Timedelta(days=min_window_days))
    if (end - start).days < min_window_days:
        desired_end = start + pd.Timedelta(days=min_window_days)
        if desired_end <= max_date:
            end = desired_end
        else:
            start = max(min_date, max_date - pd.Timedelta(days=min_window_days))
            end = max_date
    return start, end


def apply_time_focus(
    ax,
    frame: pd.DataFrame,
    *,
    value_columns: Sequence[str],
    scenario_start: pd.Timestamp | None = None,
    date_column: str = "date",
    pre_days: int = 4,
    post_days: int = 8,
    min_window_days: int = 18,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    window = compute_time_focus_window(
        frame,
        value_columns=value_columns,
        scenario_start=scenario_start,
        date_column=date_column,
        pre_days=pre_days,
        post_days=post_days,
        min_window_days=min_window_days,
    )
    if window is None:
        return None
    ax.set_xlim(window)
    return window


def qualitative_color_map(labels: Iterable[str]) -> dict[str, str]:
    unique_labels = sorted({str(label) for label in labels})
    return {
        label: QUALITATIVE_COLORS[index % len(QUALITATIVE_COLORS)]
        for index, label in enumerate(unique_labels)
    }


def policy_profile_color_map(labels: Iterable[str]) -> dict[str, str]:
    unique_labels = [str(label) for label in labels]
    fallback_map = qualitative_color_map(unique_labels)
    return {
        label: POLICY_PROFILE_COLORS.get(label, fallback_map.get(label, QUALITATIVE_COLORS[0]))
        for label in unique_labels
    }


def policy_profile_linestyle_map(labels: Iterable[str]) -> dict[str, Any]:
    return {
        str(label): POLICY_PROFILE_LINESTYLES.get(str(label), "-")
        for label in labels
    }


def format_date_axis(ax) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    formatter = mdates.DateFormatter("%Y-%m-%d")
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    tick_font = font_props(size=10.0)
    for label in ax.get_xticklabels():
        if tick_font is not None:
            label.set_fontproperties(tick_font)
        label.set_rotation(0)
        label.set_horizontalalignment("center")


def add_scenario_marker(ax, scenario_start: pd.Timestamp, label: str = "场景开始") -> None:
    marker_date = pd.Timestamp(scenario_start)
    ax.axvline(marker_date, color=THEME["accent"], linestyle=(0, (3, 2)), linewidth=1.4, alpha=0.9)
    ymin, ymax = ax.get_ylim()
    ax.text(
        marker_date,
        ymax - (ymax - ymin) * 0.06,
        label,
        color=THEME["accent"],
        fontsize=9.2,
        ha="left",
        va="top",
        bbox={
            "facecolor": "#FFF1F2",
            "edgecolor": "#F8B4BD",
            "boxstyle": "round,pad=0.22",
            "alpha": 0.9,
        },
        fontproperties=font_props(size=9.2),
    )


def _wrap_header_text(text: str | None, *, width: int) -> list[str]:
    if text is None:
        return []
    raw = str(text).strip()
    if not raw:
        return []
    scenario_suffix = re.search(r"([A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)$", raw)
    if scenario_suffix is not None and len(raw) > width:
        prefix_text = raw[: scenario_suffix.start()].rstrip()
        suffix_text = scenario_suffix.group(1).strip()
        if prefix_text and suffix_text:
            return [prefix_text, suffix_text]
    for delimiter in ("：", ":"):
        if delimiter in raw and len(raw) > width:
            prefix, suffix = raw.split(delimiter, 1)
            prefix_line = f"{prefix}{delimiter}".strip()
            suffix_text = suffix.strip()
            if prefix_line and suffix_text:
                remaining = textwrap.wrap(
                    suffix_text,
                    width=width,
                    break_long_words=True,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                return [prefix_line] + (remaining or [suffix_text])
    wrapped = textwrap.wrap(
        raw,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=False,
    )
    return wrapped or [raw]
