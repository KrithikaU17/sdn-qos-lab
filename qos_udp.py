#!/usr/bin/env python3
"""UDP QoS traffic generator, congested receiver, and SDN-style controller."""

import argparse
import json
import queue
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

CLASSES = {"voice": 1, "video": 2, "bulk": 3}
NAMES = {value: key for key, value in CLASSES.items()}
# Per-class UDP ports for Mininet + OpenFlow matching (see ryu_qos_controller.py)
CLASS_PORTS = {"voice": 19001, "video": 19002, "bulk": 19003}
HEADER = struct.Struct("!4sBId")
MAGIC = b"QOS1"
DEFAULT_RYU_POLICY_URL = "http://127.0.0.1:8080/policy"
MININET_SERVER_CAPACITY = 100_000


class QoSServer:
    def __init__(self, host, port, control_port, capacity, queue_size, weights,
                 class_ports=False):
        self.host, self.port, self.control_port = host, port, control_port
        self.class_ports = class_ports
        self.capacity = capacity
        self.weights = dict(weights)
        self.queues = {
            name: queue.Queue(maxsize=queue_size) for name in CLASSES
        }
        self.stats = defaultdict(
            lambda: {
                "offered": 0, "processed": 0, "dropped": 0, "bytes": 0,
                "latency_sum": 0.0, "interval_processed": 0,
                "interval_dropped": 0, "interval_offered": 0,
                "interval_bytes": 0, "interval_latency": 0.0,
            }
        )
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.current = {name: 0 for name in CLASSES}

    def _enqueue_packet(self, data, name_hint=None):
        if len(data) < HEADER.size:
            return
        magic, class_id, seq, sent_at = HEADER.unpack_from(data)
        name = NAMES.get(class_id)
        if magic != MAGIC or not name:
            return
        if name_hint and name_hint != name:
            return
        with self.lock:
            stat = self.stats[name]
            stat["offered"] += 1
            stat["interval_offered"] += 1
        try:
            self.queues[name].put_nowait((seq, sent_at, len(data)))
        except queue.Full:
            with self.lock:
                stat = self.stats[name]
                stat["dropped"] += 1
                stat["interval_dropped"] += 1

    def receive_on_port(self, port, name_hint=None):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, port))
        sock.settimeout(0.2)
        while not self.stop_event.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            self._enqueue_packet(data, name_hint)
        sock.close()

    def receive(self):
        if self.class_ports:
            threads = [
                threading.Thread(
                    target=self.receive_on_port,
                    args=(CLASS_PORTS[name], name),
                    daemon=True,
                )
                for name in CLASSES
            ]
            for thread in threads:
                thread.start()
            while not self.stop_event.is_set():
                time.sleep(0.2)
        else:
            self.receive_on_port(self.port)

    def choose_queue(self):
        available = [name for name, q in self.queues.items() if not q.empty()]
        if not available:
            return None
        total = sum(max(0, self.weights[name]) for name in available)
        if total == 0:
            return available[0]
        for name in available:
            self.current[name] += max(0, self.weights[name])
        selected = max(available, key=lambda name: self.current[name])
        self.current[selected] -= total
        return selected

    def schedule(self):
        next_service = time.perf_counter()
        while not self.stop_event.is_set():
            now = time.perf_counter()
            if now < next_service:
                time.sleep(min(next_service - now, 0.01))
                continue
            name = self.choose_queue()
            if name is None:
                time.sleep(0.001)
                next_service = time.perf_counter()
                continue
            _, sent_at, size = self.queues[name].get_nowait()
            latency = (time.time() - sent_at) * 1000
            with self.lock:
                stat = self.stats[name]
                stat["processed"] += 1
                stat["bytes"] += size
                stat["latency_sum"] += latency
                stat["interval_processed"] += 1
                stat["interval_bytes"] += size
                stat["interval_latency"] += latency
                capacity = self.capacity
            next_service = max(next_service + 1.0 / max(capacity, 1), time.perf_counter())

    def control(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host, self.control_port))
        sock.settimeout(0.2)
        while not self.stop_event.is_set():
            try:
                data, address = sock.recvfrom(4096)
                command = json.loads(data.decode())
                with self.lock:
                    for name, weight in command.get("weights", {}).items():
                        if name in CLASSES:
                            self.weights[name] = max(0, int(weight))
                    if "capacity_pps" in command:
                        self.capacity = max(1, int(command["capacity_pps"]))
                    response = {
                        "weights": self.weights, "capacity_pps": self.capacity
                    }
                sock.sendto(json.dumps(response).encode(), address)
                print(f"\nPolicy updated: {response}", flush=True)
            except socket.timeout:
                continue
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"\nInvalid control command: {exc}", flush=True)
        sock.close()

    @staticmethod
    def fairness(values):
        total = sum(values)
        squares = sum(value * value for value in values)
        return total * total / (len(values) * squares) if squares else 1.0

    def report(self):
        print("time class  throughput_kbps latency_ms loss_% processed queued")
        started = time.time()
        while not self.stop_event.wait(1):
            throughputs = []
            rows = []
            with self.lock:
                for name in CLASSES:
                    stat = self.stats[name]
                    count = stat["interval_processed"]
                    throughput = stat["interval_bytes"] * 8 / 1000
                    latency = stat["interval_latency"] / count if count else 0
                    offered = stat["interval_offered"]
                    loss = stat["interval_dropped"] * 100 / offered if offered else 0
                    throughputs.append(throughput)
                    rows.append((name, throughput, latency, loss,
                                 stat["processed"], self.queues[name].qsize()))
                    for key in ("interval_processed", "interval_dropped",
                                "interval_offered", "interval_bytes",
                                "interval_latency"):
                        stat[key] = 0
            elapsed = time.time() - started
            for row in rows:
                print(f"{elapsed:4.0f}s {row[0]:5} {row[1]:16.1f} "
                      f"{row[2]:10.1f} {row[3]:6.1f} {row[4]:9} {row[5]:6}")
            print(f"Jain fairness index: {self.fairness(throughputs):.3f}", flush=True)

    def run(self, duration=0):
        threads = [
            threading.Thread(target=self.receive, daemon=True),
            threading.Thread(target=self.schedule, daemon=True),
            threading.Thread(target=self.control, daemon=True),
            threading.Thread(target=self.report, daemon=True),
        ]
        for thread in threads:
            thread.start()
        if self.class_ports:
            ports = ",".join(str(CLASS_PORTS[n]) for n in CLASSES)
            print(f"Data UDP {self.host} ports [{ports}]; controller UDP "
                  f"{self.host}:{self.control_port}; capacity={self.capacity} pps")
        else:
            print(f"Data UDP {self.host}:{self.port}; controller UDP "
                  f"{self.host}:{self.control_port}; capacity={self.capacity} pps")
        try:
            self.stop_event.wait(duration if duration > 0 else None)
        except KeyboardInterrupt:
            pass
        self.stop_event.set()
        for thread in threads:
            thread.join(timeout=1)


