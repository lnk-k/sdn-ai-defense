"""从真实实验日志生成结果，缺失数据保留为 null，不填造数字。"""
import argparse
import csv
import json
from pathlib import Path
import statistics
from sdn_defense.journal import record


def json_lines(path):
    if not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 实时读取时允许跳过正在写入的最后一行。
    return rows


def throughput(path):
    if not Path(path).exists():
        return []
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError:
        return []
    return [{"start": x["sum"]["start"], "end": x["sum"]["end"],
             "mbps": x["sum"]["bits_per_second"] / 1e6} for x in data.get("intervals", [])]


def mean_phase(series, start, end):
    # 按重叠时间加权，避免较短的最后一个区间被赋予完整权重。
    total, seconds = 0., 0.
    for row in series:
        overlap = max(0, min(end, row["end"])-max(start, row["start"]))
        total += overlap * row["mbps"]
        seconds += overlap
    return total / seconds if seconds else None


def summarize_run(directory):
    directory = Path(directory)
    meta = json.loads((directory / "metadata.json").read_text())
    if meta["status"] != "completed":
        return None
    events = json_lines(directory / "events.jsonl")
    series = throughput(directory / "receiver.json")
    start = meta["started"]
    attack = meta["scenario_started"]
    stop = meta["scenario_ended"]
    real_attack = meta["scenario"] != "normal"
    attack_protocol = {"icmp": 1, "udp": 17}.get(meta["scenario"])
    def is_attack_event(e):
        return (real_attack and e.get("src") == "10.0.0.3"
                and e.get("protocol") == attack_protocol and attack <= e["time"] <= stop)
    def first(kind):
        return next((e["time"] for e in events if e["kind"] == kind and is_attack_event(e)), None)
    request, ack, drop = first("block_requested"), first("rule_ack"), first("drop_observed")
    wrong_target = lambda e: (not real_attack or e.get("src") != "10.0.0.3" or e.get("protocol") != attack_protocol)
    return {"id": meta["id"], "scenario": meta["scenario"], "method": meta["method"], "seed": meta["seed"],
            "baseline_mbps": mean_phase(series, 1, attack-start),
            "during_attack_mbps": mean_phase(series, attack-start+2, stop-start),
            "after_attack_mbps": mean_phase(series, stop-start+1, meta["duration"]),
            "post_rule_mbps": mean_phase(series, ack-start+1, stop-start) if ack else None,
            "detection_latency_s": request-attack if request and real_attack else None,
            "rule_ack_latency_s": ack-request if ack and request and real_attack else None,
            "drop_observed_latency_s": drop-attack if drop and real_attack else None,
            "false_blocks": sum(e["kind"]=="rule_ack" and not is_attack_event(e) for e in events),
            "wrong_target_blocks": sum(e["kind"]=="rule_ack" and wrong_target(e) for e in events),
            "out_of_window_blocks": sum(e["kind"]=="rule_ack" and not wrong_target(e) and not is_attack_event(e) for e in events),
            "drop_confirmed": bool(drop) if real_attack else None,
            "openflow_errors": sum(e["kind"]=="openflow_error" for e in events)}


