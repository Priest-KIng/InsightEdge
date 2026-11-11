"""Generate aligned, paper-sized result charts from the recorded evaluations."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "docs/paper_reproducibility/score_gated_coverage/findings_summary.json"
ASSETS = ROOT / "docs/paper_assets"

INK = "#18324B"
MUTED = "#586A7B"
GRID = "#D8E0E7"
BLUE = "#3B78A1"
TEAL = "#2D806B"
AMBER = "#C77B35"
GRAY = "#8996A3"
PALE = "#F5F8FA"


def font(size: int, bold: bool = False):
    path = Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def canvas(width: int, height: int, title: str, subtitle: str):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((width // 2, 25), title, fill=INK, font=font(40, True), anchor="mt")
    draw.text((width // 2, 78), subtitle, fill=MUTED, font=font(25), anchor="mt")
    return image, draw


def legend_item(draw, x, y, color, label, size=23):
    draw.rounded_rectangle((x, y - 12, x + 24, y + 12), radius=5, fill=color)
    draw.text((x + 34, y), label, fill=INK, font=font(size), anchor="lm")


def save(image: Image.Image, name: str) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    image.save(ASSETS / name, dpi=(300, 300), optimize=True)


def retrieval_latency() -> None:
    image, draw = canvas(
        1200, 690,
        "Fixture retrieval latency",
        "Median query time across a 16-question fixture; lower is faster",
    )
    rows = [
        ("Lexical", 3.91, TEAL),
        ("Dense", 45.12, BLUE),
        ("Rerank mode*", 45.85, BLUE),
        ("Adaptive router", 47.71, BLUE),
        ("Hybrid", 47.85, BLUE),
        ("Compression", 48.03, BLUE),
    ]
    left, right, top, bottom = 350, 1100, 160, 565
    maximum = 50.0
    for tick in range(0, 51, 10):
        x = left + tick / maximum * (right - left)
        draw.line((x, top, x, bottom), fill=GRID, width=2)
        draw.text((x, bottom + 12), str(tick), fill=MUTED, font=font(21), anchor="mt")
    draw.text(((left + right) / 2, bottom + 48), "Median retrieval latency (ms)", fill=INK, font=font(25), anchor="mt")
    for i, (label, value, color) in enumerate(rows):
        y = top + 35 + i * 61
        draw.text((left - 20, y), label, fill=INK, font=font(25), anchor="rm")
        x = left + value / maximum * (right - left)
        draw.rounded_rectangle((left, y - 15, max(left + 5, x), y + 15), radius=8, fill=color)
        draw.text((x + 12, y), f"{value:.1f} ms", fill=INK, font=font(23, True), anchor="lm")
    draw.text((55, 655), "* No cross-encoder was configured for this row.", fill=MUTED, font=font(20), anchor="lm")
    save(image, "retrieval_quality_latency.png")


def scope_contract() -> None:
    image, draw = canvas(
        1200, 555,
        "File-scope filtering blocks distractor chunks",
        "Controlled near-duplicate test · 24 named-file questions · top-3 retrieval",
    )
    legend_item(draw, 305, 139, AMBER, "Unscoped")
    legend_item(draw, 575, 139, TEAL, "File-filtered")
    left, right, top, bottom = 400, 1110, 185, 450
    maximum = 100.0
    for tick in range(0, 101, 25):
        x = left + tick / maximum * (right - left)
        draw.line((x, top, x, bottom), fill=GRID, width=2)
        draw.text((x, bottom + 9), f"{tick}%", fill=MUTED, font=font(20), anchor="mt")
    rows = [
        ("Target document\nretrieved", 100.0, 100.0),
        ("Out-of-scope\nchunks", 66.7, 0.0),
    ]
    for i, (label, unscoped, filtered) in enumerate(rows):
        center = top + 72 + i * 125
        draw.multiline_text((55, center), label, fill=INK, font=font(24, True), anchor="lm", spacing=2)
        for offset, value, color, text in [
            (-18, unscoped, AMBER, f"{unscoped:.1f}%" if unscoped % 1 else f"{unscoped:.0f}%"),
            (18, filtered, TEAL, f"{filtered:.1f}%" if filtered % 1 else f"{filtered:.0f}%"),
        ]:
            y = center + offset
            x = left + value / maximum * (right - left)
            draw.rounded_rectangle((left, y - 11, max(left + 5, x), y + 11), radius=6, fill=color)
            label_x = x + 11 if value < 93 else x - 10
            anchor = "lm" if value < 93 else "rm"
            draw.text((label_x, y), text, fill=INK, font=font(21, True), anchor=anchor)
    draw.text((width_center := (left + right) / 2, bottom + 42), "Share of retrieved chunks / questions (%)", fill=INK, font=font(23), anchor="mt")
    save(image, "scope_contract_results.png")


def live_latency() -> None:
    image, draw = canvas(
        1200, 650,
        "Response time by prompt type",
        "Five single-run Phi-3 Mini service probes; shorter is faster",
    )
    rows = [
        ("Named-file summary", 7.42, BLUE),
        ("Injection in document", 5.59, AMBER),
        ("Workspace overview", 4.63, BLUE),
        ("Named fact", 1.80, BLUE),
        ("Unsupported request", 0.11, GRAY),
    ]
    left, right, top, bottom = 390, 1100, 150, 515
    maximum = 8.0
    for tick in range(0, 9, 2):
        x = left + tick / maximum * (right - left)
        draw.line((x, top, x, bottom), fill=GRID, width=2)
        draw.text((x, bottom + 10), f"{tick} s", fill=MUTED, font=font(21), anchor="mt")
    for i, (label, value, color) in enumerate(rows):
        y = top + 34 + i * 63
        draw.text((left - 20, y), label, fill=INK, font=font(24), anchor="rm")
        x = left + value / maximum * (right - left)
        draw.rounded_rectangle((left, y - 14, max(left + 5, x), y + 14), radius=7, fill=color)
        draw.text((x + 12, y), f"{value:.2f} s", fill=INK, font=font(22, True), anchor="lm")
    draw.text((55, 618), "Refusal returned without model generation; timings vary between runs.", fill=MUTED, font=font(20), anchor="lm")
    save(image, "live_local_latency.png")


def source_coverage_findings() -> None:
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    er = data["cross_validated_threshold_selection"]["precision_drop_bound_sensitivity"]["0.025"]
    mh = data["multihop_paired_differences_vs_global"]
    left_rows = [
        ("All queries\n(n=470)", er["paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"] * 100, -er["paired_difference_vs_global_bm25"]["chunk_precision_at_k"]["mean"] * 100),
        ("Multi-source\n(n=92)", er["multi_gold_paired_difference_vs_global_bm25"]["document_recall_at_k"]["mean"] * 100, -er["multi_gold_paired_difference_vs_global_bm25"]["chunk_precision_at_k"]["mean"] * 100),
    ]
    right_rows = [
        ("Routed gate", mh["intent_routed_relevance_gated"]["document_recall_at_8"]["mean_difference"] * 100, -mh["intent_routed_relevance_gated"]["gold_document_chunk_share_at_8"]["mean_difference"] * 100),
        ("Lexical MMR\nλ = 0.6", mh["lexical_mmr_lambda_0.6"]["document_recall_at_8"]["mean_difference"] * 100, -mh["lexical_mmr_lambda_0.6"]["gold_document_chunk_share_at_8"]["mean_difference"] * 100),
        ("Lexical MMR\nλ = 0.8", mh["lexical_mmr_lambda_0.8"]["document_recall_at_8"]["mean_difference"] * 100, -mh["lexical_mmr_lambda_0.8"]["gold_document_chunk_share_at_8"]["mean_difference"] * 100),
    ]
    image = Image.new("RGB", (1800, 920), "white")
    draw = ImageDraw.Draw(image)
    draw.text((900, 26), "Recall gain and context-share cost", fill=INK, font=font(48, True), anchor="mt")
    draw.text((900, 84), "Change from global BM25 · percentage points · larger bars mean larger changes", fill=MUTED, font=font(30), anchor="mt")
    legend_item(draw, 520, 150, BLUE, "Document recall gain", size=28)
    legend_item(draw, 920, 150, AMBER, "Gold-chunk share drop", size=28)
    maximum = 3.1

    def draw_panel(title: str, panel_left: int, panel_right: int, rows: list[tuple[str, float, float]], centers: list[int]) -> None:
        plot_left, plot_right = panel_left + 265, panel_right - 30
        draw.text((panel_left + 10, 215), title, fill=INK, font=font(32, True), anchor="lm")
        for tick in range(4):
            x = plot_left + tick / maximum * (plot_right - plot_left)
            draw.line((x, 265, x, centers[-1] + 45), fill=GRID, width=2)
            draw.text((x, 255), f"{tick} pp", fill=MUTED, font=font(25), anchor="mb")
        for (label, recall, share), center in zip(rows, centers):
            draw.multiline_text((panel_left + 10, center), label, fill=INK, font=font(29), anchor="lm", spacing=3)
            for offset, value, color, suffix in [
                (-19, recall, BLUE, f"+{recall:.2f}"),
                (19, share, AMBER, f"−{share:.2f}"),
            ]:
                y = center + offset
                x = plot_left + value / maximum * (plot_right - plot_left)
                draw.rounded_rectangle((plot_left, y - 11, x, y + 11), radius=7, fill=color)
                draw.text((x + 12, y), suffix, fill=INK, font=font(26, True), anchor="lm")

    draw_panel("EnterpriseRAG · held-out folds", 55, 870, left_rows, [385, 575])
    draw_panel("MultiHop-RAG · frozen-threshold transfer", 930, 1745, right_rows, [345, 505, 665])
    draw.text((55, 785), "Point estimates; paired 95% intervals are reported in the text.", fill=MUTED, font=font(25), anchor="lm")
    draw.text((55, 830), "RBSC and one-source selection have larger recall gains and larger share losses; see Table XII.", fill=MUTED, font=font(24), anchor="lm")
    save(image, "rbsc_tradeoff.png")


def main() -> None:
    retrieval_latency()
    scope_contract()
    live_latency()
    source_coverage_findings()
    for name in ("retrieval_quality_latency.png", "scope_contract_results.png", "live_local_latency.png", "rbsc_tradeoff.png"):
        print(ASSETS / name)


if __name__ == "__main__":
    main()
