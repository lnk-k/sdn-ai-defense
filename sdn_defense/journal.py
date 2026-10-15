"""开发与实验日志：人可读 Markdown、可解析 JSONL，追加写入并避免重复补录。"""
import argparse
from datetime import datetime
import fcntl
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def record(stage, message, details=None, event_id=None):
    directory = ROOT / "docs" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    json_file = directory / "journal.jsonl"
    markdown = ROOT / "docs" / "开发与实验日志.md"
    with (directory / ".journal.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if event_id and json_file.exists():
            for line in json_file.read_text().splitlines():
                if json.loads(line).get("event_id") == event_id:
                    return
        row = {"recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "stage": stage, "message": message, "details": details or {}}
        if event_id:
            row["event_id"] = event_id
        with json_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if not markdown.exists():
            markdown.write_text("# 开发与实验日志\n\n记录时间为日志写入时间；历史实验补录的实际开始、结束时间列在详情中。失败记录保留，不用成功实验覆盖。机器可读副本见 `logs/journal.jsonl`。\n\n| 记录时间 | 阶段 | 记录 | 详情 |\n| --- | --- | --- | --- |\n", encoding="utf-8")
        def cell(value):
            return str(value).replace("|", "\\|").replace("\n", "<br>")
        details_text = json.dumps(row["details"], ensure_ascii=False) if details else "—"
        with markdown.open("a", encoding="utf-8") as f:
            f.write("| " + " | ".join(map(cell, [row["recorded_at"], stage, message, details_text])) + " |\n")


def import_runs(root):
    for file in sorted(Path(root).glob("*/*/metadata.json")):
        meta = json.loads(file.read_text())
        if meta.get("status") not in {"completed", "failed"}:
            continue
        details = {k: meta[k] for k in ("status", "scenario", "method", "seed", "split", "error") if k in meta}
        details["directory"] = str(file.parent.relative_to(ROOT))
        for key in ("started", "ended"):
            if key in meta:
                details[key] = datetime.fromtimestamp(meta[key]).astimezone().isoformat(timespec="seconds")
        record("历史实验补录", meta["id"], details, f"run:{file.parent.resolve()}:{meta['status']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("message", nargs="?")
    p.add_argument("--stage", default="开发")
    p.add_argument("--import-runs", action="store_true")
    p.add_argument("--root", default=str(ROOT / "artifacts"))
    a = p.parse_args()
    if a.import_runs:
        import_runs(a.root)
    if a.message:
        record(a.stage, a.message)
