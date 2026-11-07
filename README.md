# QoS UDP — Mininet + Ryu / OS-Ken (SDN)

Run on **Ubuntu** (22.04 recommended) or in a **privileged** `ubuntu:22.04` Docker container. Install: **[INSTALL.md](INSTALL.md)**. Experiments: **[experiments/PERFORMANCE.md](experiments/PERFORMANCE.md)**.

## What this stack does

| Layer | Mechanism |
|-------|-----------|
| **Sockets** | `qos_udp.py` — UDP clients on **h1–h3**, server on **hsrv** |
| **Congestion** | Mininet **TCLink** 5 Mbps on client links |
| **SDN control** | Ryu or **OS-Ken** — OpenFlow 1.3, REST `/policy` |
| **Data-plane QoS** | **OVS linux-htb** queues 0/1/2 + `set_queue` per class (`ovs_qos.py`) |
| **Metrics** | Server log: throughput, latency, loss, Jain fairness |

## Topology

```
  h1  10.0.0.1   (voice)  ──┐
  h2  10.0.0.2   (video)  ──┼── s1 (OVS) ──► hsrv 10.0.0.10
  h3  10.0.0.3   (bulk)   ──┘      ▲
                                     │ HTB queues + OpenFlow
                               Ryu / OS-Ken :6633 / REST :8080
```

| Class | UDP port (`--class-ports`) | OVS queue |
|-------|----------------------------|-----------|
| voice | 19001 | 0 |
| video | 19002 | 1 |
| bulk  | 19003 | 2 |

---

## 1. Start order

**Terminal 1 — SDN controller** (venv on 22.04; OS-Ken on 24.04+ — see INSTALL)

```bash
cd "$PROJ"
# Ryu:
ryu-manager ryu_qos_controller.py
# OS-Ken:
# ryu-manager osken_qos_controller.py
```

**Terminal 2 — Mininet**

```bash
sudo python3 mininet_qos.py
```

Registers `server_ofport`, applies initial HTB QoS, starts server on **hsrv** (`/tmp/qos_srv.log`).

**Terminal 3 — policy** (while traffic runs)

```bash
python3 qos_udp.py sdn-controller --weights voice=8,video=3,bulk=1
```

Each policy change **reprograms HTB rates** and OpenFlow rules (queue + priority).

---

## 2. Mininet CLI — clients and logs

```text
mininet> h1 python3 /app/qos_udp.py client --host 10.0.0.10 --class-ports --class voice --rate 400 --duration 60 &
mininet> h2 python3 /app/qos_udp.py client --host 10.0.0.10 --class-ports --class video --rate 600 --duration 60 &
mininet> h3 python3 /app/qos_udp.py client --host 10.0.0.10 --class-ports --class bulk  --rate 800 --duration 60 &
mininet> hsrv tail -f /tmp/qos_srv.log
```

Use your real path instead of `/app` if needed.

---

## 3. Verify QoS and SDN

```bash
curl -s http://127.0.0.1:8080/status | python3 -m json.tool
```

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
mininet> sh ovs-vsctl list queue
```

`status` should include `ovs_port`, `queue_map`, and current `weights`.

---

## 4. Performance comparison (report / PPT)

Follow **[experiments/PERFORMANCE.md](experiments/PERFORMANCE.md)**:

1. Baseline weights `1,1,1` → save log → `parse_qos_log.py` → CSV  
2. Dynamic `8,3,1` → save log → compare voice vs bulk  
3. Optional slide text: **[PPT_additions.md](PPT_additions.md)**

---

## 5. Project files

| File | Role |
|------|------|
| `qos_udp.py` | UDP app: client, server, `sdn-controller` |
| `mininet_qos.py` | Topology, TCLink, register topology with controller |
| `ryu_qos_controller.py` | Ryu: HTB + OpenFlow |
| `osken_qos_controller.py` | OS-Ken: same logic |
| `ovs_qos.py` | `ovs-vsctl` HTB setup, queue ↔ class map |
| `experiments/parse_qos_log.py` | Log → CSV for graphs |
| `qos_udp_guide.txt` | Tutorial + rubric notes |

---

## 6. Report checklist

1. `dump-flows` + **`list queue`** before/after policy  
2. Server log + Jain fairness  
3. Baseline vs **8:3:1** table or graph (CSV)  
4. Architecture: sockets + **Mininet congestion** + **OVS queues** + dynamic policy
