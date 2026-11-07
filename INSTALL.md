# Installation — QoS UDP + Mininet + SDN

**Ubuntu 22.04 LTS** is the recommended lab OS. **24.04 / 25.04 / 26.04:** use **OS-Ken** in a venv (see below) or a **Docker** `ubuntu:22.04` privileged container.

On Windows, use an Ubuntu VM or WSL2; copy the project to e.g. `~/prj5` or `/media/sf_prj5`.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip python3-venv git curl
sudo systemctl enable --now openvswitch-switch
```

Verify:

```bash
sudo mn -c
sudo mn --test pingall
python3 qos_udp.py -h
ovs-vsctl --version
```

---

## 2. SDN controller (venv recommended)

The controller runs **`ovs-vsctl`** to configure HTB queues — install on the **same host** as Mininet, not inside Mininet namespaces.

### Ubuntu 22.04 — Ryu

```bash
python3 -m venv ~/sdn-venv
source ~/sdn-venv/bin/activate
pip install 'pip<24' 'setuptools==57.5.0' wheel 'eventlet==0.30.2' 'ryu==4.34'
ryu-manager --version
```

Run:

```bash
source ~/sdn-venv/bin/activate
ryu-manager ryu_qos_controller.py
```

### Ubuntu 24.04+ — OS-Ken

```bash
python3 -m venv ~/sdn-venv
source ~/sdn-venv/bin/activate
pip install os-ken==4.2.2
ryu-manager --version
```

Run:

```bash
ryu-manager osken_qos_controller.py
```

(`ryu-manager` is provided by the OS-Ken package.)

---

## 3. Docker quick lab (no custom image)

```bash
docker run -it --rm --privileged -v "$(pwd):/app" -w /app ubuntu:22.04 bash
# inside container:
apt-get update && apt-get install -y mininet openvswitch-switch python3 python3-pip python3-venv curl sudo
service openvswitch-switch start
python3 -m venv /opt/venv && /opt/venv/bin/pip install os-ken==4.2.2
export PATH="/opt/venv/bin:$PATH"
```

Start **ryu-manager** then **sudo python3 mininet_qos.py** in the same privileged container.

---

## 4. Run order

1. Controller: `ryu-manager ryu_qos_controller.py` (or `osken_qos_controller.py`)
2. `sudo python3 mininet_qos.py`
3. Clients on h1–h3; `python3 qos_udp.py sdn-controller ...` on host

See **README.md** and **experiments/PERFORMANCE.md**.

---

## 5. Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QOS_RYU_URL` | `http://127.0.0.1:8080` | Controller REST base |

---

## 6. Troubleshooting

| Problem | What to try |
|---------|-------------|
| Ryu pip / `ALREADY_HANDLED` / `is_timeout` | 22.04 venv + setuptools/eventlet pins; or OS-Ken |
| `ovs-vsctl list queue` empty | Start controller **before** clients; apply `/policy`; check `curl :8080/status` → `ovs_port` |
| Ryu not reachable | Start controller before Mininet |
| 100% pingall in Docker | `docker run` must include **`--privileged`** |
| HTB errors on port | Run `sudo mn -c`; restart Mininet; ensure `s1` exists |
