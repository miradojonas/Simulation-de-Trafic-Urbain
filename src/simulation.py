"""
Module principal – Moteur de simulation de trafic urbain
Contient :
  - Vehicle   : représentation d'un véhicule (position, état, statistiques)
  - TrafficSimulation : moteur principal intégrant Markov + Files d'attente
"""

import random
from dataclasses import dataclass, field

import networkx as nx

from markov_model import MarkovTrafficModel
from queue_model import QueueSystem


# ---------------------------------------------------------------------------
# Entité Véhicule
# ---------------------------------------------------------------------------
@dataclass
class Vehicle:
    """
    Représente un véhicule se déplaçant le long d'un chemin dans le graphe.

    Attributs
    ---------
    path        : liste ordonnée de nœuds (source → destination)
    kind        : catégorie du véhicule (car, suv, truck, bus)
    sprite      : nom de l'image sprite associée
    edge_index  : index de l'arête courante dans path
    progress    : avancement sur l'arête courante ∈ [0, 1]
    speed       : incrément de progression par tick (avant facteur Markov)
    lane_side   : file latérale relative au sens ( -1 = voie droite, +1 = voie gauche )
    stops       : nombre d'arrêts cumulés (feux rouges, sécurité)
    wait_ticks  : durée totale d'attente cumulée (en ticks)
    """
    path: list
    kind: str = "car"
    sprite: str = "sedan"
    edge_index: int = 0
    progress: float = 0.0
    speed: float = 0.02
    lane_side: int = -1
    stops: int = 0
    wait_ticks: int = 0
    queued_node: object | None = None
    blocked_last_tick: bool = False
    occupied_node: object | None = None
    prev_progress: float = 0.0


