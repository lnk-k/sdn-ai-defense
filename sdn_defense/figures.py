"""使用真实结果生成可导出的报告图；图内英文避免平台中文字体依赖。"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sdn_defense.report import json_lines, throughput


def generate(root="artifacts", output="docs/figures"):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = json.loads((root / "results.json").read_text())
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 140})
    methods = ("off", "threshold", "rf")
    titles = ("No defense", "Threshold", "Random forest")
    colors = ("#64748b", "#e6a23c", "#0d9488")

    fig, ax = plt.subplots(figsize=(8, 4.4), layout="constrained")
    scenarios = ("normal", "icmp", "udp")
    x = np.arange(3)
    for i, (method, title, color) in enumerate(zip(methods, titles, colors)):
        groups = [next(g for g in result["groups"] if g["method"] == method and g["scenario"] == s) for s in scenarios]
        values = [g["during_attack_mbps"]["mean"] for g in groups]
        centers = x + (i - 1) * 0.24
        ax.bar(centers, values, 0.23, label=title, color=color, zorder=3)
        for center, scenario, value in zip(centers, scenarios, values):
            observed = [r["during_attack_mbps"] for r in result["runs"] if r["scenario"]==scenario and r["method"]==method]
            offsets = np.linspace(-0.035, 0.035, len(observed))
            ax.scatter(center+offsets, observed, s=16, color="#182533", zorder=4)
            ax.text(center, value+0.3, f"{value:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x, ["Normal background", "ICMP flood", "UDP flood"])
    ax.set_ylabel("Normal TCP receiver throughput (Mbit/s)")
    ax.set_title("TCP throughput: bars = means; dots = individual runs", pad=36)
    ax.grid(axis="y", alpha=0.2, zorder=0)
    ax.set_ylim(0, 12)
    ax.legend(ncols=3, loc="lower center", bbox_to_anchor=(0.5, 1.005), frameon=False)
    fig.savefig(output / "throughput-comparison.png")
    fig.savefig(output / "throughput-comparison.svg")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(8, 3.8), layout="constrained")
    for ax, method, title in zip(axes, ("threshold", "rf"), titles[1:]):
        matrix = np.array(result["classifier"][method]["confusion_matrix"])
        ax.imshow(matrix, cmap="Blues", vmin=0)
        for (row, col), value in np.ndenumerate(matrix):
            ax.text(col, row, str(value), ha="center", va="center",
                    color="white" if value > matrix.max() / 2 else "#15202b", fontsize=18)
        ax.set_xticks([0, 1], ["Normal", "Attack"])
        ax.set_yticks([0, 1], ["Normal", "Attack"])
        ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
        ax.set_title(title)
    fig.suptitle("Independent test runs: confusion matrices")
    fig.savefig(output / "confusion-matrices.png")
    plt.close(fig)

    # 固定使用第 1 次 UDP 对照轮次，避免事后选择最漂亮的实验。
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, layout="constrained")
    for ax, method, title, color in zip(axes, methods, titles, colors):
        directory = root / "benchmark" / f"udp-{method}-00"
        meta = json.loads((directory / "metadata.json").read_text())
        series = throughput(directory / "receiver.json")
        ax.plot([(r["start"] + r["end"]) / 2 for r in series],
                [r["mbps"] for r in series], color=color, linewidth=2, marker=".")
        ax.axvspan(meta["scenario_started"]-meta["started"], meta["scenario_ended"]-meta["started"],
                   color="#f59e0b", alpha=0.1, label="Scenario active")
        for event in json_lines(directory / "events.jsonl"):
            if event["kind"] == "rule_ack":
                ax.axvline(event["time"]-meta["started"], color="#ef4444", linestyle="--", alpha=0.7)
        ax.set_title(f"{title} | {meta['id']}", loc="left")
        ax.set_ylim(0, 14); ax.set_ylabel("TCP Mbit/s"); ax.grid(alpha=0.2)
    axes[-1].set_xlabel("Seconds from normal business start")
    fig.suptitle("UDP comparison / seed 900: shade = traffic active; dashed = rule acknowledged")
    fig.savefig(output / "udp-timeline.png")
    fig.savefig(output / "udp-timeline.svg")
    plt.close(fig)
    print(f"真实结果图已保存到 {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="artifacts")
    p.add_argument("--output", default="docs/figures")
    a = p.parse_args()
    generate(a.root, a.output)
