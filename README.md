# QoS UDP — Mininet + Ryu (SDN)

Run this stack on **Ubuntu** (VM or lab machine). Install steps: **[INSTALL.md](INSTALL.md)**.

## Topology and hosts

```
  h1  10.0.0.1   (voice client)
  h2  10.0.0.2   (video client)
  h3  10.0.0.3   (bulk client)
        |  |  |
        +--+--+- s1 (Open vSwitch, OpenFlow 1.3)
                 |
  hsrv  10.0.0.10  (UDP server — qos_udp server)
```

| Host | IP | Role |
|------|-----|------|
| `h1` | 10.0.0.1 | `qos_udp.py client` — voice |
| `h2` | 10.0.0.2 | `qos_udp.py client` — video |
| `h3` | 10.0.0.3 | `qos_udp.py client` — bulk |
| `hsrv` | 10.0.0.10 | `qos_udp.py server` (metrics log) |
| `s1` | — | Switch programmed by **Ryu** |

| Class | UDP dest port (use `--class-ports`) |
|-------|-------------------------------------|
| voice | 19001 |
| video | 19002 |
| bulk  | 19003 |

Client links to `s1`: **5 Mbps** each (congestion). **Ryu** REST: `http://127.0.0.1:8080` · OpenFlow: **6633**.

Set project path once (adjust if needed):

```bash
export PROJ=~/prj5
cd $PROJ
```

---

## 1. Start order (three terminals on Ubuntu)

**Terminal 1 — SDN controller (leave running)**

```bash
cd $PROJ
ryu-manager ryu_qos_controller.py
```

**Terminal 2 — Mininet (creates h1, h2, h3, hsrv, s1)**

```bash
cd $PROJ
sudo python3 mininet_qos.py
```

`mininet_qos.py` waits for Ryu, registers the switch port to `hsrv`, and **starts the UDP server on `hsrv`** in the background (`/tmp/qos_srv.log`).

**Terminal 3 — SDN policy (Ubuntu host, not inside Mininet CLI)**

Run while clients are sending traffic:

```bash
cd $PROJ
python3 qos_udp.py sdn-controller --weights voice=8,video=3,bulk=1
```

---

## 2. Using Mininet hosts: h1, h2, h3, hsrv

At the **`mininet>`** prompt you run commands **on a host** with:

```text
mininet> <host> <command>
```

### hsrv (server)

Started automatically by `mininet_qos.py`. You do **not** need to start the server again unless you stopped it.

**View metrics (throughput, latency, loss, fairness):**

```text
mininet> hsrv tail -f /tmp/qos_srv.log
```

**Check server is running:**

```text
mininet> hsrv pgrep -af qos_udp
mininet> hsrv ss -ulnp | grep -E '19001|19002|19003'
```

**Restart server manually (if needed):**

```text
mininet> hsrv pkill -f "qos_udp.py server" || true
mininet> hsrv python3 $PROJ/qos_udp.py server --host 0.0.0.0 --class-ports --mininet > /tmp/qos_srv.log 2>&1 &
```

Use the real path to `qos_udp.py` on the VM if `$PROJ` is not set inside Mininet hosts (often the same path as on the host, e.g. `/home/user/prj5/qos_udp.py`).

### h1, h2, h3 (clients)

**Option A — one line per host from `mininet>`** (background):

```text
mininet> h1 python3 /home/user/prj5/qos_udp.py client --host 10.0.0.10 --class-ports --class voice --rate 400 --duration 30 &
mininet> h2 python3 /home/user/prj5/qos_udp.py client --host 10.0.0.10 --class-ports --class video --rate 600 --duration 30 &
mininet> h3 python3 /home/user/prj5/qos_udp.py client --host 10.0.0.10 --class-ports --class bulk  --rate 800 --duration 30 &
```

Replace `/home/user/prj5` with your clone path.

**Option B — shell on a host (`xterm`)**

```text
mininet> xterm h1
mininet> xterm h2
mininet> xterm h3
```

In each xterm:

```bash
cd ~/prj5
python3 qos_udp.py client --host 10.0.0.10 --class-ports --class voice --rate 400 --duration 30
# h2: --class video   h3: --class bulk
```

**Connectivity check from a client host:**

```text
mininet> h1 ping -c 3 10.0.0.10
```

### Suggested manual workflow

1. Terminal 1: `ryu-manager …`
2. Terminal 2: `sudo python3 mininet_qos.py` → wait for `mininet>`
3. `mininet>`: start **h1, h2, h3** clients (above)
4. `mininet>`: `hsrv tail -f /tmp/qos_srv.log`
5. Terminal 3: `sdn-controller` mid-test to favor voice
6. `exit` at `mininet>` to tear down

---

## 3. Verify SDN and traffic

**On Ubuntu host (Terminal 3 or another shell):**

```bash
curl http://127.0.0.1:8080/status
python3 qos_udp.py sdn-controller --weights voice=1,video=1,bulk=1
python3 qos_udp.py sdn-controller --weights voice=8,video=3,bulk=1
```

**OpenFlow rules on `s1` (from `mininet>` or host with sudo):**

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

**Switch port counters:**

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-ports s1
```

---

## 4. Mininet-related files

| File | Purpose |
|------|---------|
| `mininet_qos.py` | Topology, link limits, start server on `hsrv`, Mininet CLI |
| `ryu_qos_controller.py` | Ryu SDN app (flow priorities + REST `/policy`, `/topology`) |
| `qos_udp.py` | `client` on **h1–h3**, `server` on **hsrv**, `sdn-controller` on Ubuntu host |
| `requirements-sdn.txt` | `pip install ryu` |
| `INSTALL.md` | apt: Mininet, OVS |

---

## 5. Report checklist

1. Screenshot: `dump-flows s1` before and after `sdn-controller`.
2. Log excerpt: `hsrv tail -40 /tmp/qos_srv.log` (per-class throughput, latency, loss, Jain fairness).
3. Note policy change time vs change in voice vs bulk rows in the log.

More background: **qos_udp_guide.txt**.
