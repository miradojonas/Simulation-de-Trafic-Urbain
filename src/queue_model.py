"""
Module 2 – Files d'attente aux intersections
Modélise l'accumulation de véhicules aux intersections (feux, priorités,
rond-points). Trois phénomènes observés, conformément au projet :

  - SATURATION FAIBLE : files courtes, écoulement normal
  - ATTENTE           : files moyennes, dégradation perceptible
  - CONGESTION        : files longues, blocage généralisé

Le modèle est un système M/M/1 discret simplifié :
  - arrivée aléatoire à chaque tick selon la probabilité `arrival`
  - service (départ) aléatoire selon la probabilité `service`
  - les deux probabilités sont modulées par l'état Markov du trafic
"""

from dataclasses import dataclass
import random

# Seuils qualitatifs pour l'observation de l'état d'écoulement
CONGESTION_SEUIL_AVG = 4.0   # file moyenne ≥ 4  → CONGESTION
CONGESTION_SEUIL_MAX = 8     # file max    ≥ 8  → CONGESTION
ATTENTE_SEUIL_AVG    = 2.0   # file moyenne ≥ 2  → ATTENTE
ATTENTE_SEUIL_MAX    = 4     # file max    ≥ 4  → ATTENTE

# Libellés des phénomènes (utilisés par l'IHM et les rapports)
PHENOMENE_CONGESTION        = "CONGESTION"
PHENOMENE_ATTENTE           = "ATTENTE"
PHENOMENE_SATURATION_FAIBLE = "SATURATION FAIBLE"


@dataclass
class QueueSystem:
    """
    Système de files d'attente aux intersections.

    Attributs
    ---------
    seed          : graine aléatoire
    arrival_base  : probabilité de base d'arrivée d'un véhicule par tick
    service_base  : probabilité de base de service (départ) par tick
    queues        : dict {node_id -> longueur de file}
    """
    seed: int = 123
    arrival_base: float = 0.35   # Prob. d'arrivée de base
    service_base: float = 0.40   # Prob. de service de base

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.queues: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def init_intersections(self, node_ids: list):
        """
        Crée une file vide pour chaque intersection listée.
        Les intersections modélisent feux rouges, priorités, rond-points.
        """
        self.queues = {nid: 0 for nid in node_ids}

    # ------------------------------------------------------------------
    # Évolution
    # ------------------------------------------------------------------
    def step(self, markov_state: str, arrivals: dict | None = None, services: dict | None = None):
        """
        Avance d'un tick toutes les files.

        Les probabilités d'arrivée et de service sont modulées selon
        l'état macro du trafic (FLUIDE / RALENTI / BOUCHON).

        Paramètres
        ----------
        markov_state : état courant de la chaîne de Markov
        """
        has_external = bool(arrivals) or bool(services)

        # Mode "couplé" : quand on reçoit des événements réels de la simulation
        # (arrivées à la ligne d'arrêt / franchissements), on évite de rajouter
        # en plus un bruit stochastique M/M/1, sinon les files explosent.
        if not has_external:
            if markov_state == "FLUIDE":
                # Trafic fluide : peu d'arrivées, service rapide
                arrival = self.arrival_base * 0.8
                service = self.service_base * 1.2
            elif markov_state == "RALENTI":
                # Trafic ralenti : arrivées normales, service légèrement dégradé
                arrival = self.arrival_base * 1.0
                service = self.service_base * 0.9
            else:  # BOUCHON
                # Congestion : beaucoup d'arrivées, service très lent
                arrival = self.arrival_base * 1.2
                service = self.service_base * 0.6

            for nid in self.queues:
                # Phase d'arrivée : un véhicule peut rejoindre la file
                if self.rng.random() < arrival:
                    self.queues[nid] += 1
                # Phase de service : un véhicule peut quitter la file
                if self.queues[nid] > 0 and self.rng.random() < service:
                    self.queues[nid] -= 1

        # Couplage optionnel avec la simulation : appliquer des deltas externes.
        if arrivals:
            for nid, k in arrivals.items():
                if nid in self.queues and k:
                    self.queues[nid] += max(0, int(k))
        if services:
            for nid, k in services.items():
                if nid in self.queues and k:
                    self.queues[nid] = max(0, self.queues[nid] - max(0, int(k)))

    # ------------------------------------------------------------------
    # Métriques
    # ------------------------------------------------------------------
    def avg_queue(self) -> float:
        """Longueur moyenne des files sur toutes les intersections."""
        if not self.queues:
            return 0.0
        return sum(self.queues.values()) / len(self.queues)

    def max_queue(self) -> int:
        """Longueur maximale observée sur toutes les intersections."""
        return max(self.queues.values()) if self.queues else 0

    def observation(self) -> str:
        """
        Retourne le phénomène qualificatif observé selon les seuils :
          CONGESTION        : saturation critique
          ATTENTE           : dégradation perceptible
          SATURATION FAIBLE : écoulement quasi-normal
        """
        avg = self.avg_queue()
        mx  = self.max_queue()
        if mx >= CONGESTION_SEUIL_MAX or avg >= CONGESTION_SEUIL_AVG:
            return PHENOMENE_CONGESTION
        if mx >= ATTENTE_SEUIL_MAX or avg >= ATTENTE_SEUIL_AVG:
            return PHENOMENE_ATTENTE
        return PHENOMENE_SATURATION_FAIBLE

    def snapshot(self) -> dict:
        """Retourne une copie de l'état courant des files."""
        return dict(self.queues)

    def reset(self):
        """Vide toutes les files (conserve les intersections initialisées)."""
        for nid in self.queues:
            self.queues[nid] = 0
        self.rng = random.Random(self.seed)