# Suggested new / updated slides (paste into Presentation1.pptx)

## Slide: OVS HTB data-plane QoS (NEW)

**Title:** Switch QoS — OVS HTB queues

- Egress toward **hsrv** uses **linux-htb** with **3 queues**
- **Queue 0** = voice, **1** = video, **2** = bulk (OpenFlow `set_queue`)
- Policy weights **8 : 3 : 1** → proportional **max-rate** per queue
- Dynamic `/policy` **reconfigures HTB** and reinstalls flows
- Verify: `ovs-vsctl list queue`, `curl :8080/status`

## Slide: Policy → queue mapping (NEW)

| Class | UDP port | OpenFlow queue | Weight example |
|-------|----------|----------------|----------------|
| voice | 19001 | 0 | 8 |
| video | 19002 | 1 | 3 |
| bulk  | 19003 | 2 | 1 |

Control: **TCLink 5 Mbps** client links (congestion) + **HTB** on **s1 → hsrv**

## Slide: Results — baseline vs dynamic (UPDATE slide 12 area)

- **Baseline:** `voice=1,video=1,bulk=1` — table or CSV from `baseline.csv`
- **After policy:** `voice=8,video=3,bulk=1` — `voice_priority.csv`
- Plot: throughput (kbps) or loss % per class
- One sentence: voice share ↑, bulk ↓ under saturation

## Slide: Reproduction & deliverables (fill slides 16–18)

- GitHub repo, README, `mininet_qos.py`, `ryu_qos_controller.py` / `osken_qos_controller.py`
- `experiments/PERFORMANCE.md` + `parse_qos_log.py`
- Commands: Ryu → Mininet → h1–h3 clients → `sdn-controller`

## Slide: Limitations (honest)

- Classification: UDP **destination port** + application header (not DPI)
- QoS on **one switch egress** (lab topology)
- Host environment: Ubuntu VM / Docker 22.04 recommended
