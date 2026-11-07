# Performance experiments (baseline vs dynamic QoS)

Run on the **same machine** as Mininet + Ryu/OS-Ken (controller needs `ovs-vsctl`).

## Setup

1. `ryu-manager ryu_qos_controller.py` (or `ryu-manager osken_qos_controller.py` with OS-Ken venv)
2. `sudo python3 mininet_qos.py`
3. Start clients on `h1`, `h2`, `h3` (see README).

## Experiment A — equal weights (baseline)

```bash
python3 qos_udp.py sdn-controller --weights voice=1,video=1,bulk=1
```

Let traffic run **30 s**, then on Mininet CLI:

```text
mininet> hsrv cp /tmp/qos_srv.log /tmp/baseline.log
```

Capture:

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
mininet> sh ovs-vsctl list queue
```

## Experiment B — voice priority (dynamic policy)

Mid-test:

```bash
python3 qos_udp.py sdn-controller --weights voice=8,video=3,bulk=1
```

Run **30 s** more, then:

```text
mininet> hsrv cp /tmp/qos_srv.log /tmp/voice_priority.log
```

Verify API shows queue mapping:

```bash
curl -s http://127.0.0.1:8080/status | python3 -m json.tool
```

## Parse logs to CSV (for graphs)

On the host (paths if copied from hsrv):

```bash
python3 experiments/parse_qos_log.py /tmp/baseline.log -o experiments/baseline.csv
python3 experiments/parse_qos_log.py /tmp/voice_priority.log -o experiments/voice_priority.csv
```

Plot throughput or loss per class in Excel, gnuplot, or Python.

## What to compare

| Metric | Source in log |
|--------|----------------|
| Throughput (kbps) | column 3 per class row |
| Latency (ms) | column 4 |
| Loss % | column 5 |
| Fairness | `Jain fairness index` lines |

**Expected:** After experiment B, **voice** throughput should improve relative to **bulk** under congestion; `list queue` shows HTB max-rates aligned with weights.
