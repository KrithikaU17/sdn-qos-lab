#!/usr/bin/env python3
"""
OS-Ken SDN controller for QoS UDP (OpenFlow 1.3). Same behavior as ryu_qos_controller.py.

  POST /topology   {"server_ofport": 4, "switch_name": "s1"}
  POST /policy     {"weights": {"voice": 8, "video": 3, "bulk": 1}}
  GET  /status
"""

import json

import ovs_qos
from os_ken.app import wsgi
from os_ken.app.wsgi import ControllerBase, route
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3

CLASS_BY_UDP_PORT = {
    19001: "voice",
    19002: "video",
    19003: "bulk",
}

DEFAULT_WEIGHTS = {"voice": 1, "video": 1, "bulk": 1}
DEFAULT_SERVER_OFPORT = 4


def weights_to_priorities(weights):
    priorities = {}
    for name in ovs_qos.CLASS_NAMES:
        weight = max(0, int(weights.get(name, 0)))
        priorities[name] = 100 + weight * 1000
    return priorities


class QoSPolicyAPI(ControllerBase):
    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.controller = data["controller"]

    @route("qos", "/policy", methods=["POST"])
    def set_policy(self, req, **_kwargs):
        try:
            body = json.loads(req.body.decode() if req.body else "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": str(exc)})
        self.controller.apply_policy(body.get("weights", {}))
        return json.dumps(
            {
                "weights": self.controller.weights,
                "ovs_port": self.controller.ovs_port,
                "status": "ok",
            }
        )

    @route("qos", "/topology", methods=["POST"])
    def set_topology(self, req, **_kwargs):
        try:
            body = json.loads(req.body.decode() if req.body else "{}")
        except json.JSONDecodeError as exc:
            return json.dumps({"error": str(exc)})
        self.controller.server_ofport = int(
            body.get("server_ofport", DEFAULT_SERVER_OFPORT)
        )
        self.controller.switch_name = body.get("switch_name", ovs_qos.DEFAULT_SWITCH)
        self.controller.port_max_bps = int(
            body.get("port_max_bps", ovs_qos.DEFAULT_PORT_MAX_BPS)
        )
        self.controller.reinstall_all()
        return json.dumps(
            {
                "server_ofport": self.controller.server_ofport,
                "switch_name": self.controller.switch_name,
                "ovs_port": self.controller.ovs_port,
                "status": "ok",
            }
        )

    @route("qos", "/status", methods=["GET"])
    def status(self, req, **_kwargs):
        return json.dumps(
            {
                "weights": self.controller.weights,
                "server_ofport": self.controller.server_ofport,
                "switch_name": self.controller.switch_name,
                "ovs_port": self.controller.ovs_port,
                "queue_map": ovs_qos.CLASS_QUEUE_ID,
                "switches": list(self.controller.datapaths.keys()),
            }
        )


class QoSController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": wsgi.WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.weights = dict(DEFAULT_WEIGHTS)
        self.server_ofport = DEFAULT_SERVER_OFPORT
        self.switch_name = ovs_qos.DEFAULT_SWITCH
        self.port_max_bps = ovs_qos.DEFAULT_PORT_MAX_BPS
        self.ovs_port = None
        wsgi_app = kwargs["wsgi"]
        wsgi_app.register(QoSPolicyAPI, {"controller": self})

    def apply_policy(self, weights):
        for name in ovs_qos.CLASS_NAMES:
            if name in weights:
                self.weights[name] = max(0, int(weights[name]))
        self.logger.info("SDN policy weights: %s", self.weights)
        self.reinstall_all()

    def reinstall_all(self):
        self._apply_ovs_qos()
        for dp in self.datapaths.values():
            self._install_qos_flows(dp)

    def _apply_ovs_qos(self):
        self.ovs_port = ovs_qos.configure_switch_qos(
            self.switch_name,
            self.server_ofport,
            self.weights,
            port_max_bps=self.port_max_bps,
        )

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)
        ]
        self._add_flow(dp, 0, match, actions)
        self.reinstall_all()

    def _install_qos_flows(self, dp):
        parser = dp.ofproto_parser
        priorities = weights_to_priorities(self.weights)
        for udp_port, class_name in CLASS_BY_UDP_PORT.items():
            priority = priorities[class_name]
            queue_id = ovs_qos.CLASS_QUEUE_ID[class_name]
            match = parser.OFPMatch(
                eth_type=0x0800,
                ip_proto=17,
                udp_dst=udp_port,
            )
            actions = [
                parser.OFPActionSetQueue(queue_id),
                parser.OFPActionOutput(self.server_ofport),
            ]
            self._add_flow(dp, priority, match, actions)
            self.logger.info(
                "switch %s %s udp:%s pri %s queue %s -> ofport %s",
                dp.id,
                class_name,
                udp_port,
                priority,
                queue_id,
                self.server_ofport,
            )

    def _add_flow(self, dp, priority, match, actions):
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
