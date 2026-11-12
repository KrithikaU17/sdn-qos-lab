#!/usr/bin/env python3
"""
Ryu SDN controller for QoS UDP (OpenFlow 1.3).

Matches UDP destination ports per traffic class and installs flow rules with
priorities derived from policy weights. HTTP API (default port 8080):

  POST /topology   {"server_ofport": 4}
  POST /policy     {"weights": {"voice": 8, "video": 3, "bulk": 1}}
  GET  /status
"""

import json

from ryu.app import wsgi
from ryu.app.wsgi import ControllerBase, route
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls

# UDP destination port → traffic class (must match qos_udp.CLASS_PORTS).
CLASS_BY_UDP_PORT = {
    19001: "voice",
    19002: "video",
    19003: "bulk",
}

DEFAULT_WEIGHTS = {"voice": 1, "video": 1, "bulk": 1}
# Default switch port number that leads to the UDP server.
DEFAULT_SERVER_OFPORT = 4


def weights_to_priorities(weights):
    """Convert each class weight into a rule priority. Higher weight means a higher priority number, which the switch checks first."""
    priorities = {}
    for name in ("voice", "video", "bulk"):
        weight = max(0, int(weights.get(name, 0)))
        priorities[name] = 100 + weight * 1000
    return priorities


class QoSPolicyAPI(ControllerBase):
    """HTTP REST API used by Mininet and qos_udp.py to change SDN policy."""

    def __init__(self, req, link, data, **config):
        """Keep a handle to the Ryu app so REST calls can update live flows."""
        super().__init__(req, link, data, **config)
        self.controller = data["controller"]

    @route("qos", "/policy", methods=["POST"])
    def set_policy(self, req, **_kwargs):
        """POST /policy — update class weights and reinstall OpenFlow rules."""
        try:
            body = json.loads(req.body.decode() if req.body else "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": str(exc)})
        self.controller.apply_policy(body.get("weights", {}))
        return json.dumps({"weights": self.controller.weights, "status": "ok"})

    @route("qos", "/topology", methods=["POST"])
    def set_topology(self, req, **_kwargs):
        """POST /topology — set which switch port leads to the UDP server."""
        try:
            body = json.loads(req.body.decode() if req.body else "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": str(exc)})
        self.controller.server_ofport = int(
            body.get("server_ofport", DEFAULT_SERVER_OFPORT)
        )
        self.controller.reinstall_all()
        return json.dumps(
            {
                "server_ofport": self.controller.server_ofport,
                "status": "ok",
            }
        )

    @route("qos", "/status", methods=["GET"])
    def status(self, req, **_kwargs):
        """GET /status — current weights, server port, and connected switches."""
        return json.dumps(
            {
                "weights": self.controller.weights,
                "server_ofport": self.controller.server_ofport,
                "switches": list(self.controller.datapaths.keys()),
            }
        )


class QoSController(app_manager.RyuApp):
    """Ryu app: when a switch connects, install UDP class flows toward the server."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": wsgi.WSGIApplication}

    def __init__(self, *args, **kwargs):
        """Register the REST API and start with equal class weights."""
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.weights = dict(DEFAULT_WEIGHTS)
        self.server_ofport = DEFAULT_SERVER_OFPORT
        wsgi_app = kwargs["wsgi"]
        wsgi_app.register(QoSPolicyAPI, {"controller": self})

    def apply_policy(self, weights):
        """Save new class weights and push updated flow priorities to all switches."""
        for name in ("voice", "video", "bulk"):
            if name in weights:
                self.weights[name] = max(0, int(weights[name]))
        self.logger.info("SDN policy weights: %s", self.weights)
        self.reinstall_all()

    def reinstall_all(self):
        """Rewrite QoS flows on every connected switch."""
        for dp in self.datapaths.values():
            self._install_qos_flows(dp)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        """When a switch connects: tell it to send unknown packets here, then install the class rules."""
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)
        ]
        self._add_flow(dp, 0, match, actions)
        self._install_qos_flows(dp)

    def _install_qos_flows(self, dp):
        """Install one rule per traffic class: packets sent to that class's UDP port go out the server port."""
        parser = dp.ofproto_parser
        priorities = weights_to_priorities(self.weights)
        for udp_port, class_name in CLASS_BY_UDP_PORT.items():
            priority = priorities[class_name]
            match = parser.OFPMatch(
                eth_type=0x0800,
                ip_proto=17,
                udp_dst=udp_port,
            )
            actions = [parser.OFPActionOutput(self.server_ofport)]
            self._add_flow(dp, priority, match, actions)
            self.logger.info(
                "switch %s %s udp:%s priority %s -> ofport %s",
                dp.id,
                class_name,
                udp_port,
                priority,
                self.server_ofport,
            )

    def _add_flow(self, dp, priority, match, actions):
        """Send one rule to the switch: a match (which packets) plus an action (where to send them). The rule never expires."""
        parser = dp.ofproto_parser
        instructions = [
            parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)
        ]
        mod = parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=0,
            hard_timeout=0,
        )
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def packet_in_handler(self, ev):
        """Send packets that match no QoS rule (such as ARP or ping) to every port, so normal traffic still works."""
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        in_port = msg.match['in_port']

        actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None

        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data
        )
        dp.send_msg(out)
