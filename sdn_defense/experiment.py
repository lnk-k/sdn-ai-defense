"""一键采集、训练、对照实验；每轮使用全新拓扑，目录禁止覆盖。"""
import argparse
import json
from pathlib import Path
import random
from sdn_defense.lab import run_round


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["collect", "benchmark"])
    p.add_argument("--output", default="artifacts")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--model", default="models/random_forest.joblib")
    args = p.parse_args()
    if args.action == "collect":
        tasks = [(scenario, i) for i in range(6) for scenario in ("normal", "icmp", "udp")]
        for scenario, i in tasks:
            output = Path(args.output) / "collection" / f"{scenario}-{i:02d}"
            if (output / "metadata.json").exists():
                old = json.loads((output / "metadata.json").read_text())
                if old.get("status") == "completed" and old.get("split"):
                    print(f"已有完整证据，跳过 {output}", flush=True)
                    continue
                raise RuntimeError(f"{output} 有未完成记录，请保留该记录并使用新的输出目录重试")
            print(f"采集 {scenario} 轮次 {i+1}/6", flush=True)
            meta = run_round(output, scenario, "off", seed=100+i,
                             duration=18, attack_start=4, attack_end=14)
            meta["split"] = "train" if i < 4 else "validation" if i == 4 else "test"
            (output / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        if not Path(args.model).exists():
            p.error("请先训练模型")
        tasks = [(scenario, method, i) for i in range(args.repeats)
                 for scenario in ("normal", "icmp", "udp") for method in ("off", "threshold", "rf")]
        random.Random(2026).shuffle(tasks)
        for scenario, method, i in tasks:
            output = Path(args.output) / "benchmark" / f"{scenario}-{method}-{i:02d}"
            if (output / "metadata.json").exists():
                if json.loads((output / "metadata.json").read_text()).get("status") == "completed":
                    continue
                raise RuntimeError(f"{output} 已有未完成记录，请使用新的输出目录")
            print(f"评估 {scenario} / {method} / 轮次 {i+1}", flush=True)
            run_round(output, scenario, method, seed=900+i, model=args.model)


if __name__ == "__main__":
    main()
