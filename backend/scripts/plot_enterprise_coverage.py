from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


POLICIES = [
    ("bounded_cap2_window_4", "RBSC\nw=4"),
    ("bounded_cap2_window_8", "RBSC\nw=8"),
    ("bounded_cap2_window_12", "RBSC\nw=12"),
    ("source_cap_2", "Cap 2\nunbounded"),
    ("source_diverse_topk", "One per\ndocument"),
    ("intent_routed_source_cap_2", "Intent\nrouted"),
    ("oracle_intent_upper_bound", "Gold-label\noracle"),
]


def _difference_and_ci(interval: dict[str, object], metric: str) -> tuple[float, list[float]]:
    value = float(interval[f"multi_gold_{metric}_difference"])
    ci = [float(item) for item in interval[f"multi_gold_{metric}_difference_95pct_bootstrap_ci"]]
    return value, ci


def plot_results(results_path: Path, output_path: Path) -> None:
    result = json.loads(results_path.read_text(encoding="utf-8"))
    paired = result["paired_bootstrap_differences_vs_global_bm25"]
    labels = [label for _, label in POLICIES]
    recall_values, recall_low, recall_high = [], [], []
    precision_values, precision_low, precision_high = [], [], []
    for config, _ in POLICIES:
        interval = paired[config]
        recall, recall_ci = _difference_and_ci(interval, "document_recall_at_k")
        precision, precision_ci = _difference_and_ci(interval, "chunk_precision_at_k")
        recall_values.append(recall * 100)
        recall_low.append((recall - recall_ci[0]) * 100)
        recall_high.append((recall_ci[1] - recall) * 100)
        precision_values.append(precision * 100)
        precision_low.append((precision - precision_ci[0]) * 100)
        precision_high.append((precision_ci[1] - precision) * 100)

    width, height = 1650, 750
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    regular_path = Path(r"C:\Windows\Fonts\arial.ttf")
    bold_path = Path(r"C:\Windows\Fonts\arialbd.ttf")
    try:
        title_font = ImageFont.truetype(str(bold_path), 29)
        panel_font = ImageFont.truetype(str(bold_path), 25)
        label_font = ImageFont.truetype(str(regular_path), 19)
        tick_font = ImageFont.truetype(str(regular_path), 17)
    except OSError:
        title_font = panel_font = label_font = tick_font = ImageFont.load_default()
    ink, grid = "#1F2933", "#D8DEE5"
    colors = ["#138A72", "#69A89A", "#9CBDB5", "#D1A23B", "#B85847", "#527EA6", "#7364A6"]
    n_multi = result["configurations"]["global_bm25_topk"]["by_gold_source_count"]["multi_gold_source"]["queries"]
    title = f"Multi-document questions (n={n_multi}); paired 95% bootstrap intervals"
    bounds = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((width - (bounds[2] - bounds[0])) // 2, 22), title, fill=ink, font=title_font)

    def draw_panel(panel_x: int, title: str, values: list[float], lows: list[float], highs: list[float],
                   y_min: float, y_max: float, y_label: str) -> None:
        panel_w = 775
        chart_left, chart_top = panel_x + 85, 145
        chart_w, chart_h = 640, 410
        draw.text((panel_x + 55, 78), title, fill=ink, font=panel_font)
        draw.text((panel_x + 55, 111), y_label, fill=ink, font=label_font)
        for tick in range(5):
            value = y_min + (y_max - y_min) * tick / 4
            y = chart_top + chart_h - int(chart_h * tick / 4)
            draw.line((chart_left, y, chart_left + chart_w, y), fill=grid, width=2)
            text = f"{value:.0f}"
            bb = draw.textbbox((0, 0), text, font=tick_font)
            draw.text((chart_left - (bb[2] - bb[0]) - 12, y - 11), text, fill=ink, font=tick_font)
        draw.line((chart_left, chart_top, chart_left, chart_top + chart_h), fill=ink, width=2)
        draw.line((chart_left, chart_top + chart_h, chart_left + chart_w, chart_top + chart_h), fill=ink, width=2)
        zero_y = chart_top + chart_h - int((0 - y_min) / (y_max - y_min) * chart_h)
        draw.line((chart_left, zero_y, chart_left + chart_w, zero_y), fill="#606B75", width=2)
        slot = chart_w / len(labels)
        bar_w = 48
        for idx, label in enumerate(labels):
            center = chart_left + int(slot * (idx + 0.5))
            val = values[idx]
            low = val - lows[idx]
            high = val + highs[idx]
            y_val = chart_top + chart_h - int((val - y_min) / (y_max - y_min) * chart_h)
            y_low = chart_top + chart_h - int((low - y_min) / (y_max - y_min) * chart_h)
            y_high = chart_top + chart_h - int((high - y_min) / (y_max - y_min) * chart_h)
            draw.rectangle((center - bar_w // 2, min(zero_y, y_val), center + bar_w // 2, max(zero_y, y_val)), fill=colors[idx], outline=ink, width=1)
            draw.line((center, y_high, center, y_low), fill=ink, width=2)
            draw.line((center - 8, y_high, center + 8, y_high), fill=ink, width=2)
            draw.line((center - 8, y_low, center + 8, y_low), fill=ink, width=2)
            for line_number, line in enumerate(label.split("\n")):
                bb = draw.textbbox((0, 0), line, font=tick_font)
                draw.text((center - (bb[2] - bb[0]) // 2, chart_top + chart_h + 14 + line_number * 21), line, fill=ink, font=tick_font)

    draw_panel(30, "Evidence-set coverage", recall_values, recall_low, recall_high,
               min(-2, min(recall_values + [0]) - 1), max(16, max(recall_values) + 2),
               "Δ doc recall@8 (pp)")
    draw_panel(830, "Retrieved-context proxy", precision_values, precision_low, precision_high,
               min(-30, min(precision_values + [0]) - 2), max(4, max(precision_values) + 2),
               "Δ gold-doc chunk share@8 (pp)")
    footnote = "Positive recall gains can reduce the share of chunks drawn from annotated gold documents."
    bb = draw.textbbox((0, 0), footnote, font=label_font)
    draw.text(((width - (bb[2] - bb[0])) // 2, height - 39), footnote, fill=ink, font=label_font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, dpi=(300, 300), optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot EnterpriseRAG-Bench source-coverage ablations.")
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", default=None, type=Path)
    args = parser.parse_args()
    output_path = args.output or Path(__file__).resolve().parents[2] / "docs" / "paper_assets" / "rbsc_tradeoff.png"
    plot_results(args.results, output_path.resolve())
    print(output_path.resolve())


if __name__ == "__main__":
    main()
