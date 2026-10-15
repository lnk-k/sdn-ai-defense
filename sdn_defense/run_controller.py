"""OS-Ken 4.x 移除了旧 osken-manager 命令，使用正式 AppManager API 启动。"""
import argparse
import logging
import os


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--method", choices=["off", "threshold", "rf"], default="off")
    p.add_argument("--model", default="models/random_forest.joblib")
    p.add_argument("--output", default="runtime/live")
    p.add_argument("--port", type=int, default=6653)
    args = p.parse_args()
    os.environ.update(SDN_METHOD=args.method, SDN_MODEL=args.model, SDN_RUN_DIR=args.output)
    from os_ken import cfg
    from os_ken.base import app_manager  # 此导入会按依赖顺序注册 OpenFlow 配置。
    cfg.CONF(args=[])
    cfg.CONF.set_override("ofp_listen_host", "127.0.0.1")
    cfg.CONF.set_override("ofp_tcp_listen_port", args.port)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app_manager.AppManager.run_apps(["sdn_defense.controller"])


if __name__ == "__main__":
    main()