def generate(root, model):
    root = Path(root)
    rows = [r for f in sorted((root/"benchmark").glob("*/metadata.json")) if (r:=summarize_run(f.parent))]
    if not rows:
        raise ValueError("尚无完成的真实对照实验")
    model_report = json.loads(Path(model).with_suffix(".json").read_text())
    groups = []
    for scenario in ("normal", "icmp", "udp"):
        for method in ("off", "threshold", "rf"):
            items = [r for r in rows if r["scenario"]==scenario and r["method"]==method]
            if not items:
                continue
            group = {"scenario": scenario, "method": method, "repeats": len(items)}
            group["drop_confirmed_runs"] = sum(r["drop_confirmed"] is True for r in items)
            for key in ("baseline_mbps", "during_attack_mbps", "after_attack_mbps", "detection_latency_s", "drop_observed_latency_s", "false_blocks"):
                values = [r[key] for r in items if r[key] is not None]
                group[key] = {"mean": statistics.mean(values) if values else None,
                              "std": statistics.stdev(values) if len(values)>1 else None,
                              "count": len(values)}
            groups.append(group)
    result = {"source": "real-mininet", "classifier": model_report, "runs": rows, "groups": groups}
    (root/"results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with (root/"results.csv").open("w", newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    fmt=lambda x: "未测得" if x is None else f"{x:.3f}"
    text = ["# 真实实验结果", "", "数据来源：Ubuntu + Mininet + Open vSwitch 的实际运行日志。所有数值由脚本计算，未填入预期成绩。", "",
            "## 检测效果（独立测试轮次）", "", "| 方法 | Accuracy | Precision | Recall | F1 | 误报率 | 平均推理 ms |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for name in ("threshold", "rf"):
        m=model_report[name]
        text.append("| "+name+" | "+" | ".join(fmt(m[k]) for k in ("accuracy","precision","recall","f1","false_positive_rate"))+f" | {m['inference_mean_ms']:.6f} |")
    text += ["", "## 正常 TCP 业务吞吐量与响应", "", "测量来自服务端 iperf3 接收区间；单位 Mbit/s。场景期统计从流量开始后第 2 秒到停止，不包含停止后的自然恢复。正常场景的 h3 流量也属于合法背景流量。", "",
             "| 场景 | 方法 | 轮次 | 基线吞吐量 | 场景期吞吐量（均值 ± 样本标准差） | 检测时延 s | 确认丢弃轮次 | 误封次数均值 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for g in groups:
        confirmed = "—" if g['scenario'] == 'normal' else f"{g['drop_confirmed_runs']}/{g['repeats']}"
        text.append(f"| {g['scenario']} | {g['method']} | {g['repeats']} | {fmt(g['baseline_mbps']['mean'])} | {fmt(g['during_attack_mbps']['mean'])} ± {fmt(g['during_attack_mbps']['std'])} | {fmt(g['detection_latency_s']['mean'])} | {confirmed} | {fmt(g['false_blocks']['mean'])} |")
    text += ["", "## 指标口径与限制", "",
             "- 模型推理耗时仅包含一次分类计算；检测时延从攻击进程启动到首次封禁请求，包含采样和连续窗口判定。",
             "- Barrier 回复证明交换机处理了之前的规则消息；drop_observed 是轮询到丢弃规则计数增长的额外证据，其时延是离散采样下的观测上界。",
             "- 暂时封禁 10 秒后规则自动失效，攻击仍在继续时允许再次检测和封禁；不把被封禁期间的零流量当作攻击结束。",
             "- 数据集来自同一台机器、固定拓扑和已知流量生成方法，测试轮次数较少，只能支持课设范围内的结论。",
             "- 所有虚拟主机共享虚拟机 CPU，极端负载会影响测量。高吞吐正常传输可能造成拥塞，拥塞本身不等同于攻击。",
             "- 检测时延只对成功检测的轮次取均值；确认丢弃轮次同时展示，避免漏检被平均时延掩盖。误封包含正常主机、错误协议和场景时段外的规则确认。",
             "- TCP 接收区间与编排时间通过进程启动时间对齐，存在少量启动偏差，不能据此宣称毫秒级端到端精度。",
             "- 原始证据在 collection/ 和 benchmark/；数据集、划分、参数与模型校验信息在 models/。", ""]
    (root/"真实实验结果.md").write_text("\n".join(text))
    record("结果汇总", f"已从原始日志汇总 {len(rows)} 轮闭环实验。",
           {"root": str(root), "json": str(root/"results.json"), "report": str(root/"真实实验结果.md")})
    print(f"已生成 {len(rows)} 轮结果：{root/'真实实验结果.md'}")
    return result


if __name__ == "__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",default="artifacts");p.add_argument("--model",default="models/random_forest.joblib")
    a=p.parse_args();generate(a.root,a.model)
