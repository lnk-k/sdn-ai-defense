"""平台无关的统计、检测和防御决策；真实控制器与离线演示共用。"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from pathlib import Path
import json

FEATURES = ["packet_rate", "byte_rate", "mean_packet_bytes", "is_icmp", "is_tcp", "is_udp"]
SCHEMA = 1


@dataclass(frozen=True)
class Counter:
    packets: int
    bytes: int
    duration: float
    monotonic: float
    wall: float


class Sampler:
    def __init__(self):
        self.previous: dict[tuple, Counter] = {}

    def forget_switch(self, dpid):
        self.previous = {k: v for k, v in self.previous.items() if k[0] != dpid}

    def update(self, key, counter: Counter, protocol: int):
        before = self.previous.get(key)
        self.previous[key] = counter
        if before is None:
            return None
        dt = counter.monotonic - before.monotonic
        if (dt <= 0 or counter.duration < before.duration
                or counter.packets < before.packets or counter.bytes < before.bytes):
            return None
        packets, size = counter.packets - before.packets, counter.bytes - before.bytes
        return dict(packet_rate=packets / dt, byte_rate=size / dt,
                    mean_packet_bytes=size / packets if packets else 0,
                    is_icmp=int(protocol == 1), is_tcp=int(protocol == 6), is_udp=int(protocol == 17),
                    packets=packets, bytes=size, window_seconds=dt,
                    window_start=before.wall, window_end=counter.wall)


def vector(row):
    values = [float(row[name]) for name in FEATURES]
    if not all(math.isfinite(v) and v >= 0 for v in values):
        raise ValueError("特征必须为有限非负数")
    return values


class Detector:
    def __init__(self, method="threshold", model=None, threshold_pps=1200.0):
        if method not in {"off", "threshold", "rf"}:
            raise ValueError("method 必须是 off、threshold 或 rf")
        self.method = method
        self.threshold_pps = threshold_pps
        if method == "threshold" and model and Path(model).with_suffix(".json").exists():
            self.threshold_pps = json.loads(Path(model).with_suffix(".json").read_text())["threshold_pps"]
        self.model = None
        self.probability_threshold = 0.8
        if method == "rf":
            import joblib
            artifact = joblib.load(model)  # 仅加载本项目生成的本地模型。
            if artifact["features"] != FEATURES or artifact["schema"] != SCHEMA:
                raise ValueError("模型特征版本不匹配，请重新训练")
            self.model = artifact["model"]
            self.probability_threshold = artifact["probability_threshold"]

    def predict(self, row):
        start = time.perf_counter_ns()
        x = vector(row)
        if row["packet_rate"] == 0:
            return False, 0.0, (time.perf_counter_ns() - start) / 1e6
        if self.method == "rf":
            index = list(self.model.classes_).index(1)
            score = float(self.model.predict_proba([x])[0, index])
            attack = score >= self.probability_threshold
        else:
            score = float(row["packet_rate"] >= self.threshold_pps)
            attack = self.method != "off" and bool(score)
        return bool(attack), score, (time.perf_counter_ns() - start) / 1e6


class Policy:
    """连续窗口告警；已封禁的零流量不构成“恢复正常”的证据。"""
    def __init__(self, consecutive=2, block_seconds=10):
        self.consecutive = consecutive
        self.block_seconds = block_seconds
        self.streak: dict[tuple, int] = {}
        self.blocked: dict[tuple, float] = {}

    def observe(self, key, attack, now):
        if key in self.blocked:
            if now < self.blocked[key]:
                return False
            del self.blocked[key]
            self.streak.pop(key, None)
        self.streak[key] = self.streak.get(key, 0) + 1 if attack else 0
        return self.streak[key] >= self.consecutive

    def mark_blocked(self, key, now):
        self.blocked[key] = now + self.block_seconds
        self.streak.pop(key, None)

    def release(self, key):
        self.blocked.pop(key, None)
        self.streak.pop(key, None)

    def is_blocked(self, key, now):
        return self.blocked.get(key, -1) > now


class Recorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def append(self, name, obj):
        with (self.directory / f"{name}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, allow_nan=False) + "\n")

    def snapshot(self, obj):
        temp = self.directory / "state.tmp"
        temp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temp.replace(self.directory / "state.json")
