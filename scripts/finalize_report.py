"""将汇总数据与解释写入课设报告第五章，可在重现实验后再次运行。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = json.loads((ROOT / "artifacts/results.json").read_text())
    model = result["classifier"]
    raw = (ROOT / "artifacts/真实实验结果.md").read_text()
    tables = raw[raw.index("## 检测效果"):raw.index("## 指标口径")].replace("## ", "### ")
    def mean(scenario, method):
        return next(g for g in result["groups"] if g["scenario"]==scenario and g["method"]==method)["during_attack_mbps"]["mean"]
    rf_runs = [r for r in result["runs"] if r["method"]=="rf"]
    rf_attacks = [r for r in rf_runs if r["scenario"]!="normal"]
    rf_normal = [r for r in rf_runs if r["scenario"]=="normal"]
    counts=model["sample_counts"]
    matrix=model["rf"]["confusion_matrix"]
    confirmed=sum(r["drop_confirmed"] for r in rf_attacks)
    false=sum(r["false_blocks"] for r in rf_runs)
    normal_false=sum(r["false_blocks"] for r in rf_normal)
    rf_wrong=sum(r['wrong_target_blocks'] for r in rf_runs)
    rf_outside=sum(r['out_of_window_blocks'] for r in rf_runs)
    text=f'''## 5. 实验结果

实验日期为 2026 年 9 月 22 日。18 轮采集产生 {sum(counts.values())} 个有效窗口，其中训练 {counts['train']}、验证 {counts['validation']}、测试 {counts['test']} 个；共有 {len(result['runs'])} 轮独立闭环对照实验。原始数据、逐轮结果和过程日志均随项目提供。

验证集选出的包速率阈值为 {model['threshold_pps']} 包/秒，随机森林概率阈值为 {model['probability_threshold']}。测试集包含 {sum(matrix[0])} 个正常窗口与 {sum(matrix[1])} 个异常窗口。模型与数据集在闭环对照前冻结，未根据闭环测试结果重新调参。

{tables}
### 5.3 结果解释

本次独立测试中随机森林 F1 为 {model['rf']['f1']:.3f}，阈值方法 F1 为 {model['threshold']['f1']:.3f}。这只代表三个保留测试轮次上的结果。训练和测试来自固定拓扑与已知生成器，正常 UDP 的载荷为 512/900/1200 字节，异常 UDP 为 128/192/256/384 字节，存在很明显的包长差异，因此分类任务相对容易。不能将本次成绩外推为真实网络或未知攻击的准确率。

UDP 场景中，无防御的正常 TCP 平均接收吞吐量为 {mean('udp','off'):.3f} Mbit/s，随机森林防御为 {mean('udp','rf'):.3f} Mbit/s。该指标在场景仍持续期间统计，说明收益并非仅来自异常流量自然停止。每组只有两轮，表中同时保留波动范围，不做统计显著性宣称。

正常背景场景中，无防御和随机森林的正常 TCP 吞吐量分别为 {mean('normal','off'):.3f} 和 {mean('normal','rf'):.3f} Mbit/s。合法 UDP 也会竞争瓶颈带宽，因此吞吐量降低本身不是攻击的证明；阈值封禁合法流量后即使 TCP 吞吐量升高，也不能视为正确防御。

随机森林在 {len(rf_attacks)} 轮异常场景中，有 {confirmed} 轮确认真实丢弃；{len(rf_normal)} 轮纯正常场景中记录到 {normal_false} 次封禁。按“非目标源、错误协议或场景时段外确认规则均计入”的严格口径，随机森林全部轮次合计 {false} 次误封/场景外封禁。逐轮记录见 `artifacts/results.csv`，应将场景结束后的延迟动作与直接误封正常客户端区分分析。离线分类成绩不能替代控制时序的评估。

进一步核对后，随机森林的非目标源/错误协议封禁为 {rf_wrong} 次，目标正确但场景时段外的封禁为 {rf_outside} 次。这些窗口统计存在采样延迟，场景刚结束时仍可能依据之前的异常窗口下发规则；本次报告保留这一时间边界问题，没有通过更改统计窗口去消除它。

![三种方法的业务接收吞吐量比较](figures/throughput-comparison.png)

图 1：场景持续期正常 TCP 接收吞吐量，柱为两轮均值，黑点为每轮实际测量；样本标准差保留在上表。

![独立测试混淆矩阵](figures/confusion-matrices.png)

图 2：行是真实标签，列是预测标签；正类为异常。样本单位是一秒左右的统计窗口。

![固定第 1 轮 UDP 对照时间曲线](figures/udp-timeline.png)

图 3：固定采用 seed=900 的三种方法，阴影表示场景流量持续，虚线表示规则确认；没有挑选最优轮次作图。

### 5.4 证据与复现

- 原始日志：`artifacts/collection/` 与 `artifacts/benchmark/`。
- 统计结果：`artifacts/results.json`、`artifacts/results.csv`。
- 数据集与划分：`models/dataset.csv`、`models/random_forest.json`。
- 环境版本、依赖清单、代码/模型校验值及验收：`docs/verification/`。
- 开发和实验过程：[开发与实验日志](开发与实验日志.md)。

模型推理时间、从场景开始到请求封禁的检测时延、规则确认耗时，以及首次观测丢弃的时刻使用不同口径。检测失败的轮次没有零时延成绩，而是保留缺失值并展示未确认丢弃。CPU 共享、虚拟机时间同步与进程启动偏差限制了时间测量精度，不能用本系统宣称毫秒级端到端响应。

'''
    report = ROOT / "docs/课程设计报告.md"
    original = report.read_text()
    original = original[:original.index("## 5. 实验结果")] + text + original[original.index("## 6. 讨论与局限"):]
    original = original.replace("实验日期：以原始实验日志为准", "实验日期：2026 年 9 月 22 日")
    original = original.replace("主要软件包括 Mininet、Open vSwitch、OS-Ken", "主要软件包括 Mininet 2.3.0、Open vSwitch 3.3.9、Python 3.12.3、iperf3 3.16、OS-Ken")
    report.write_text(original)
    print(report)


if __name__ == "__main__":
    main()
