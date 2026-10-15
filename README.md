# 基于软件定义网络的智能网络异常检测与动态防御系统

面向计算机网络课程设计的完整实验项目。使用 **Mininet + Open vSwitch + OS-Ken + 随机森林**，实现流量统计、异常检测、临时封禁和正常业务恢复验证。

**本机已完成实测**：18 轮采集、18 轮闭环对照；Mac 与 Linux 均通过 12 项测试。UDP 场景正常 TCP 平均接收吞吐量从无防御的 **0.969 Mbit/s** 提升到随机森林防御的 **8.360 Mbit/s**。模型、原始日志、结果图和报告均已包含在项目中。

## 先看什么

1. 第一次学习：阅读 [原理与答辩说明](docs/原理与答辩说明.md)。
2. 运行和演示：按本页的启动步骤操作。
3. 课程报告：[课程设计报告](docs/课程设计报告.md)。
4. 实测结果：[真实实验结果](artifacts/真实实验结果.md) 和 `artifacts/results.csv`。
5. 过程记录：[开发与实验日志](docs/开发与实验日志.md)，同时保留 `docs/logs/journal.jsonl` 供程序读取。

结果仅针对固定拓扑的受控 ICMP/UDP 场景。报告保留了阈值误封/漏检，以及随机森林 3 次场景结束后的延迟封禁，不把离线分类满分解释为通用检测能力。

## 实验结构

```text
                 OS-Ken 控制器 + 阈值 / RF 检测器
                     ↑ 统计       ↓ OpenFlow 规则
h1：正常 TCP ─┐
h2：正常 ping ┼─ s1 ═══ 10 Mbit/s ═══ s2 ─ server
h3：场景流量 ─┘   ↑                    
              入口计数与临时丢弃
```

- h1：10.0.0.1，持续访问服务端 iperf3，测量业务影响。
- h2：10.0.0.2，持续正常 ping。
- h3：10.0.0.3，产生正常 UDP、受控 UDP 洪泛或 ICMP 洪泛。
- server：10.0.0.10，TCP 测量端口 5201、UDP 接收端口 9999。
- 控制器在 Linux 内监听 `127.0.0.1:6653`，看板默认仅本机 `127.0.0.1:8808`。
- 拓扑不添加 NAT、外部网络接口或互联网出口。生成器目标固定为实验服务器，设定速率与时间上限。

## Mac 本机启动

本机项目目录：`/Users/kk/Documents/ChatGPT/课程设计/sdn-ai-defense`。

Mac 负责编辑源码、打开看板；专用 Lima 实例 `sdn-course` 内运行真实网络。虚拟机为 Ubuntu 24.04 ARM64，4 核、4 GB 内存、20 GB 稀疏磁盘，仅共享本项目目录。

```bash
cd /Users/kk/Documents/ChatGPT/课程设计/sdn-ai-defense
bash scripts/macos.sh start
bash scripts/macos.sh dashboard
```

然后打开 <http://127.0.0.1:8808>。选择实验记录，点击“回放”，观察流量曲线、规则确认和丢弃事件。

另开一个终端执行新的约半分钟演示：

```bash
bash scripts/macos.sh demo
```

演示期间在看板中刷新记录、选择最新的 `demo/udp-rf-...`。结束后日志会保留，可以反复回放。

关闭看板用 `Ctrl+C`；不做实验时可以关闭虚拟机：

```bash
bash scripts/macos.sh stop
```

## 从零重现实验

### Ubuntu 直接安装

在专用 Ubuntu 24.04 实验环境中进入项目目录：

```bash
bash scripts/bootstrap_linux.sh
```

脚本安装 Mininet、Open vSwitch、iperf3，创建 `.venv-linux` 并安装 Python 依赖。系统的 Mininet 通过 `--system-site-packages` 供虚拟环境使用。

脚本将 Ubuntu 官方源的 HTTP 地址改为 HTTPS，并保留 `.bak` 备份；下载时沿用现有代理环境变量，不改变宿主机代理设置。

### 新的 Mac 环境

本机已经配好环境。若将项目复制到另一台 Apple Silicon Mac，需要先安装 Homebrew、Lima 和 Python 3.12 或 3.13，并将 `infra/lima.yaml` 中的共享路径改为新项目的绝对路径：

```bash
brew install lima
limactl start --name sdn-course --tty=false infra/lima.yaml
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-report.txt
bash scripts/macos.sh bootstrap
```

Intel / AMD 主机优先使用 Ubuntu 原生或对应架构的 Linux 虚拟机，不能复用 ARM64 镜像。看板只用 Python 标准库，可以直接运行 `python3 -m sdn_defense.web`。

### 数据采集 → 训练 → 对照实验 → 报告

```bash
sudo .venv-linux/bin/python -m sdn_defense.experiment collect
.venv-linux/bin/python -m sdn_defense.train
sudo .venv-linux/bin/python -m sdn_defense.experiment benchmark --repeats 2
.venv-linux/bin/python -m sdn_defense.report
```

在已经配置好的 Mac 上，对应为：

```bash
bash scripts/macos.sh collect
bash scripts/macos.sh train
bash scripts/macos.sh benchmark 2
bash scripts/macos.sh report
```

