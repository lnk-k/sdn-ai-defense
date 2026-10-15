"""OpenFlow 1.3 控制器：table 0 计数/防御，table 1 二层学习转发。"""
import os
import time

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ether_types
from os_ken.ofproto import ofproto_v1_3

from sdn_defense.core import Counter, Detector, Policy, Recorder, Sampler

MONITOR = 0xA1000000
DROP = 0xD1000000


class DefenseController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.method = os.getenv("SDN_METHOD", "off")
        self.detector = Detector(self.method, os.getenv("SDN_MODEL", "models/random_forest.joblib"))
        self.policy = Policy(consecutive=2, block_seconds=10)
        self.rec = Recorder(os.getenv("SDN_RUN_DIR", "runtime/live"))
        self.sampler = Sampler()
        self.datapaths, self.mac, self.rows = {}, {}, {}
        self.requests, self.parts, self.barriers, self.mods = {}, {}, {}, {}
        self.pending_keys, self.observed_drops = set(), set()
        self.recent = []
        self.started = time.time()
        self.monitor = hub.spawn(self.poll)

    def event(self, kind, **kwargs):
        item = {"time": time.time(), "kind": kind, **kwargs}
        self.recent = (self.recent + [item])[-50:]
        self.rec.append("events", item)
        self.logger.info("%s %s", kind, kwargs)

    def snapshot(self):
        self.rec.snapshot({"source": "real-mininet", "method": self.method,
                           "time": time.time(), "started": self.started,
                           "switches": sorted(self.datapaths),
                           "flows": list(self.rows.values()), "events": self.recent})

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change(self, ev):
        dp = ev.datapath
        if dp.id is None:  # 启动端口探测尚未进行 OpenFlow 握手，不是交换机断线。
            return
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.event("switch_connected", dpid=dp.id)
        else:
            self.datapaths.pop(dp.id, None)
            self.sampler.forget_switch(dp.id)
            self.mac.pop(dp.id, None)
            self.event("switch_disconnected", dpid=dp.id)
        self.snapshot()

    def flow(self, dp, table, priority, match, instructions, **kwargs):
        msg = dp.ofproto_parser.OFPFlowMod(datapath=dp, table_id=table,
                    priority=priority, match=match, instructions=instructions, **kwargs)
        dp.set_xid(msg)
        dp.send_msg(msg)
        return msg

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath
        p, ofp = dp.ofproto_parser, dp.ofproto
        # 仅用于本项目新建的独立 Mininet 交换机，清除该实例残留流表。
        dp.send_msg(p.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                    table_id=ofp.OFPTT_ALL, out_port=ofp.OFPP_ANY,
                    out_group=ofp.OFPG_ANY, match=p.OFPMatch()))
        self.sampler.forget_switch(dp.id)
        self.flow(dp, 0, 0, p.OFPMatch(), [p.OFPInstructionGotoTable(1)])
        self.flow(dp, 1, 0, p.OFPMatch(), [p.OFPInstructionActions(
            ofp.OFPIT_APPLY_ACTIONS, [p.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])])
        if dp.id == 1:
            for host in range(1, 4):
                for proto in (1, 6, 17):
                    self.flow(dp, 0, 100,
                        p.OFPMatch(in_port=host, eth_type=0x0800, ipv4_src=f"10.0.0.{host}", ip_proto=proto),
                        [p.OFPInstructionGotoTable(1)], cookie=MONITOR + host * 256 + proto)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp, p, ofp = msg.datapath, msg.datapath.ofproto_parser, msg.datapath.ofproto
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        port = msg.match["in_port"]
        table = self.mac.setdefault(dp.id, {})
        table[eth.src] = port
        out = table.get(eth.dst, ofp.OFPP_FLOOD)
        if out == port:
            return
        actions = [p.OFPActionOutput(out)]
        if out != ofp.OFPP_FLOOD:
            self.flow(dp, 1, 10, p.OFPMatch(in_port=port, eth_dst=eth.dst),
                [p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)], idle_timeout=60)
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=port,
                    actions=actions, data=msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None))

    def poll(self):
        while True:
            hub.sleep(1)
            dp = self.datapaths.get(1)
            if dp is None:
                continue
            now = time.monotonic()
            if self.requests:
                if now - min(self.requests.values()) < 3:
                    continue
                self.event("stats_timeout")
                self.requests.clear()
                self.parts.clear()
            req = dp.ofproto_parser.OFPFlowStatsRequest(dp, table_id=0)
            dp.set_xid(req)
            self.requests[req.xid] = now
            dp.send_msg(req)

    def block(self, dp, key, score):
        if key in self.pending_keys:
            return
        _, host, proto = key
        p, ofp = dp.ofproto_parser, dp.ofproto
        self.pending_keys.add(key)
        self.event("block_requested", src=f"10.0.0.{host}", protocol=proto, score=score)
        mod = self.flow(dp, 0, 400,
            p.OFPMatch(in_port=host, eth_type=0x0800, ipv4_src=f"10.0.0.{host}", ip_proto=proto),
            [], cookie=DROP + host * 256 + proto, hard_timeout=self.policy.block_seconds,
            flags=ofp.OFPFF_SEND_FLOW_REM)
        self.mods[mod.xid] = {"key": key, "failed": False}
        barrier = p.OFPBarrierRequest(dp)
        dp.set_xid(barrier)
        self.barriers[barrier.xid] = mod.xid
        dp.send_msg(barrier)

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier(self, ev):
        xid = self.barriers.pop(ev.msg.xid, None)
        context = self.mods.pop(xid, None)
        if context is None:
            return
        key = context["key"]
        self.pending_keys.discard(key)
        if not context["failed"]:
            self.policy.mark_blocked(key, time.monotonic())
            self.observed_drops.discard(key)
            self.event("rule_ack", src=f"10.0.0.{key[1]}", protocol=key[2],
                       seconds=self.policy.block_seconds)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error(self, ev):
        if ev.msg.xid in self.mods:
            self.mods[ev.msg.xid]["failed"] = True
        self.event("openflow_error", error_type=ev.msg.type, code=ev.msg.code, xid=ev.msg.xid)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def removed(self, ev):
        msg = ev.msg
        if msg.cookie & 0xFF000000 != DROP:
            return
        key = (msg.datapath.id, (msg.cookie & 0xFFFF) // 256, msg.cookie & 0xFF)
        self.policy.release(key)
        self.event("rule_expired", src=f"10.0.0.{key[1]}", protocol=key[2],
                   dropped_packets=msg.packet_count)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def stats(self, ev):
        msg = ev.msg
        if msg.xid not in self.requests:
            return
        stats = self.parts.setdefault(msg.xid, [])
        stats.extend(msg.body)
        if msg.flags & msg.datapath.ofproto.OFPMPF_REPLY_MORE:
            return
        self.parts.pop(msg.xid)
        self.requests.pop(msg.xid)
        mono, wall = time.monotonic(), time.time()
        for entry in stats:
            prefix = entry.cookie & 0xFF000000
            if prefix not in (MONITOR, DROP):
                continue
            host, proto = (entry.cookie & 0xFFFF) // 256, entry.cookie & 0xFF
            key = (msg.datapath.id, host, proto)
            if prefix == DROP:
                if entry.packet_count > 0 and key not in self.observed_drops:
                    self.observed_drops.add(key)
                    self.event("drop_observed", src=f"10.0.0.{host}", protocol=proto,
                               dropped_packets=entry.packet_count)
                continue
            sample = self.sampler.update(key, Counter(entry.packet_count, entry.byte_count,
                        entry.duration_sec + entry.duration_nsec / 1e9, mono, wall), proto)
            if sample is None:
                continue
            blocked = self.policy.is_blocked(key, mono) or key in self.pending_keys
            attack, score, inference_ms = self.detector.predict(sample)
            row = {**sample, "src": f"10.0.0.{host}", "protocol": proto,
                   "dpid": msg.datapath.id, "blocked": blocked,
                   "prediction": int(attack), "score": score, "inference_ms": inference_ms,
                   "source": "real-mininet", "method": self.method}
            self.rec.append("samples", row)
            self.rows[str(key)] = row
            if not blocked and self.policy.observe(key, attack, mono):
                self.block(msg.datapath, key, score)
        self.snapshot()
