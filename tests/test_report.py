import json
from sdn_defense.report import summarize_run


def test_only_matching_attack_time_and_protocol_count_as_defense(tmp_path):
    meta = dict(id='fixture',status='completed',scenario='udp',method='rf',seed=1,
                started=100,scenario_started=107,scenario_ended=121,duration=26)
    (tmp_path/'metadata.json').write_text(json.dumps(meta))
    events = [dict(time=108,kind='rule_ack',src='10.0.0.3',protocol=1),
              dict(time=109,kind='block_requested',src='10.0.0.3',protocol=17),
              dict(time=109.01,kind='rule_ack',src='10.0.0.3',protocol=17),
              dict(time=110,kind='drop_observed',src='10.0.0.3',protocol=17),
              dict(time=123,kind='rule_ack',src='10.0.0.3',protocol=17)]
    (tmp_path/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
    row=summarize_run(tmp_path)
    assert row['false_blocks']==2 and row['drop_confirmed']
    assert row['detection_latency_s']==2
    assert row['drop_observed_latency_s']==3
    assert row['during_attack_mbps'] is None


def test_missed_attack_has_no_fabricated_zero_latency(tmp_path):
    meta=dict(id='fixture',status='completed',scenario='icmp',method='threshold',seed=1,
              started=100,scenario_started=107,scenario_ended=121,duration=26)
    (tmp_path/'metadata.json').write_text(json.dumps(meta))
    row=summarize_run(tmp_path)
    assert row['detection_latency_s'] is None
    assert row['drop_observed_latency_s'] is None
    assert row['drop_confirmed'] is False