采集包含 18 轮：3 种场景，各 6 轮，每轮 18 秒，另有启动清理时间。前 4 轮用于训练，第 5 轮验证，第 6 轮测试。对照实验默认 18 轮：3 种场景 × 3 种方法 × 2 次重复，每轮 26 秒。请预留约 15–25 分钟。

已完成且具有完整元数据的轮次会跳过。失败轮次保留证据，不自动覆盖；重新试验可使用新的 `--output` 目录，并让训练和报告指向对应目录。

不要同时启动两个实验：它们使用相同的 s1/s2 名称和控制器端口。异常中断后先确认没有其他 Mininet 实验，再在实验虚拟机中执行 `sudo mn -c` 清理残留。

### 单独运行一轮

```bash
sudo .venv-linux/bin/python -m sdn_defense.lab \
  --scenario udp --method rf --seed 901 \
  --output artifacts/demo/my-demo
```

`--scenario` 支持 `normal / icmp / udp`；`--method` 支持 `off / threshold / rf`。

## 每个目录放什么

| 目录 / 文件 | 用途 |
| --- | --- |
| `sdn_defense/core.py` | 累计计数差分、统一特征、检测器、防御策略 |
| `sdn_defense/controller.py` | OpenFlow 1.3 真实控制器 |
| `sdn_defense/run_controller.py` | OS-Ken 4.x 的程序化启动入口 |
| `sdn_defense/lab.py` | Mininet 拓扑、正常业务、场景流量与日志管理 |
| `sdn_defense/experiment.py` | 批量采集与重复对照实验 |
| `sdn_defense/train.py` | 按实验轮次划分数据、训练、验证和测试 |
| `sdn_defense/report.py` | 解析真实结果、输出 JSON / CSV / Markdown |
| `sdn_defense/web.py`、`web/` | 不依赖前端构建工具的中文看板 |
| `models/` | 模型、数据集、阈值、特征顺序、离线评估 |
| `artifacts/collection/` | 禁用防御的原始训练数据采集日志 |
| `artifacts/benchmark/` | 无防御、阈值、RF 的实测对照日志 |
| `tests/` | 计数器、判定、防御规则和统计口径测试 |

看板的“放行速率”指命中统计规则、进入二层转发表的数据，不包含高优先级规则直接丢弃的包；实际接收速率由服务端独立测量。

每轮实验保存 `metadata.json`、`samples.jsonl`、`events.jsonl`、`receiver.json`、`business.json`、`controller.log` 和流表快照。`receiver.json` 是服务端实际接收吞吐量的来源。

## 测试

```bash
.venv/bin/python -m pytest -q
# Linux 中使用 .venv-linux/bin/python
```

自动测试验证计数器重置、连续窗口、规则超时、OpenFlow 消息序列化、空 action 丢弃、Barrier 确认和错误处理。真正的交换机行为还需要实际 Mininet 实验验证，不能用单元测试替代。

生成报告插图（在安装了 `requirements-report.txt` 的环境执行）：

```bash
.venv/bin/python -m sdn_defense.figures
```

图片保存在 `docs/figures/`，包括对照吞吐量、独立测试混淆矩阵及固定第 1 轮 UDP 实验时间曲线。

更新报告第五章和核验原始证据：

```bash
.venv/bin/python scripts/finalize_report.py
.venv/bin/python scripts/verify_artifacts.py
```

验收脚本检查随项目交付的 18+18 轮数据。`passed` 表示证据完整且一致，性能局限另列于 `performance_findings`，不是“没有误报”的承诺。

## 日志记录

每轮新实验会自动记录初始化、正常业务、场景开始、场景结束、完成或失败；训练和结果汇总也会追加记录。过去已完成的轮次已明确标记为“历史实验补录”，记录写入时间与实际实验时间分开。

手动补充开发记录：

```bash
.venv/bin/python -m sdn_defense.journal --stage 开发 "这里写本次改动和验证结果"
```

看完整过程用 `docs/开发与实验日志.md`，程序读取使用 `docs/logs/journal.jsonl`。数据包统计与规则事件则保存在各轮实验目录，互不替代。

## 范围和限制

- 首版检测已知 ICMP/UDP 流量异常，不宣称实现所有类型入侵检测。
- TCP SYN 洪泛和端口扫描需要额外特征和实验设计，目前未实现。
- 入口聚合粒度为“主机接入端口 + 源 IPv4 + 协议”，不逐连接创建规则，避免大量短连接直接造成流表膨胀。
- 特征不包含主机 IP；IP 仅用于日志定位和执行封禁。固定端口/IP 对应属于本实验拓扑假设，不覆盖源地址伪造和主机迁移。
- 流量统计采样周期为 1 秒，连续 2 个异常窗口才封禁，端到端响应通常是秒级。
- 只加载本项目自行训练的 `joblib` 模型；跨环境使用建议重新训练并保存实际依赖版本。
- 本次任务不向博客自动发布源码或报告；课设文件都保存在本地项目目录。

## 官方资料

- [Mininet 官方入门](https://mininet.org/walkthrough/)
- [OS-Ken 应用 API](https://docs.openstack.org/os-ken/latest/os_ken_app_api.html)
- [Open vSwitch 文档](https://docs.openvswitch.org/en/latest/)
- [scikit-learn 随机森林](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html)
- [Lima 安装与运行](https://lima-vm.io/docs/installation/)
