"""按独立实验轮次划分训练/验证/测试集，防止相邻窗口泄漏。"""
import argparse
import csv
import json
from pathlib import Path
import time
import hashlib

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

from sdn_defense.core import FEATURES, SCHEMA, vector
from sdn_defense.journal import record


def load_rows(root):
    rows = []
    for file in sorted(Path(root).glob("*/metadata.json")):
        meta = json.loads(file.read_text())
        if meta.get("status") != "completed" or meta["method"] != "off":
            continue
        if meta.get("split") not in {"train", "validation", "test"}:
            continue
        for line in (file.parent / "samples.jsonl").read_text().splitlines():
            row = json.loads(line)
            # 排除空闲规则和过渡窗口；标签来自流量编排，绝不来自检测器预测。
            if row["packets"] < 3 or row["blocked"]:
                continue
            start, end = meta["scenario_started"], meta["scenario_ended"]
            inside = row["window_start"] >= start + 1 and row["window_end"] <= end - 1
            outside = row["window_end"] < start or row["window_start"] > end + 1
            attacker = row["src"] == "10.0.0.3" and meta["scenario"] != "normal"
            if attacker and not (inside or outside):
                continue
            label = int(attacker and inside and row["protocol"] == {"icmp": 1, "udp": 17}.get(meta["scenario"]))
            rows.append({**row, "label": label, "run_id": meta["id"], "split": meta["split"], "scenario": meta["scenario"]})
    if not rows:
        raise ValueError("没有可训练的已完成采集轮次，请先运行 collect")
    return rows


def metrics(y, prediction):
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    return {"accuracy": float(accuracy_score(y, prediction)),
            "precision": float(precision_score(y, prediction, zero_division=0)),
            "recall": float(recall_score(y, prediction, zero_division=0)),
            "f1": float(f1_score(y, prediction, zero_division=0)),
            "false_positive_rate": float(fp / (fp+tn)) if fp+tn else 0,
            "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]]}


def fit(root, output):
    rows = load_rows(root)
    groups = {split: {r["run_id"] for r in rows if r["split"] == split} for split in ("train", "validation", "test")}
    assert not groups["train"] & groups["test"] and not groups["train"] & groups["validation"] and not groups["validation"] & groups["test"]
    datasets = {}
    for split in groups:
        part = [r for r in rows if r["split"] == split]
        if {r["label"] for r in part} != {0, 1}:
            raise ValueError(f"{split} 必须包含正常和异常两类样本")
        datasets[split] = (np.array([vector(r) for r in part]), np.array([r["label"] for r in part]))
    model = RandomForestClassifier(n_estimators=120, max_depth=8, min_samples_leaf=2,
                                   class_weight="balanced", random_state=2026, n_jobs=1)
    model.fit(*datasets["train"])
    vx, vy = datasets["validation"]
    probability = model.predict_proba(vx)[:, list(model.classes_).index(1)]
    def selection(pred):
        m = metrics(vy, pred)
        return m["f1"], -m["false_positive_rate"]
    rf_threshold = max([0.5, 0.6, 0.7, 0.8, 0.9], key=lambda t: selection(probability >= t))
    pps_threshold = max([500, 800, 1200, 1600, 2000, 3000, 4000, 6000], key=lambda t: selection(vx[:, 0] >= t))
    tx, ty = datasets["test"]
    report = {"source": "real-mininet", "schema": SCHEMA, "features": FEATURES,
              "groups": {k: sorted(v) for k, v in groups.items()},
              "sample_counts": {k: len(v[1]) for k, v in datasets.items()},
              "probability_threshold": rf_threshold, "threshold_pps": pps_threshold,
              "limitations": "同一固定拓扑的受控已知攻击；不代表互联网未知攻击泛化能力。"}
    for name in ("threshold", "rf"):
        predictions, elapsed = [], []
        for x in tx:
            before = time.perf_counter_ns()
            value = bool(x[0] >= pps_threshold) if name == "threshold" else bool(model.predict_proba([x])[0, list(model.classes_).index(1)] >= rf_threshold)
            elapsed.append((time.perf_counter_ns()-before)/1e6)
            predictions.append(value)
        report[name] = {**metrics(ty, predictions), "inference_mean_ms": float(np.mean(elapsed)), "inference_p95_ms": float(np.percentile(elapsed, 95))}
    report["feature_importance"] = dict(zip(FEATURES, model.feature_importances_.tolist()))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    dataset_file = output.parent / "dataset.csv"
    fields = ["run_id", "split", "scenario", "src", "protocol", "window_start", "window_end", "label", *FEATURES]
    with dataset_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    report["dataset_sha256"] = hashlib.sha256(dataset_file.read_bytes()).hexdigest()
    joblib.dump({"model": model, "features": FEATURES, "schema": SCHEMA,
                 "probability_threshold": rf_threshold, "dataset_sha256": report["dataset_sha256"]}, output)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    record("训练与评估", "训练完成，已按独立轮次保存模型和测试结果。",
           {"model": str(output), "sample_counts": report["sample_counts"],
            "threshold_pps": pps_threshold, "probability_threshold": rf_threshold,
            "dataset_sha256": report["dataset_sha256"]})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="artifacts/collection")
    p.add_argument("--output", default="models/random_forest.joblib")
    a = p.parse_args()
    fit(a.data, a.output)
