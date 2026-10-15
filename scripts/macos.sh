#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
action="${1:-dashboard}"
guest() { limactl shell --workdir "$project_dir" sdn-course "$@"; }
case "$action" in
  start) limactl start --tty=false sdn-course ;;
  bootstrap) guest bash scripts/bootstrap_linux.sh ;;
  collect) guest sudo .venv-linux/bin/python -m sdn_defense.experiment collect ;;
  train) guest .venv-linux/bin/python -m sdn_defense.train ;;
  benchmark) guest sudo .venv-linux/bin/python -m sdn_defense.experiment benchmark --repeats "${2:-2}" ;;
  report) guest .venv-linux/bin/python -m sdn_defense.report ;;
  demo) guest sudo .venv-linux/bin/python -m sdn_defense.lab --scenario udp --method rf --output "artifacts/demo/udp-rf-$(date +%Y%m%d-%H%M%S)" ;;
  dashboard) exec .venv/bin/python -m sdn_defense.web ;;
  test) .venv/bin/python -m pytest -q ;;
  stop) limactl stop sdn-course ;;
  *) echo '用法：bash scripts/macos.sh start|bootstrap|collect|train|benchmark [轮数]|report|demo|dashboard|test|stop'; exit 2 ;;
esac