def send_traffic(host, port, traffic_class, rate, duration, payload_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (host, port)
    interval = 1.0 / rate
    padding = bytes(max(0, payload_size - HEADER.size))
    deadline = time.perf_counter() + duration
    next_send = time.perf_counter()
    sent = 0
    while time.perf_counter() < deadline:
        packet = HEADER.pack(MAGIC, CLASSES[traffic_class], sent, time.time()) + padding
        sock.sendto(packet, target)
        sent += 1
        next_send += interval
        delay = next_send - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    sock.close()
    print(f"{traffic_class}: sent {sent} packets")


def update_policy(host, port, weights, capacity=None):
    command = {"weights": weights}
    if capacity is not None:
        command["capacity_pps"] = capacity
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    sock.sendto(json.dumps(command).encode(), (host, port))
    response, _ = sock.recvfrom(4096)
    print("Controller response:", response.decode())
    sock.close()


def update_sdn_policy(weights, ryu_url=DEFAULT_RYU_POLICY_URL):
    payload = json.dumps({"weights": weights}).encode()
    req = urllib.request.Request(
        ryu_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print("Ryu SDN response:", resp.read().decode())
    except urllib.error.URLError as exc:
        print(f"Ryu SDN error: {exc}")
        raise


def resolve_client_port(traffic_class, port, use_class_ports):
    if use_class_ports:
        return CLASS_PORTS[traffic_class]
    return port


def parse_weights(text):
    result = {}
    for item in text.split(","):
        name, value = item.split("=", 1)
        if name not in CLASSES:
            raise argparse.ArgumentTypeError(f"unknown class: {name}")
        result[name] = int(value)
    return result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default="127.0.0.1")
    common.add_argument("--port", type=int, default=19000)

    server = sub.add_parser("server", parents=[common])
    server.add_argument("--control-port", type=int, default=19001)
    server.add_argument("--capacity", type=int, default=800,
                        help="congested bottleneck capacity in packets/sec")
    server.add_argument("--queue-size", type=int, default=200)
    server.add_argument("--weights", type=parse_weights,
                        default={"voice": 8, "video": 3, "bulk": 1})
    server.add_argument("--duration", type=float, default=0)
    server.add_argument(
        "--class-ports",
        action="store_true",
        help="listen on UDP 19001/19002/19003 (Mininet + Ryu)",
    )
    server.add_argument(
        "--mininet",
        action="store_true",
        help="high server capacity; congestion on Mininet links",
    )

    client = sub.add_parser("client", parents=[common])
    client.add_argument("--class", dest="traffic_class", choices=CLASSES,
                        required=True)
    client.add_argument("--rate", type=float, required=True)
    client.add_argument("--duration", type=float, default=10)
    client.add_argument("--size", type=int, default=512)
    client.add_argument(
        "--class-ports",
        action="store_true",
        help="send to per-class UDP port (Mininet + Ryu)",
    )

    controller = sub.add_parser("controller")
    controller.add_argument("--host", default="127.0.0.1")
    controller.add_argument("--port", type=int, default=19001)
    controller.add_argument("--weights", type=parse_weights, required=True)
    controller.add_argument("--capacity", type=int)

    sdn = sub.add_parser(
        "sdn-controller",
        help="push QoS weights to Ryu (OpenFlow priorities)",
    )
    sdn.add_argument("--weights", type=parse_weights, required=True)
    sdn.add_argument("--ryu-url", default=DEFAULT_RYU_POLICY_URL)

    return parser


def main():
    args = build_parser().parse_args()
    if args.mode == "server":
        capacity = args.capacity
        if getattr(args, "mininet", False):
            capacity = MININET_SERVER_CAPACITY
        QoSServer(
            args.host,
            args.port,
            args.control_port,
            capacity,
            args.queue_size,
            args.weights,
            class_ports=getattr(args, "class_ports", False),
        ).run(args.duration)
    elif args.mode == "client":
        port = resolve_client_port(
            args.traffic_class,
            args.port,
            getattr(args, "class_ports", False),
        )
        send_traffic(
            args.host, port, args.traffic_class, args.rate,
            args.duration, args.size,
        )
    elif args.mode == "controller":
        update_policy(args.host, args.port, args.weights, args.capacity)
    elif args.mode == "sdn-controller":
        update_sdn_policy(args.weights, args.ryu_url)


if __name__ == "__main__":
    main()
