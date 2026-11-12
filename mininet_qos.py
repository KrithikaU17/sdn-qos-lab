#!/usr/bin/env python3
"""
Mininet topology for QoS UDP + Ryu SDN.

  h1 (voice)  --+
  h2 (video)  --+-- s1 -- hsrv (UDP server 10.0.0.10)
  h3 (bulk)   --+

Prerequisites:
  Terminal 1:  ryu-manager ryu_qos_controller.py
  Terminal 2:  sudo python3 mininet_qos.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.topo import Topo

# Ryu REST base URL (override with QOS_RYU_URL if Ryu is not on localhost).
RYU_REST = os.environ.get("QOS_RYU_URL", "http://127.0.0.1:8080")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
QOS_SCRIPT = os.path.join(PROJECT_DIR, "qos_udp.py")


class QoSTopo(Topo):
    """One switch, three client hosts, and a server on a slower bottleneck link."""

    def build(self):
        """Create s1, h1–h3 (50 Mbps), and hsrv (5 Mbps) so the server link congests."""
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        hsrv = self.addHost("hsrv", ip="10.0.0.10/24", mac="00:00:00:00:00:10")
        clients = (
            ("h1", "10.0.0.1/24", "00:00:00:00:00:01"),
            ("h2", "10.0.0.2/24", "00:00:00:00:00:02"),
            ("h3", "10.0.0.3/24", "00:00:00:00:00:03"),
        )
        for name, ip, mac in clients:
            host = self.addHost(name, ip=ip, mac=mac)
            self.addLink(
                host,
                s1,
                cls=TCLink,
                bw=50,
                delay="5ms",
                max_queue_size=200,
            )

        self.addLink(
            hsrv,
            s1,
            cls=TCLink,
            bw=5,
            delay="1ms",
        )


def switch_ofport_to_host(net, switch_name, host_name):
    """Return the number of the switch port that connects to this host."""
    switch = net[switch_name]
    host = net[host_name]
    pairs = host.connectionsTo(switch)
    if not pairs:
        raise RuntimeError(f"No link between {host_name} and {switch_name}")
    switch_intf = pairs[0][1]
    return int(switch.ports[switch_intf])


def http_post(path, payload):
    """POST JSON to the Ryu REST API (for example /topology or /policy)."""
    url = f"{RYU_REST.rstrip('/')}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()


def wait_for_ryu():
    """Poll GET /status until Ryu is up, or give up after about 20 seconds."""
    status_url = f"{RYU_REST.rstrip('/')}/status"
    for _ in range(40):
        try:
            urllib.request.urlopen(status_url, timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def run():
    """Start Mininet, tell Ryu the server port, launch the UDP server, then CLI."""
    setLogLevel("info")
    if not os.path.isfile(QOS_SCRIPT):
        info(f"*** Missing {QOS_SCRIPT}\n")
        sys.exit(1)

    net = Mininet(
        topo=QoSTopo(),
        controller=RemoteController("c0", ip="127.0.0.1", port=6633),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        cleanup=True,
    )

    net.start()
    info("*** Waiting for Ryu REST at %s ...\n" % RYU_REST)
    if not wait_for_ryu():
        info("*** Start Ryu first: ryu-manager ryu_qos_controller.py\n")
        net.stop()
        sys.exit(1)

    ofport = switch_ofport_to_host(net, "s1", "hsrv")
    info(f"*** hsrv connected to s1 OpenFlow port {ofport}\n")
    http_post("/topology", {"server_ofport": ofport})
    http_post("/policy", {"weights": {"voice": 1, "video": 1, "bulk": 1}})

    py = sys.executable
    srv_cmd = (
        f"{py} {QOS_SCRIPT} server --host 0.0.0.0 --class-ports --mininet "
        f"> /tmp/qos_srv.log 2>&1 &"
    )
    info(f"*** Starting server on hsrv\n")
    net["hsrv"].cmd(srv_cmd)
    time.sleep(1)

    info(
        "\n*** Manual clients (Mininet CLI):\n"
        f"  h1 {py} {QOS_SCRIPT} client --host 10.0.0.10 --class-ports "
        "--class voice --rate 400 --duration 20 &\n"
        f"  h2 {py} {QOS_SCRIPT} client --host 10.0.0.10 --class-ports "
        "--class video --rate 600 --duration 20 &\n"
        f"  h3 {py} {QOS_SCRIPT} client --host 10.0.0.10 --class-ports "
        "--class bulk --rate 800 --duration 20 &\n"
        f"  # On Ubuntu host: {py} {QOS_SCRIPT} sdn-controller "
        "--weights voice=8,video=3,bulk=1\n"
        "  hsrv tail -f /tmp/qos_srv.log\n"
        "  sh ovs-ofctl -O OpenFlow13 dump-flows s1\n\n"
    )

    CLI(net)
    net.stop()


if __name__ == "__main__":
    run()
