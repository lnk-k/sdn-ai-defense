"""在独立 Linux 中运行受控 Mininet 实验，保存全部原始证据。"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import random
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
from sdn_defense.journal import record


def stop_process(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)


def run_round(output, scenario, method, seed, duration=26, attack_start=7, attack_end=21, model=None):
    if platform.system() != "Linux" or os.geteuid() != 0:
        raise RuntimeError("真实实验必须在 Linux 中以 sudo 运行；Mac 请进入课设 Lima 虚拟机。")
    from mininet.net import Mininet
    from mininet.node import RemoteController, OVSSwitch
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    setLogLevel("warning")
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"实验目录已存在，避免覆盖证据：{output}")
    output.mkdir(parents=True)
    rng = random.Random(seed)
    pps = rng.randint(3500, 7500) if scenario == "udp" else rng.randint(200, 1600)
    size = rng.choice([128, 192, 256, 384]) if scenario == "udp" else rng.choice([512, 900, 1200])
    ping_interval = rng.choice([0.0005, 0.001, 0.002])
    model = str(Path(model or ROOT / "models/random_forest.joblib").resolve())
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    handles, processes, net, controller = [], [], None, None
    metadata = {"id": output.name, "source": "real-mininet", "scenario": scenario,
                "method": method, "seed": seed, "duration": duration,
                "bottleneck_mbps": 10, "poll_seconds": 1, "status": "starting",
                "traffic": {"pps": pps, "payload_bytes": size, "ping_interval": ping_interval}}
    last_stage = None

    def save():
        nonlocal last_stage
        temp = output / "metadata.tmp"
        temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        temp.replace(output / "metadata.json")
        phase = (metadata["status"], "场景结束" if "scenario_ended" in metadata else "场景开始" if "scenario_started" in metadata else "初始化或基线")
        if phase != last_stage:
            record("网络实验", f"{output.name}：{phase[0]} / {phase[1]}",
                   {"scenario": scenario, "method": method, "seed": seed,
                    "directory": str(output), "error": metadata.get("error")},
                   f"run:{output}:{metadata['status']}" if metadata["status"] in {"completed", "failed"} else None)
            last_stage = phase

    def log(name):
        f = (output / name).open("w")
        handles.append(f)
        return f

    save()
    try:
        controller = subprocess.Popen([sys.executable, "-m", "sdn_defense.run_controller",
            "--method", method, "--model", model, "--output", str(output)],
            cwd=ROOT, env=env, stdout=log("controller.log"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while True:
            if controller.poll() is not None:
                raise RuntimeError("控制器启动失败，请查看 controller.log")
            try:
                with socket.create_connection(("127.0.0.1", 6653), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("控制器监听端口未就绪")
                time.sleep(0.2)
        net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=False)
        net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
        s1 = net.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13", failMode="secure")
        s2 = net.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13", failMode="secure")
        hosts = {}
        for n in range(1, 4):
            h = net.addHost(f"h{n}", ip=f"10.0.0.{n}/24", mac=f"02:00:00:00:00:{n:02x}")
            net.addLink(h, s1, port2=n)
            hosts[n] = h
        server = net.addHost("server", ip="10.0.0.10/24", mac="02:00:00:00:00:0a")
        net.addLink(s1, s2, port1=4, port2=1, bw=10, delay="2ms", max_queue_size=50, use_htb=True)
        net.addLink(s2, server, port1=2)
        net.start()
        deadline = time.monotonic() + 25
        while True:
            if controller.poll() is not None:
                raise RuntimeError("控制器提前退出，请查看 controller.log")
            state = output / "state.json"
            if state.exists() and len(json.loads(state.read_text())["switches"]) == 2:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("交换机未能连接控制器")
            time.sleep(0.2)
        if net.pingAll(timeout="2") != 0:
            raise RuntimeError("拓扑连通性检查未通过")
        business_server = server.popen(["iperf3", "-s", "-1", "-p", "5201", "-J"], stdout=log("receiver.json"), stderr=subprocess.STDOUT)
        processes.append(business_server)
        processes.append(server.popen([sys.executable, "-m", "sdn_defense.traffic", "receive",
                         "--seconds", str(min(120, duration+8))], cwd=str(ROOT), stdout=log("udp-sink.log"), stderr=subprocess.STDOUT))
        time.sleep(0.8)
        metadata.update(status="running", started=time.time())
        save()
        business = hosts[1].popen(["iperf3", "-c", "10.0.0.10", "-p", "5201", "-t", str(duration), "-i", "1", "-J"],
                                  stdout=log("business.json"), stderr=subprocess.STDOUT)
        processes.append(business)
        processes.append(hosts[2].popen(["ping", "-n", "-i", "0.2", "-w", str(duration), "10.0.0.10"],
                                      stdout=log("normal-ping.log"), stderr=subprocess.STDOUT))
        time.sleep(attack_start)
        metadata["scenario_started"] = time.time()
        seconds = attack_end - attack_start
        if scenario == "icmp":
            command = ["ping", "-n", "-q", "-i", str(ping_interval), "-s", "128", "-w", str(seconds), "10.0.0.10"]
        else:
            command = [sys.executable, "-m", "sdn_defense.traffic", "send", "--pps", str(pps),
                       "--size", str(size), "--seconds", str(seconds)]
        attack_process = hosts[3].popen(command, cwd=str(ROOT), stdout=log("scenario.log"), stderr=subprocess.STDOUT)
        processes.append(attack_process)
        save()
        time.sleep(seconds)
        stop_process(attack_process)
        metadata["scenario_ended"] = time.time()
        save()
        business.wait(timeout=duration-attack_end+12)
        business_server.wait(timeout=5)
        time.sleep(1)
        for h in handles:
            h.flush()
        business_data = json.loads((output / "business.json").read_text())
        if "error" in business_data or "end" not in business_data:
            raise RuntimeError(f"业务测量失败：{business_data.get('error')}")
        for switch in ("s1", "s2"):
            result = subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch], text=True, capture_output=True, check=True)
            (output / f"{switch}-flows.txt").write_text(result.stdout)
        metadata.update(status="completed", ended=time.time())
        save()
    except BaseException as exc:
        metadata.update(status="failed", error=str(exc), ended=time.time())
        save()
        raise
    finally:
        for p in reversed(processes):
            stop_process(p)
        if net is not None:
            net.stop()
        stop_process(controller)
        for f in handles:
            f.close()
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["normal", "udp", "icmp"], default="udp")
    parser.add_argument("--method", choices=["off", "threshold", "rf"], default="threshold")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model")
    args = parser.parse_args()
    run_round(args.output, args.scenario, args.method, args.seed, model=args.model)


if __name__ == "__main__":
    main()
