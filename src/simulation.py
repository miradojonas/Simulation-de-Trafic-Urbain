"""
Contient les classes métier de simulation : vehicule + TrafficSimulation
"""

import random
from dataclasses import dataclass

import networkx as nx

from markov_model import MarkovTrafficModel
from queue_model import QueueSystem


@dataclass
class Vehicle:
    # Représente un véhicule qui avance le long d'un chemin
    path: list
    kind: str = "car"
    sprite: str = "sedan"
    edge_index: int = 0   # index de l'arête courante dans path
    progress: float = 0.0 # progression [0, 1] sur l'arête courante
    speed: float = 0.02   # progression ajoutée à chaque tick
    lane_side: int = 1    # -1 = file gauche, +1 = file droite
    stops: int = 0        # nb d'arrêts cumulés
    wait_ticks: int = 0   # temps cumulé à l'arrêt


class TrafficSimulation:
    # Moteur principal de la simulation
    def __init__(self, G, n_vehicles=20, seed=42):
        self.G = G
        self.rng = random.Random(seed)
        self.nodes = list(self.G.nodes)
        self.vehicles = []
        self.running = True
        self.tick_count = 0
        self.completed_trips = 0

        # Module 1 : chaîne de Markov (macro-état trafic)
        self.markov = MarkovTrafficModel(seed=seed, initial_state="FLUIDE")
        self.markov_update_every = 20
        self.current_speed_factor = self.markov.speed_factor()

        # Module 2 : files d'attente aux intersections
        self.queue_system = QueueSystem(seed=seed)
        sample_nodes = self.nodes[:]
        self.rng.shuffle(sample_nodes)
        self.queue_nodes = sample_nodes[: min(25, len(sample_nodes))]
        self.queue_system.init_intersections(self.queue_nodes)

        # Contrainte sécurité / trafic
        self.min_progress_gap = 0.10
        self.stop_line_progress = 0.82

        # Feux tricolores
        self.sim_ticks_per_second = 30
        self.enable_traffic_lights = False
        self.light_config = {
            # Durée de lumière
            "green_seconds": 18,
            "yellow_seconds": 3,
            "all_red_seconds": 1,
            "offset_mode": "checkerboard",
        }
        self._apply_light_config(self.light_config)
        self._init_vehicles(n_vehicles)

    def _random_vehicle_kind(self):
        kinds = ["car", "suv", "truck", "bus"]
        weights = [0.55, 0.20, 0.15, 0.10]
        return self.rng.choices(kinds, weights=weights, k=1)[0]

    def _speed_for_kind(self, kind: str) -> float:
        if kind == "truck":
            return self.rng.uniform(0.008, 0.018)
        if kind == "bus":
            return self.rng.uniform(0.010, 0.020)
        if kind == "suv":
            return self.rng.uniform(0.012, 0.028)
        return self.rng.uniform(0.013, 0.032)

    def _sprite_for_kind(self, kind: str) -> str:
        choices = {
            "car": ["sedan", "taxi", "sports_red", "sports_yellow"],
            "suv": ["suv", "suv_green", "suv_large"],
            "truck": ["truck", "truckdelivery", "towtruck"],
            "bus": ["bus", "bus_school", "transport"],
        }
        pool = choices.get(kind, ["sedan"])
        return self.rng.choice(pool)

    def _random_node_pair(self):
        u = self.rng.choice(self.nodes)
        v = self.rng.choice(self.nodes)
        while v == u:
            v = self.rng.choice(self.nodes)
        return u, v

    def _build_path(self):
        for _ in range(30):
            u, v = self._random_node_pair()
            try:
                return nx.shortest_path(self.G, u, v, weight="travel_time")
            except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                continue
        return None

    def _build_path_from(self, start_node):
        if start_node not in self.G:
            return None

        for _ in range(30):
            v = self.rng.choice(self.nodes)
            while v == start_node:
                v = self.rng.choice(self.nodes)
            try:
                return nx.shortest_path(self.G, start_node, v, weight="travel_time")
            except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                continue
        return None

    def _init_vehicles(self, n):
        for _ in range(n):
            path = self._build_path()
            if path and len(path) >= 2:
                kind = self._random_vehicle_kind()
                sprite = self._sprite_for_kind(kind)
                self.vehicles.append(
                    Vehicle(
                        path=path,
                        kind=kind,
                        sprite=sprite,
                        speed=self._speed_for_kind(kind),
                        lane_side=-1 if self.rng.random() < 0.5 else 1,
                    )
                )

    def _apply_light_config(self, cfg: dict):
        green_s = max(8, int(cfg.get("green_seconds", 18)))
        yellow_s = max(2, int(cfg.get("yellow_seconds", 3)))
        all_red_s = max(0, int(cfg.get("all_red_seconds", 1)))

        self.light_config["green_seconds"] = green_s
        self.light_config["yellow_seconds"] = yellow_s
        self.light_config["all_red_seconds"] = all_red_s
        self.light_config["offset_mode"] = cfg.get("offset_mode", "checkerboard")

        self.light_green_ticks = self.sim_ticks_per_second * green_s
        self.light_yellow_ticks = self.sim_ticks_per_second * yellow_s
        self.light_all_red_ticks = self.sim_ticks_per_second * all_red_s

        self.light_phase_offset = {
            n: self._build_light_offset_for_node(n) for n in self.nodes
        }

    def configure_traffic_lights(
            self,
            enabled: bool | None = None,
            green_seconds: int | None = None,
            yellow_seconds: int | None = None,
            all_red_seconds: int | None = None,
            offset_mode: str | None = None,
    ):
        if enabled is not None:
            self.enable_traffic_lights = bool(enabled)

        cfg = dict(self.light_config)
        if green_seconds is not None:
            cfg["green_seconds"] = green_seconds
        if yellow_seconds is not None:
            cfg["yellow_seconds"] = yellow_seconds
        if all_red_seconds is not None:
            cfg["all_red_seconds"] = all_red_seconds
        if offset_mode is not None:
            cfg["offset_mode"] = offset_mode

        self._apply_light_config(cfg)

    def _edge_orientation(self, n1, n2) -> str:
        x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
        x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
        return "EW" if abs(x2 - x1) >= abs(y2 - y1) else "NS"

    def _build_light_offset_for_node(self, node):
        mode = self.light_config.get("offset_mode", "checkerboard")
        half_cycle = (
            self.light_green_ticks
            + self.light_yellow_ticks
            + self.light_all_red_ticks
        )

        if mode == "none":
            return 0

        if mode == "hash":
            return half_cycle if (hash(str(node)) % 2 == 1) else 0

        # mode checkerboard (recommandé)
        parts = str(node).split("_")
        if len(parts) == 3 and parts[0] == "I":
            try:
                r, c = int(parts[1]), int(parts[2])
                return half_cycle if ((r + c) % 2 == 1) else 0
            except ValueError:
                pass

        return half_cycle if (hash(str(node)) % 2 == 1) else 0

    def _light_state_for_node(self, node):
        # Cycle : NS vert -> NS jaune -> rouge total -> EW vert -> EW jaune -> rouge total
        total = 2 * (
            self.light_green_ticks
            + self.light_yellow_ticks
            + self.light_all_red_ticks
        )
        t = (self.tick_count + self.light_phase_offset.get(node, 0)) % total

        ns_green_end = self.light_green_ticks
        ns_yellow_end = ns_green_end + self.light_yellow_ticks
        ns_all_red_end = ns_yellow_end + self.light_all_red_ticks
        ew_green_end = ns_all_red_end + self.light_green_ticks
        ew_yellow_end = ew_green_end + self.light_yellow_ticks

        if t < ns_green_end:
            return {"NS": "green", "EW": "red"}
        if t < ns_yellow_end:
            return {"NS": "yellow", "EW": "red"}
        if t < ns_all_red_end:
            return {"NS": "red", "EW": "red"}
        if t < ew_green_end:
            return {"NS": "red", "EW": "green"}
        if t < ew_yellow_end:
            return {"NS": "red", "EW": "yellow"}
        return {"NS": "red", "EW": "red"}

    def _must_stop_for_light(self, n1, n2) -> bool:
        orient = self._edge_orientation(n1, n2)
        light = self._light_state_for_node(n2)
        return light.get(orient, "red") in ("red", "yellow")

    def reset(self):
        n = len(self.vehicles)
        self.vehicles = []
        self.tick_count = 0
        self._init_vehicles(n)
        self.markov.state = "FLUIDE"
        self.current_speed_factor = self.markov.speed_factor()
        self.queue_system.init_intersections(self.queue_nodes)
        self.completed_trips = 0

    def toggle(self):
        self.running = not self.running

    def step(self):
        if not self.running:
            return

        self.tick_count += 1

        # 1) Markov
        if self.tick_count % self.markov_update_every == 0:
            self.markov.step()
            self.current_speed_factor = self.markov.speed_factor()

        # 2) Queue
        self.queue_system.step(self.markov.state)

        # 3) Avancement véhicule + feux
        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                self.completed_trips += 1
                current_node = veh.path[-1]
                new_path = self._build_path_from(current_node)
                if new_path and len(new_path) >= 2:
                    veh.path = new_path
                    veh.edge_index = 0
                    veh.progress = 0.0
                continue

            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]
            delta = veh.speed * self.current_speed_factor

            if self.enable_traffic_lights and self._must_stop_for_light(n1, n2):
                old = veh.progress
                veh.progress = min(veh.progress + delta, self.stop_line_progress)
                if veh.progress <= old + 1e-9:
                    veh.wait_ticks += 1
                if veh.progress >= self.stop_line_progress - 1e-6:
                    veh.stops += 1
            else:
                veh.progress += delta

        # 4) Distance de sécurité (même arête + même file)
        groups = {}
        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                continue
            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]
            key = (n1, n2, veh.lane_side)
            groups.setdefault(key, []).append(veh)

        for vehs in groups.values():
            vehs.sort(key=lambda v: v.progress, reverse=True)
            for idx in range(1, len(vehs)):
                leader = vehs[idx - 1]
                follower = vehs[idx]
                max_allowed = max(0.0, leader.progress - self.min_progress_gap)
                if follower.progress > max_allowed:
                    follower.progress = max_allowed
                    follower.wait_ticks += 1

        # 5) Passage à l'arête suivante
        for veh in self.vehicles:
            while veh.progress >= 1.0 and veh.edge_index < len(veh.path) - 1:
                veh.progress -= 1.0
                veh.edge_index += 1

    def traffic_state(self):
        return self.markov.state

    def vehicle_positions(self):
        positions = []
        for kind_list in self.vehicle_positions_by_type().values():
            positions.extend(kind_list)
        return positions

    def vehicle_positions_by_type(self):
        by_type = {"car": [], "suv": [], "truck": [], "bus": []}

        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                node = veh.path[-1]
                x = self.G.nodes[node]["x"]
                y = self.G.nodes[node]["y"]
                by_type.setdefault(veh.kind, []).append((x, y))
                continue

            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]

            x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
            x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]

            t = veh.progress
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            by_type.setdefault(veh.kind, []).append((x, y))

        return by_type

    def vehicle_render_data(self):
        data = []

        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                node = veh.path[-1]
                x = self.G.nodes[node]["x"]
                y = self.G.nodes[node]["y"]
                data.append(
                    {
                        "x": x,
                        "y": y,
                        "kind": veh.kind,
                        "sprite": veh.sprite,
                        "lane_side": veh.lane_side,
                    }
                )
                continue

            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]
            x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
            x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
            t = veh.progress

            data.append(
                {
                    "x": x1 + t * (x2 - x1),
                    "y": y1 + t * (y2 - y1),
                    "kind": veh.kind,
                    "sprite": veh.sprite,
                    "lane_side": veh.lane_side,
                }
            )

        return data

    def avg_speed(self):
        if not self.vehicles:
            return 0.0
        return sum(v.speed for v in self.vehicles) / len(self.vehicles)

    def avg_queue(self):
        return self.queue_system.avg_queue()

    def max_queue(self):
        return self.queue_system.max_queue()

    def queue_snapshot(self):
        if hasattr(self, "queue_system") and hasattr(self.queue_system, "queues"):
            return dict(self.queue_system.queues)
        return {}

    def traffic_lights_snapshot(self):
        return {node: self._light_state_for_node(node) for node in self.nodes}
    
    def throughput_per_1000_ticks(self):
        if self.tick_count <= 0:
            return 0.0
        return (self.completed_trips / self.tick_count) * 1000.0