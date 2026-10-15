"""独立核验交付数据；有漏轮、协议错误或缺少丢弃证据时退出失败。"""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdn_defense.report import summarize_run, throughput
from sdn_defense.journal import record


def main():
    errors, findings, counts = [], [], {}
    for stage, expected in (("collection", 18), ("benchmark", 18)):
        dirs = sorted((ROOT / "artifacts" / stage).glob("*/metadata.json"))
        counts[stage] = len(dirs)
        if len(dirs) != expected:
            errors.append(f"{stage}: 预期 {expected} 轮，实际 {len(dirs)}")
        for file in dirs:
            meta = json.loads(file.read_text())
            if meta["status"] != "completed":
                errors.append(f"{file.parent.name}: 未完成")
                continue
            for name in ("samples", "events"):
                lines = (file.parent / f"{name}.jsonl").read_text().splitlines()
                if not lines:
                    errors.append(f"{file.parent.name}: 缺少 {name}")
                for line in lines:
                    row = json.loads(line)
                    if row.get("kind") in {"openflow_error", "stats_timeout"}:
                        errors.append(f"{file.parent.name}: {row['kind']}")
            if not throughput(file.parent / "receiver.json"):
                errors.append(f"{file.parent.name}: 缺少实际接收吞吐量")
            if stage == "benchmark":
                row = summarize_run(file.parent)
                if row["false_blocks"]:
                    findings.append(f"{meta['id']}: 非目标或场景外封禁 {row['false_blocks']} 次，保留在结果表中")
                if meta["scenario"] != "normal" and meta["method"] != "off" and not row["drop_confirmed"]:
                    findings.append(f"{meta['id']}: 未确认丢弃，保留漏检结果")
    model = json.loads((ROOT / "models/random_forest.json").read_text())
    digest = hashlib.sha256((ROOT / "models/dataset.csv").read_bytes()).hexdigest()
    if digest != model["dataset_sha256"]:
        errors.append("数据集 SHA-256 不匹配")
    groups = [set(v) for v in model["groups"].values()]
    if sum(map(len, groups)) != len(set().union(*groups)):
        errors.append("训练/验证/测试轮次重叠")
    manifest = json.loads((ROOT / "docs/verification/experiment-manifest.json").read_text())
    # 只核查对照期间使用的执行代码和冻结模型；报告与日志工具可继续完善。
    for name in ("sdn_defense/core.py", "sdn_defense/controller.py", "sdn_defense/lab.py",
                 "sdn_defense/traffic.py", "sdn_defense/experiment.py", "models/random_forest.joblib"):
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != manifest["sha256"][name]:
            errors.append(f"冻结文件改变：{name}")
    result = {"checked_at": datetime.now().astimezone().isoformat(),
              "passed": not errors, "counts": counts, "errors": errors, "performance_findings": findings,
              "note": "passed 仅表示原始证据完整且一致；性能不足单列，不隐藏误封、漏检或调整模型。仅验证课设实验范围。"}
    (ROOT / "docs/verification/acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    record("交付验收", "原始证据核验通过" if not errors else "原始证据核验发现问题", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
