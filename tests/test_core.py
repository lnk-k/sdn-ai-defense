import math
import pytest
from sdn_defense.core import Counter, Sampler, Policy, vector, Detector
from sdn_defense.report import mean_phase


def test_counter_delta_and_reset():
    s=Sampler();k=(1,1,17)
    assert s.update(k,Counter(10,1000,1,1,101),17) is None
    row=s.update(k,Counter(40,7000,3,3,103),17)
    assert row['packet_rate']==15 and row['byte_rate']==3000 and row['mean_packet_bytes']==200
    assert row['is_udp']==1 and row['window_start']==101
    assert s.update(k,Counter(2,120,0.5,4,104),17) is None
    assert s.update(k,Counter(4,240,1.5,5,105),17)['packet_rate']==2
    s.forget_switch(1)
    assert s.update(k,Counter(9,540,2,6,106),17) is None


def test_real_interval_and_zero_packets():
    s=Sampler();s.update((1,2,1),Counter(4,100,1,1,1),1)
    row=s.update((1,2,1),Counter(4,100,2.7,2.7,2.7),1)
    assert row['mean_packet_bytes']==0 and row['packet_rate']==0


def test_policy_requires_consecutive_and_expires():
    p=Policy(2,10);k=(1,3,17)
    assert not p.observe(k,True,0)
    assert not p.observe(k,False,1)
    assert not p.observe(k,True,2)
    assert p.observe(k,True,3)
    p.mark_blocked(k,3)
    assert not p.observe(k,False,4) and p.is_blocked(k,12)
    assert not p.observe(k,True,14)
    assert p.observe(k,True,15)


def test_features_reject_nan():
    row=dict(packet_rate=1,byte_rate=2,mean_packet_bytes=float('nan'),is_icmp=1,is_tcp=0,is_udp=0)
    with pytest.raises(ValueError):vector(row)


def test_off_never_blocks_and_threshold_boundary():
    row=dict(packet_rate=1200,byte_rate=120000,mean_packet_bytes=100,is_icmp=1,is_tcp=0,is_udp=0)
    assert not Detector('off').predict(row)[0]
    assert Detector('threshold').predict(row)[0]


def test_phase_is_time_weighted_and_missing_is_null():
    series=[dict(start=0,end=1,mbps=10),dict(start=1,end=3,mbps=4)]
    assert mean_phase(series,0,3)==6
    assert mean_phase(series,4,5) is None


def test_idle_flow_does_not_query_model():
    detector = Detector('off')
    detector.method = 'rf'
    row = dict(packet_rate=0, byte_rate=0, mean_packet_bytes=0,
               is_icmp=0, is_tcp=0, is_udp=1)
    assert detector.predict(row)[:2] == (False, 0.0)
