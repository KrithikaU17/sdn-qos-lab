# Installation — QoS UDP + Mininet + Ryu

Run **Mininet** and **Ryu** on **Ubuntu Linux** (22.04 or 24.04). On Windows, use an **Ubuntu VM** (VirtualBox, VMware, or Hyper-V) or **WSL2** if your course allows it.

Edit the project on Windows; copy or clone the repo into the VM for experiments.

---

## 1. Ubuntu VM on Windows (recommended)

1. Install [VirtualBox](https://www.virtualbox.org/) or VMware Player.
2. Create a VM: **Ubuntu 22.04 LTS**, **4 GB RAM** (8 GB host RAM ideal), **30 GB** disk, **2 CPUs**.
3. Install Ubuntu; enable guest additions for shared folders (optional).
4. Copy this project into the VM, e.g. `~/prj5` (Git clone, zip, or shared folder).

---

## 2. Packages inside Ubuntu

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip git curl
sudo pip3 install -r requirements-sdn.txt
```

Verify:

```bash
sudo mn --test pingall
ryu-manager --version
python3 qos_udp.py -h
```

If `mn --test` fails, try:

```bash
sudo mn -c
sudo service openvswitch-switch start
```

---

## 3. Optional: WSL2 (Ubuntu)

```bash
# Inside WSL Ubuntu — same apt/pip steps as above
sudo apt install -y mininet openvswitch-switch python3-pip
sudo pip3 install -r requirements-sdn.txt
```

Mininet on WSL can be finicky; prefer a full VM for the lab.

---

## 4. Environment variables

| Variable       | Default                  | Purpose              |
|----------------|--------------------------|----------------------|
| `QOS_RYU_URL`  | `http://127.0.0.1:8080`  | Ryu REST base URL    |

---

## 5. Troubleshooting

| Problem | What to try |
|---------|-------------|
| `Address already in use` | `sudo mn -c`; kill old `ryu-manager` |
| Ryu not reachable from Mininet | Start `ryu-manager ryu_qos_controller.py` **before** `sudo python3 mininet_qos.py` |
| No flows on switch | `curl http://127.0.0.1:8080/status`; re-run Mininet to POST `/topology` |
| Permission denied on Mininet | Use `sudo` for `mininet_qos.py` only, not for Ryu |

---

See **README.md** for the step-by-step experiment.
