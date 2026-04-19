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
    # Répresente un véhicule qui avance le long d'un chemin
    path: list
    kind: str = "car"
    sprite: str = "sedan"
    edge_index: int = 0   #index de l'arête courante dans path
    progress: float = 0.0 # progression [0, 1] sur l'arête courante
    speed: float = 0.02   #progression ajoutée à chaque tick

class TrafficSimulation:
    # Moteur principale de la simulation
    def __init__(self, G, n_vehicles=20, seed=42):
        self.G = G
        self.rng = random.Random(seed)
        self.nodes = list(self.G.nodes)
        self.vehicles = []
        self.running = True
        self.tick_count = 0
        self._init_vehicles(n_vehicles)
        self.markov = MarkovTrafficModel(seed=seed, initial_state="FLUIDE")
        self.markov_update_every = 20
        self.current_speed_factor = 1.0
        self.queue_system = QueueSystem(seed=seed)
        # Prendre qlqs interserctions aléatoires
        sample_nodes = self.nodes[:]
        self.rng.shuffle(sample_nodes)
        self.queue_nodes = sample_nodes[:25]
        self.queue_system.init_intersections(self.queue_nodes)

    def _random_vehicle_kind(self):
        # Répartition simple du parc roulant
        kinds = ["car", "suv", "truck", "bus"]
        weights = [0.55, 0.20, 0.15, 0.10]
        return self.rng.choices(kinds, weights=weights, k=1)[0]

    def _speed_for_kind(self, kind: str) -> float:
        # Profils de vitesse de base (unité simulation/tick)
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
        # Tire deux noeuds distincts aléatoirements
        u = self.rng.choice(self.nodes)
        v = self.rng.choice(self.nodes)
        while v == u:
            v = self.rng.choice(self.nodes)
        return u, v

    def _build_path(self):
        # Construit un plus court chemin entre 2 noeuds aléatoires
        for _ in range(30):
            u, v = self._random_node_pair()
            try:
                # Plus court chemin pondéré par temps de trajet
                return nx.shortest_path(self.G, u, v, weight="travel_time")
            except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                continue
        return None
    
    def _init_vehicles(self, n):
        # Initialise n véhicule avec chemin aléatoires valides.
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
                        speed=self._speed_for_kind(kind)
                    )
                )

    def reset(self):
        # Reinititalise la simulation en récreant les trajets.
        n = len(self.vehicles)
        self.vehicles = []
        self.tick_count = 0
        self._init_vehicles(n)
        self.markov.state = "FLUIDE"
        self.current_speed_factor = self.markov.speed_factor()
        self.queue_system.init_intersections(self.queue_nodes)

    def toggle(self):
        # Bascule de RUN vers PAUSE et vice versa
        self.running = not self.running

    def step(self):
        # Avance la simulation d'un tick
        if not self.running:
            return
        
        self.tick_count += 1

        if self.tick_count % self.markov_update_every == 0:
            self.markov.step()
            self.current_speed_factor = self.markov.speed_factor()

        self.queue_system.step(self.markov.state)

        for veh in self.vehicles:
            # Si arrivé au bout : nouveau trajet
            if veh.edge_index >= len(veh.path) - 1:
                new_path = self._build_path()
                if new_path and len(new_path) >= 2:
                    veh.path = new_path
                    veh.edge_index = 0
                    veh.progress = 0
                continue

            veh.progress += veh.speed * self.current_speed_factor# Avancement sur l'arête

            # Passage vers l'arête suivant si progress >= 1
            while veh.progress >= 1.0 and veh.edge_index < len(veh.path) - 1:
                veh.progress -= 1.0
                veh.edge_index += 1

    def traffic_state(self):
        return self.markov.state

    def vehicle_positions(self):
        # Retourne les positions (x, y) interpolées des véhicules
        positions = []
        for kind_list in self.vehicle_positions_by_type().values():
            positions.extend(kind_list)
        return positions

    def vehicle_positions_by_type(self):
        # Retourne les positions regroupées par type de véhicule.
        by_type = {"car": [], "suv": [], "truck": [], "bus": []}

        for veh in self.vehicles:
            # Si au dernier noeud, position = noeud final
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
        # Retourne les positions avec métadonnées de rendu (type + sprite)
        data = []

        for veh in self.vehicles:
            # Position finale si véhicule au dernier noeud
            if veh.edge_index >= len(veh.path) - 1:
                node = veh.path[-1]
                x = self.G.nodes[node]["x"]
                y = self.G.nodes[node]["y"]
                data.append({
                    "x": x,
                    "y": y,
                    "kind": veh.kind,
                    "sprite": veh.sprite,
                })
                continue

            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]
            x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
            x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
            t = veh.progress

            data.append({
                "x": x1 + t * (x2 - x1),
                "y": y1 + t * (y2 - y1),
                "kind": veh.kind,
                "sprite": veh.sprite,
            })

        return data
    
    def avg_speed(self):
        # Vitesse moyenne (unité simulation/tick)
        if not self.vehicles:
            return 0.0
        return sum(v.speed for v in self.vehicles) / len(self.vehicles)
    
    def avg_queue(self):
        return self.queue_system.avg_queue()
    
    def max_queue(self):
        return self.queue_system.max_queue()

    def queue_snapshot(self):
        # Retourne une copie des files d'attente d'intersection -> longueur
        # Utilisé par l'UI pour un rendu visuel de la congestion
        if hasattr(self, "queue_system") and hasattr(self.queue_system, "queues"):
            return dict(self.queue_system.queues)
        return {}