# ---------------------------------------------------------------------------
# Moteur de simulation
# ---------------------------------------------------------------------------
class TrafficSimulation:
    """
    Moteur principal de la simulation de trafic urbain.

    Intègre :
      - Module 1 : Chaîne de Markov (état macro du trafic)
      - Module 2 : Files d'attente aux intersections
      - Feux tricolores (cycle NS/EW configurable)
      - Contrainte de sécurité inter-véhicules
    """

    def __init__(self, G, n_vehicles: int = 20, seed: int = 42):
        self.G = G
        self.rng = random.Random(seed)
        self.nodes = list(self.G.nodes)
        self.vehicles: list[Vehicle] = []
        self.running = True
        self.tick_count = 0
        self.completed_trips = 0

        # ── Module 1 : Chaîne de Markov ─────────────────────────────────
        # Modélise l'état macro du trafic (FLUIDE / RALENTI / BOUCHON)
        self.markov = MarkovTrafficModel(seed=seed, initial_state="FLUIDE")
        self.markov_update_every = 20   # mise à jour toutes les N ticks
        self.current_speed_factor = self.markov.speed_factor()

        # ── Paramètres de sécurité ────────────────────────────────────────
        self.min_progress_gap = 0.10        # écart minimal entre véhicules
        self.stop_line_progress = 0.82      # position de la ligne d'arrêt
        self.intersection_entry_eps = 0.004  # seuil (progress) pour considérer "dans le carrefour"

        # ── Règles d'intersection (réservation / anti-conflit) ───────────
        # Empêche plusieurs véhicules de franchir simultanément une même
        # intersection (surtout utile sur les nœuds avec feux).
        self.enable_intersection_reservations = True
        # "all" : 1 véhicule max par intersection et par tick.
        # "signals" : uniquement sur self.signal_nodes.
        self.reservation_scope = "all"
        # Verrou d'occupation : évite qu'un véhicule entre dans un carrefour
        # pendant qu'un autre y est encore (prévention des chevauchements).
        self.enable_intersection_occupancy = True
        self._intersection_occupancy: dict = {}

        # ── Feux tricolores ───────────────────────────────────────────────
        self.sim_ticks_per_second = 30
        self.enable_traffic_lights = False
        # On ne met pas des feux partout : seulement sur quelques intersections clés
        self.max_signal_nodes = 14
        self.signal_nodes = set(self._select_signal_nodes(self.max_signal_nodes))
        self.light_config = {
            "green_seconds":    18,
            "yellow_seconds":   3,
            "all_red_seconds":  1,
            "offset_mode":      "checkerboard",
        }
        self._apply_light_config(self.light_config)

        # ── Module 2 : Files d'attente aux intersections ─────────────────
        # Modélise saturation / attente / congestion aux carrefours.
        # On synchronise les intersections des files avec les intersections à feux,
        # pour que les métriques reflètent mieux ce qui se passe visuellement.
        self.queue_system = QueueSystem(seed=seed)
        self.queue_nodes: list = []
        self._sync_queue_nodes_with_signals(reset=True)

        self._init_vehicles(n_vehicles)

    def _reservation_applies_to_node(self, node) -> bool:
        if not self.enable_intersection_reservations:
            return False
        scope = (getattr(self, "reservation_scope", "signals") or "signals").lower()
        if scope == "all":
            return True
        return node in self.signal_nodes

    def _queue_pass_probability(self, node) -> float:
        """Probabilité de franchissement d'une intersection (0..1) selon la file locale."""
        try:
            q = int(self.queue_system.queues.get(node, 0))
        except Exception:
            q = 0

        # Simple : plus la file est longue, plus c'est difficile de franchir.
        # p = 1 / (1 + beta*q)  (beta modeste pour ne pas tout bloquer)
        beta = 0.18
        p = 1.0 / (1.0 + beta * max(0, q))
        # Plancher pour éviter un blocage visuel permanent
        return max(0.20, min(1.0, p))

    def _sync_queue_nodes_with_signals(self, reset: bool = False) -> None:
        """Aligne les intersections du module de file d'attente sur `signal_nodes`."""
        target = list(self.signal_nodes) if self.signal_nodes else []
        if not target:
            sample_nodes = self.nodes[:]
            self.rng.shuffle(sample_nodes)
            target = sample_nodes[: min(25, len(sample_nodes))]

        prev = {}
        if not reset:
            try:
                prev = self.queue_system.snapshot()
            except Exception:
                prev = {}

        self.queue_nodes = target
        self.queue_system.init_intersections(self.queue_nodes)
        if prev:
            for nid in self.queue_nodes:
                if nid in prev:
                    self.queue_system.queues[nid] = int(prev[nid])

    def _select_signal_nodes(self, max_nodes: int) -> list:
        """Sélectionne quelques intersections 'importantes' (degré élevé) pour y placer des feux."""
        max_nodes = max(0, int(max_nodes))
        if max_nodes == 0:
            return []

        nodes = list(self.G.nodes)
        if not nodes:
            return []

        scored = []
        for n in nodes:
            try:
                deg = int(self.G.degree(n))
            except Exception:
                deg = 0
            scored.append((deg, str(n), n))

        scored.sort(reverse=True)
        return [n for _deg, _s, n in scored[:max_nodes]]

    def set_signal_nodes(self, nodes) -> None:
        """Force la liste des intersections qui ont des feux (utilisé par l'IHM / optimisation)."""
        self.signal_nodes = set(nodes or [])
        # Recalcule les offsets car ils dépendent du node_id
        self._apply_light_config(self.light_config)
        self._sync_queue_nodes_with_signals(reset=False)

    # -----------------------------------------------------------------------
    # Génération des véhicules
    # -----------------------------------------------------------------------
    def _random_vehicle_kind(self) -> str:
        kinds   = ["car", "suv", "truck", "bus"]
        weights = [0.55, 0.20, 0.15, 0.10]
        return self.rng.choices(kinds, weights=weights, k=1)[0]

    def _speed_for_kind(self, kind: str) -> float:
        if kind == "truck":
            return self.rng.uniform(0.008, 0.018)
        if kind == "bus":
            return self.rng.uniform(0.010, 0.020)
        if kind == "suv":
            return self.rng.uniform(0.012, 0.028)
        return self.rng.uniform(0.013, 0.032)   # car (défaut)

    def _sprite_for_kind(self, kind: str) -> str:
        choices = {
            "car":   ["sedan", "taxi", "sports_red", "sports_yellow"],
            "suv":   ["suv", "suv_green", "suv_large"],
            "truck": ["truck", "truckdelivery", "towtruck"],
            "bus":   ["bus", "bus_school", "transport"],
        }
        pool = choices.get(kind, ["sedan"])
        return self.rng.choice(pool)

    def _random_node_pair(self):
        u = self.rng.choice(self.nodes)
        v = self.rng.choice(self.nodes)
        while v == u:
            v = self.rng.choice(self.nodes)
        return u, v

    def _build_path(self) -> list | None:
        for _ in range(30):
            u, v = self._random_node_pair()
            try:
                return nx.shortest_path(self.G, u, v, weight="travel_time")
            except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                continue
        return None

    def _build_path_from(self, start_node) -> list | None:
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

    def _init_vehicles(self, n: int):
        """Génération initiale des N véhicules (arrivée aléatoire Monte Carlo)."""
        for _ in range(n):
            path = self._build_path()
            if path and len(path) >= 2:
                kind   = self._random_vehicle_kind()
                sprite = self._sprite_for_kind(kind)
                self.vehicles.append(
                    Vehicle(
                        path=path,
                        kind=kind,
                        sprite=sprite,
                        speed=self._speed_for_kind(kind),
                        # Règle de sens / voie : on reste sur la voie droite.
                        # Le décalage latéral dépend du vecteur de direction, donc
                        # ça marche dans les 2 sens sans face-à-face visuel.
                        lane_side=-1,
                    )
                )

    # -----------------------------------------------------------------------
    # Configuration des feux tricolores (Module 4 – Optimisation)
    # -----------------------------------------------------------------------
    def _apply_light_config(self, cfg: dict):
        green_s   = max(8,  int(cfg.get("green_seconds",   18)))
        yellow_s  = max(2,  int(cfg.get("yellow_seconds",   3)))
        all_red_s = max(0,  int(cfg.get("all_red_seconds",  1)))

        self.light_config["green_seconds"]   = green_s
        self.light_config["yellow_seconds"]  = yellow_s
        self.light_config["all_red_seconds"] = all_red_s
        self.light_config["offset_mode"]     = cfg.get("offset_mode", "checkerboard")

        self.light_green_ticks   = self.sim_ticks_per_second * green_s
        self.light_yellow_ticks  = self.sim_ticks_per_second * yellow_s
        self.light_all_red_ticks = self.sim_ticks_per_second * all_red_s

        self.light_phase_offset = {
            n: self._build_light_offset_for_node(n) for n in self.nodes
        }

    def configure_traffic_lights(
        self,
        enabled:          bool | None = None,
        green_seconds:    int  | None = None,
        yellow_seconds:   int  | None = None,
        all_red_seconds:  int  | None = None,
        offset_mode:      str  | None = None,
    ):
        """
        Configure les feux tricolores à la volée.
        Utilisé par le Module 4 (Optimisation) pour tester différents plans.
        """
        if enabled is not None:
            self.enable_traffic_lights = bool(enabled)

        cfg = dict(self.light_config)
        if green_seconds   is not None: cfg["green_seconds"]   = green_seconds
        if yellow_seconds  is not None: cfg["yellow_seconds"]  = yellow_seconds
        if all_red_seconds is not None: cfg["all_red_seconds"] = all_red_seconds
        if offset_mode     is not None: cfg["offset_mode"]     = offset_mode

        self._apply_light_config(cfg)

    def _edge_orientation(self, n1, n2) -> str:
        x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
        x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
        return "EW" if abs(x2 - x1) >= abs(y2 - y1) else "NS"

    def _build_light_offset_for_node(self, node) -> int:
        mode      = self.light_config.get("offset_mode", "checkerboard")
        half_cycle = (
            self.light_green_ticks
            + self.light_yellow_ticks
            + self.light_all_red_ticks
        )
        if mode == "none":
            return 0
        if mode == "hash":
            return half_cycle if (hash(str(node)) % 2 == 1) else 0
        # mode checkerboard (recommandé : synchronisation en damier)
        parts = str(node).split("_")
        if len(parts) == 3 and parts[0] == "I":
            try:
                r, c = int(parts[1]), int(parts[2])
                return half_cycle if ((r + c) % 2 == 1) else 0
            except ValueError:
                pass
        return half_cycle if (hash(str(node)) % 2 == 1) else 0

    def _light_state_for_node(self, node) -> dict:
        """
        Retourne l'état des feux NS et EW pour un nœud donné.
        Cycle : NS vert → NS jaune → rouge total → EW vert → EW jaune → rouge total
        """
        total = 2 * (
            self.light_green_ticks
            + self.light_yellow_ticks
            + self.light_all_red_ticks
        )
        t = (self.tick_count + self.light_phase_offset.get(node, 0)) % total

        ns_green_end  = self.light_green_ticks
        ns_yellow_end = ns_green_end  + self.light_yellow_ticks
        ns_all_red    = ns_yellow_end + self.light_all_red_ticks
        ew_green_end  = ns_all_red    + self.light_green_ticks
        ew_yellow_end = ew_green_end  + self.light_yellow_ticks

        if t < ns_green_end:   return {"NS": "green",  "EW": "red"}
        if t < ns_yellow_end:  return {"NS": "yellow", "EW": "red"}
        if t < ns_all_red:     return {"NS": "red",    "EW": "red"}
        if t < ew_green_end:   return {"NS": "red",    "EW": "green"}
        if t < ew_yellow_end:  return {"NS": "red",    "EW": "yellow"}
        return {"NS": "red", "EW": "red"}

    def _must_stop_for_light(self, n1, n2) -> bool:
        # Règle : les feux ne s'appliquent que sur les intersections signalées.
        if n2 not in self.signal_nodes:
            return False
        orient = self._edge_orientation(n1, n2)
        light  = self._light_state_for_node(n2)
        return light.get(orient, "red") in ("red", "yellow")

    # -----------------------------------------------------------------------
    # Boucle de simulation
    # -----------------------------------------------------------------------
    def reset(self):
        """Réinitialise la simulation (conserve la configuration)."""
        n = len(self.vehicles)
        self.vehicles = []
        self.tick_count = 0
        self.completed_trips = 0
        self.markov.reset()
        self.current_speed_factor = self.markov.speed_factor()
        self.queue_system.reset()
        self._intersection_occupancy.clear()
        self._init_vehicles(n)

    def toggle(self):
        """Bascule l'état lecture / pause."""
        self.running = not self.running

    def step(self):
        """
        Avance la simulation d'un tick :
          1. Mise à jour de la Chaîne de Markov (Module 1)
          2. Mise à jour des files d'attente (Module 2)
          3. Déplacement des véhicules + respect des feux
          4. Contrainte de sécurité inter-véhicules
          5. Passage à l'arête suivante
        """
        if not self.running:
            return

        self.tick_count += 1

        # Snapshot des progress pour éviter des reculs artificiels (jitter)
        for veh in self.vehicles:
            veh.prev_progress = float(veh.progress)

        # 1) Chaîne de Markov – mise à jour périodique de l'état macro
        if self.tick_count % self.markov_update_every == 0:
            self.markov.step()
            self.current_speed_factor = self.markov.speed_factor()

        # Préparation : évènements "physiques" pour les files (arrivées/services)
        queue_arrivals: dict = {}
        queue_services: dict = {}

        # Pré-calcul : qui a besoin d'une réservation pour franchir une intersection ?
        # Pour chaque nœud à feux, on laisse passer au plus un véhicule par tick.
        winners: dict = {}
        queue_gate: dict[int, bool] = {}
        if self.enable_intersection_reservations:
            best_for_node: dict = {}
            for veh in self.vehicles:
                if veh.edge_index >= len(veh.path) - 1:
                    continue
                n1 = veh.path[veh.edge_index]
                n2 = veh.path[veh.edge_index + 1]
                if not self._reservation_applies_to_node(n2):
                    continue

                # Si l'intersection est occupée par un autre véhicule, personne n'entre.
                if self.enable_intersection_occupancy:
                    occ = self._intersection_occupancy.get(n2)
                    if occ is not None and occ != id(veh):
                        continue
                delta = veh.speed * self.current_speed_factor

                if self.enable_traffic_lights and self._must_stop_for_light(n1, n2):
                    continue

                # Le véhicule ne requiert une réservation que s'il va dépasser la ligne d'arrêt.
                if (veh.progress + delta) < self.stop_line_progress:
                    continue

                # Décision de passage liée à la file locale : on l'échantillonne
                # une seule fois par tick et par véhicule, puis on la réutilise.
                allow = True
                if n2 in getattr(self.queue_system, "queues", {}):
                    p_pass = self._queue_pass_probability(n2)
                    allow = (self.rng.random() <= p_pass)
                queue_gate[id(veh)] = allow
                if not allow:
                    continue

                score = float(veh.progress)
                if (n2 not in best_for_node) or (score > best_for_node[n2][0]):
                    best_for_node[n2] = (score, veh)

            winners = {node: pair[1] for node, pair in best_for_node.items()}

        # 2) Déplacement des véhicules + gestion des feux / réservations
        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                # Trajet terminé : on génère un nouveau chemin (variation du flux)
                self.completed_trips += 1
                current_node = veh.path[-1]
                new_path = self._build_path_from(current_node)
                if new_path and len(new_path) >= 2:
                    veh.path       = new_path
                    veh.edge_index = 0
                    veh.progress   = 0.0
                    veh.queued_node = None
                    veh.blocked_last_tick = False
                    if veh.occupied_node is not None:
                        if self._intersection_occupancy.get(veh.occupied_node) == id(veh):
                            self._intersection_occupancy.pop(veh.occupied_node, None)
                        veh.occupied_node = None
                continue

            n1    = veh.path[veh.edge_index]
            n2    = veh.path[veh.edge_index + 1]
            delta = veh.speed * self.current_speed_factor

            # Une fois la ligne d'arrêt franchie, on ne doit plus être bloqué par
            # un feu/priorité/saturation : on finit de traverser le carrefour.
            inside_intersection = veh.progress > (self.stop_line_progress + self.intersection_entry_eps)

            # Auto-réparation : si un véhicule est déjà "dans" le carrefour mais n'a
            # pas pris le verrou (cas rare), on l'associe à l'occupation.
            if (
                self.enable_intersection_occupancy
                and self._reservation_applies_to_node(n2)
                and inside_intersection
                and veh.occupied_node is None
            ):
                occ = self._intersection_occupancy.get(n2)
                if occ is None or occ == id(veh):
                    self._intersection_occupancy[n2] = id(veh)
                    veh.occupied_node = n2

            if inside_intersection:
                veh.progress += delta
                veh.blocked_last_tick = False
                continue

            must_stop_light = bool(
                self.enable_traffic_lights and self._must_stop_for_light(n1, n2)
            )

            must_stop_reservation = False
            if (
                self.enable_intersection_reservations
                and self._reservation_applies_to_node(n2)
                and ((veh.progress + delta) >= self.stop_line_progress)
            ):
                winner = winners.get(n2)
                must_stop_reservation = (winner is not None and winner is not veh)

            # Occupation : si un autre véhicule est déjà dans le carrefour, on s'arrête.
            must_stop_occupied = False
            if (
                self.enable_intersection_occupancy
                and self._reservation_applies_to_node(n2)
                and ((veh.progress + delta) >= self.stop_line_progress)
            ):
                occ = self._intersection_occupancy.get(n2)
                must_stop_occupied = (occ is not None and occ != id(veh))

            # Contrainte "physique" liée à la file d'attente : même si vert + gagnant,
            # on peut être bloqué (intersection saturée).
            must_stop_queue = False
            if (
                (n2 in getattr(self.queue_system, "queues", {}))
                and ((veh.progress + delta) >= self.stop_line_progress)
                and (not must_stop_light)
                and (not must_stop_reservation)
                and (not must_stop_occupied)
            ):
                allow = queue_gate.get(id(veh), True)
                must_stop_queue = (not allow)

            blocked = must_stop_light or must_stop_reservation or must_stop_occupied or must_stop_queue

            if blocked:
                old_progress = veh.progress
                veh.progress = min(veh.progress + delta, self.stop_line_progress)

                if veh.progress <= old_progress + 1e-9:
                    veh.wait_ticks += 1

                at_stop_line = veh.progress >= self.stop_line_progress - 1e-6
                if at_stop_line and not veh.blocked_last_tick:
                    veh.stops += 1
                if at_stop_line:
                    if veh.queued_node != n2:
                        queue_arrivals[n2] = queue_arrivals.get(n2, 0) + 1
                        veh.queued_node = n2

            else:
                prev_progress = veh.progress
                veh.progress += delta

                # Si le véhicule vient d'entrer dans la zone d'intersection, il prend le verrou.
                if (
                    self.enable_intersection_occupancy
                    and self._reservation_applies_to_node(n2)
                    and (prev_progress <= self.stop_line_progress + self.intersection_entry_eps)
                    and (veh.progress > self.stop_line_progress + self.intersection_entry_eps)
                ):
                    self._intersection_occupancy[n2] = id(veh)
                    veh.occupied_node = n2

            veh.blocked_last_tick = blocked

        # 4) Contrainte de sécurité – distance minimale entre véhicules
        #    sur la même arête et dans la même file
        groups: dict = {}
        for veh in self.vehicles:
            if veh.edge_index >= len(veh.path) - 1:
                continue
            n1  = veh.path[veh.edge_index]
            n2  = veh.path[veh.edge_index + 1]
            key = (n1, n2, veh.lane_side)
            groups.setdefault(key, []).append(veh)

        for vehs in groups.values():
            vehs.sort(key=lambda v: v.progress, reverse=True)
            for idx in range(1, len(vehs)):
                leader    = vehs[idx - 1]
                follower  = vehs[idx]
                max_prog  = max(0.0, leader.progress - self.min_progress_gap)
                if follower.progress > max_prog:
                    # Évite de "reculer" visuellement un véhicule déjà arrêté.
                    # On applique le clamp seulement s'il a avancé ce tick.
                    if follower.progress > follower.prev_progress + 1e-12:
                        follower.progress = max_prog
                        follower.wait_ticks += 1

        # 5) Passage à l'arête suivante quand progress ≥ 1
        for veh in self.vehicles:
            while veh.progress >= 1.0 and veh.edge_index < len(veh.path) - 1:
                reached_node = veh.path[veh.edge_index + 1]
                if veh.queued_node == reached_node:
                    queue_services[reached_node] = queue_services.get(reached_node, 0) + 1
                    veh.queued_node = None

                # Libère l'occupation une fois l'intersection franchie (arrivée au nœud).
                if veh.occupied_node == reached_node:
                    if self._intersection_occupancy.get(reached_node) == id(veh):
                        self._intersection_occupancy.pop(reached_node, None)
                    veh.occupied_node = None
                veh.progress  -= 1.0
                veh.edge_index += 1

        # 3) Files d'attente – évolution stochastique Markov + couplage aux blocages réels
        self.queue_system.step(self.markov.state, arrivals=queue_arrivals, services=queue_services)

    # -----------------------------------------------------------------------
    # Accès aux données (IHM + analytics)
    # -----------------------------------------------------------------------
    def traffic_state(self) -> str:
        """État macro courant du trafic (FLUIDE / RALENTI / BOUCHON)."""
        return self.markov.state

    def avg_speed(self) -> float:
        """Vitesse moyenne des véhicules (somme des vitesses de base)."""
        if not self.vehicles:
            return 0.0
        return sum(v.speed for v in self.vehicles) / len(self.vehicles)

    def avg_queue(self) -> float:
        """File d'attente moyenne sur toutes les intersections."""
        return self.queue_system.avg_queue()

    def max_queue(self) -> int:
        """File d'attente maximale observée."""
        return self.queue_system.max_queue()

    def queue_observation(self) -> str:
        """Phénomène observé : SATURATION FAIBLE / ATTENTE / CONGESTION."""
        return self.queue_system.observation()

    def queue_snapshot(self) -> dict:
        """Instantané des files d'attente par nœud."""
        return self.queue_system.snapshot()

    def throughput_per_1000_ticks(self) -> float:
        """Débit : nombre de trajets complétés pour 1000 ticks."""
        if self.tick_count <= 0:
            return 0.0
        return (self.completed_trips / self.tick_count) * 1000.0

    def traffic_lights_snapshot(self) -> dict:
        """État des feux tricolores pour les intersections signalées."""
        return {node: self._light_state_for_node(node) for node in self.signal_nodes}

    # -----------------------------------------------------------------------
    # Positions des véhicules (rendu graphique)
    # -----------------------------------------------------------------------
    def vehicle_positions(self) -> list:
        positions = []
        for kind_list in self.vehicle_positions_by_type().values():
            positions.extend(kind_list)
        return positions

    def vehicle_positions_by_type(self) -> dict:
        by_type: dict = {"car": [], "suv": [], "truck": [], "bus": []}
        for veh in self.vehicles:
            x, y = self._vehicle_world_pos(veh)
            by_type.setdefault(veh.kind, []).append((x, y))
        return by_type

    def vehicle_render_data(self) -> list:
        """
        Retourne la liste complète des données de rendu pour chaque véhicule :
        position monde (x, y), kind, sprite, lane_side.
        """
        data = []
        for veh in self.vehicles:
            x, y = self._vehicle_world_pos(veh)
            data.append({
                "x":         x,
                "y":         y,
                "kind":      veh.kind,
                "sprite":    veh.sprite,
                "lane_side": veh.lane_side,
            })
        return data

    def _vehicle_world_pos(self, veh: Vehicle) -> tuple[float, float]:
        """Calcule la position monde interpolée d'un véhicule."""
        if veh.edge_index >= len(veh.path) - 1:
            node = veh.path[-1]
            return float(self.G.nodes[node]["x"]), float(self.G.nodes[node]["y"])
        n1 = veh.path[veh.edge_index]
        n2 = veh.path[veh.edge_index + 1]
        x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
        x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
        t = veh.progress
        return x1 + t * (x2 - x1), y1 + t * (y2 - y1)