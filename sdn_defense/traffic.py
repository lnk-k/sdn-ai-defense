"""有时长和速率上限的实验 UDP 收发器；目标固定为隔离拓扑的 server。"""
import argparse
import socket
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["send", "receive"])
    parser.add_argument("--pps", type=int, default=500)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.pps <= 12000 or not 32 <= args.size <= 1400 or not 0 < args.seconds <= 120:
        parser.error("实验参数范围：1–12000 pps、32–1400 B、0–120 秒")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    end = time.monotonic() + args.seconds
    if args.mode == "receive":
        sock.bind(("10.0.0.10", 9999))
        sock.settimeout(0.5)
        while time.monotonic() < end:
            try:
                sock.recvfrom(65535)
            except socket.timeout:
                pass
    else:
        payload = b"s" * args.size
        start = time.monotonic()
        sent = 0
        # 小批次发送，按累计数量节流，避免无限制 busy loop。
        while time.monotonic() < end:
            target = start + sent / args.pps
            if target > time.monotonic():
                time.sleep(target - time.monotonic())
            for _ in range(min(20, max(1, args.pps // 100))):
                sock.sendto(payload, ("10.0.0.10", 9999))
                sent += 1
    sock.close()


if __name__ == "__main__":
    main()
