"""Open vSwitch HTB QoS queue setup for class-based UDP traffic (Mininet lab)."""

import logging
import subprocess
from typing import Dict, Optional

LOG = logging.getLogger(__name__)

CLASS_NAMES = ("voice", "video", "bulk")
# OpenFlow set_queue IDs must match creation order on the QoS record (0, 1, 2).
CLASS_QUEUE_ID = {"voice": 0, "video": 1, "bulk": 2}

DEFAULT_SWITCH = "s1"
# Egress capacity toward hsrv (bits per second) for HTB root.
DEFAULT_PORT_MAX_BPS = 10_000_000


def _run(args, check=True):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        LOG.warning(
            "ovs-vsctl failed (%s): %s",
            " ".join(args),
            (result.stderr or result.stdout).strip(),
        )
        return False
    if result.stdout:
        LOG.info("ovs-vsctl: %s", result.stdout.strip())
    return result.returncode == 0


def port_name_for_ofport(ofport: int, switch: str = DEFAULT_SWITCH) -> Optional[str]:
    """Resolve Mininet/OVS interface name (e.g. s1-eth4) from OpenFlow port number."""
    proc = subprocess.run(
        [
            "ovs-vsctl",
            "--bare",
            "--columns=name",
            "find",
            "interface",
            f"ofport={ofport}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    names = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
    for name in names:
        if name.startswith(f"{switch}-"):
            return name
    return names[0] if names else None


def _weight_rates(weights: Dict[str, int], port_max_bps: int) -> Dict[str, int]:
    """Map policy weights to per-class max-rate (bps), leaving headroom for HTB."""
    sane = {name: max(0, int(weights.get(name, 0))) for name in CLASS_NAMES}
    total = sum(sane.values()) or len(CLASS_NAMES)
    if not sum(sane.values()):
        sane = {name: 1 for name in CLASS_NAMES}
        total = 3
    cap = int(port_max_bps * 0.95)
    rates = {}
    for name in CLASS_NAMES:
        rates[name] = max(100_000, int(cap * sane[name] / total))
    return rates


def clear_port_qos(port_name: str) -> None:
    _run(["ovs-vsctl", "--if-exists", "clear", "port", port_name, "qos"], check=False)


def apply_htb_qos(
    port_name: str,
    weights: Dict[str, int],
    port_max_bps: int = DEFAULT_PORT_MAX_BPS,
) -> bool:
    """
    Create linux-htb QoS with three queues on egress toward hsrv.
    Queue 0=voice, 1=video, 2=bulk; rates follow policy weights.
    """
    rates = _weight_rates(weights, port_max_bps)
    clear_port_qos(port_name)
    min_voice = min(rates["voice"] // 4, rates["voice"])
    min_video = min(rates["video"] // 4, rates["video"])
    min_bulk = min(rates["bulk"] // 4, rates["bulk"])

    cmd = [
        "ovs-vsctl",
        "set",
        "port",
        port_name,
        "qos=@qos",
        "--",
        "--id=@qos",
        "create",
        "qos",
        "type=linux-htb",
        f"other-config:max-rate={port_max_bps}",
        "--",
        "other-config:min-rate={}".format(min_voice),
        "other-config:max-rate={}".format(rates["voice"]),
        "--",
        "other-config:min-rate={}".format(min_video),
        "other-config:max-rate={}".format(rates["video"]),
        "--",
        "other-config:min-rate={}".format(min_bulk),
        "other-config:max-rate={}".format(rates["bulk"]),
    ]
    ok = _run(cmd, check=False)
    if ok:
        LOG.info(
            "HTB QoS on %s voice=%s video=%s bulk=%s bps (max)",
            port_name,
            rates["voice"],
            rates["video"],
            rates["bulk"],
        )
    return ok


def configure_switch_qos(
    switch: str,
    server_ofport: int,
    weights: Dict[str, int],
    port_max_bps: int = DEFAULT_PORT_MAX_BPS,
) -> Optional[str]:
    port = port_name_for_ofport(server_ofport, switch=switch)
    if not port:
        LOG.warning("Could not resolve OVS port name for ofport %s", server_ofport)
        return None
    apply_htb_qos(port, weights, port_max_bps=port_max_bps)
    return port
