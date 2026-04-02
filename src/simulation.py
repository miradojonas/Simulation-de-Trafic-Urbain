"""
Contient les classes métier de simulation : vehicule + TrafficSimulation
"""

import random
from dataclasses import dataclass
import networkx as nx

@dataclass
class Vehicle:
    # Répresente un véhicule qui avance le long d'un chemin
    path: list
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
                self.vehicles.append(
                    Vehicle(
                        path=path,
                        speed=self.rng.uniform(0.01, 0.04)
                    )
                )

    def reset(self):
        # Reinititalise la simulation en récreant les trajets.
        n = len(self.vehicles)
        self.vehicles = []
        self.tick_count = 0
        self._init_vehicles(n)

    def toggle(self):
        # Bascule de RUN vers PAUSE et vice versa
        self.running = not self.running

    def step(self):
        # Avance la simulation d'un tick
        if not self.running:
            return
        
        self.tick_count += 1

        for veh in self.vehicles:
            # Si arrivé au bout : nouveau trajet
            if veh.edge_index >= len(veh.path) - 1:
                new_path = self._build_path()
                if new_path and len(new_path) >= 2:
                    veh.path = new_path
                    veh.edge_index = 0
                    veh.progress = 0
                continue

            veh.progress += veh.speed # Avancement sur l'arête

            # Passage vers l'arête suivant si progress >= 1
            while veh.progress >= 1.0 and veh.edge_index < len(veh.path) - 1:
                veh.progress -= 1.0
                veh.edge_index += 1

    def vehicle_positions(self):
        # Retourne les positions (x, y) interpolées des véhicules
        positions = []

        for veh in self.vehicles:
            # Si au dernier noeud, position = noeud final
            if veh.edge_index >= len(veh.path) - 1:
                node = veh.path[-1]
                x = self.G.nodes[node]["x"]
                y = self.G.nodes[node]["y"]
                positions.append((x, y))
                continue

            n1 = veh.path[veh.edge_index]
            n2 = veh.path[veh.edge_index + 1]

            x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
            x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]

            t = veh.progress
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            positions.append((x, y))

        return positions
    
    def avg_speed(self):
        # Vitesse moyenne (unité simulation/tick)
        if not self.vehicles:
            return 0.0
        return sum(v.speed for v in self.vehicles) / len(self.vehicles)