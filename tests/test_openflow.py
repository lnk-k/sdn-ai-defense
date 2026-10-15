from types import SimpleNamespace
from os_ken.ofproto import ofproto_v1_3 as ofp, ofproto_v1_3_parser as p
from sdn_defense.controller import DefenseController, MONITOR, DROP
from sdn_defense.core import Policy, Sampler


class Datapath:
    id=1
    ofproto=ofp
    ofproto_parser=p
    def __init__(self):self.sent=[];self.xid=10
    def set_xid(self,msg):self.xid+=1;msg.set_xid(self.xid)
    def send_msg(self,msg):
        if msg.xid is None:self.set_xid(msg)
        msg.serialize();self.sent.append(msg)


def app():
    a=DefenseController.__new__(DefenseController)
    a.pending_keys=set();a.mods={};a.barriers={};a.observed_drops=set()
    a.policy=Policy();a.sampler=Sampler();a.event=lambda *args,**kwargs:None
    return a


def test_multitable_and_ingress_accounting():
    a=app();dp=Datapath();a.features(SimpleNamespace(msg=SimpleNamespace(datapath=dp)))
    monitored=[m for m in dp.sent if isinstance(m,p.OFPFlowMod) and m.cookie & 0xff000000==MONITOR]
    assert len(monitored)==9
    assert all(m.table_id==0 and m.instructions[0].table_id==1 for m in monitored)
    assert {m.match['in_port'] for m in monitored}=={1,2,3}


def test_drop_needs_barrier_and_does_not_send_forward_action():
    a=app();dp=Datapath();key=(1,3,17);a.block(dp,key,0.99)
    mod,barrier=dp.sent
    assert mod.priority==400 and mod.table_id==0 and mod.instructions==[]
    assert mod.hard_timeout==10 and mod.match['in_port']==3 and mod.match['ipv4_src']=='10.0.0.3'
    assert mod.flags & ofp.OFPFF_SEND_FLOW_REM
    assert not a.policy.blocked
    a.barrier(SimpleNamespace(msg=SimpleNamespace(xid=barrier.xid)))
    assert key in a.policy.blocked and key not in a.pending_keys


def test_error_before_barrier_is_not_reported_as_installed():
    a=app();dp=Datapath();key=(1,3,1);a.block(dp,key,1)
    mod,barrier=dp.sent
    a.error(SimpleNamespace(msg=SimpleNamespace(xid=mod.xid,type=3,code=1)))
    a.barrier(SimpleNamespace(msg=SimpleNamespace(xid=barrier.xid)))
    assert key not in a.policy.blocked
