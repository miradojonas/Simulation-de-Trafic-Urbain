"""
Point d'entrée principal de la simulation de trafic urbain.

Lance l'interface graphique PySide6 (ui_v1.py – TrafficV1Window)
avec un graphe de ville synthétique en grille.

Architecture du projet :
  Données → Markov (M1) → Files d'attente (M2) → Monte Carlo (M3)
           → Optimisation (M4) → IHM (PySide6)
"""

import sys
import networkx as nx
from PySide6.QtWidgets import QApplication

from simulation import TrafficSimulation
from ui_v1 import TrafficV1Window


# ---------------------------------------------------------------------------
# Génération du graphe de la ville synthétique
# ---------------------------------------------------------------------------
def create_city_grid_map(
    rows:    int   = 6,
    cols:    int   = 6,
    spacing: float = 120.0,
) -> nx.MultiDiGraph:
    """
    Crée un graphe routier en grille (rows × cols intersections).

    Paramètres
    ----------
    rows    : nombre de lignes d'intersections
    cols    : nombre de colonnes d'intersections
    spacing : espacement en pixels entre deux intersections adjacentes

    Retour
    ------
    NetworkX MultiDiGraph avec attributs x, y, length, speed_kph, travel_time
    """
    rows    = max(4, int(rows))
    cols    = max(4, int(cols))
    spacing = max(20.0, float(spacing))

    G = nx.MultiDiGraph()
    G.graph["rows"] = rows
    G.graph["cols"] = cols

    # ── Nœuds : coordonnées écran directes ──────────────────────────────
    for r in range(rows + 1):
        for c in range(cols + 1):
            node_id = f"I_{r}_{c}"
            G.add_node(node_id, x=float(c * spacing), y=float(r * spacing))

    # ── Arêtes horizontales (EW) ─────────────────────────────────────────
    for r in range(rows + 1):
        for c in range(cols):
            u = f"I_{r}_{c}"
            v = f"I_{r}_{c + 1}"
            # Axes principaux (r % 3 == 0) plus rapides
            speed = 45.0 if (r % 3 == 0) else 30.0
            attrs = {
                "length":      spacing,
                "speed_kph":   speed,
                "travel_time": spacing / speed,
            }
            G.add_edge(u, v, **attrs)
            G.add_edge(v, u, **attrs)

    # ── Arêtes verticales (NS) ────────────────────────────────────────────
    for c in range(cols + 1):
        for r in range(rows):
            u = f"I_{r}_{c}"
            v = f"I_{r + 1}_{c}"
            speed = 45.0 if (c % 4 == 0) else 30.0
            attrs = {
                "length":      spacing,
                "speed_kph":   speed,
                "travel_time": spacing / speed,
            }
            G.add_edge(u, v, **attrs)
            G.add_edge(v, u, **attrs)

    return G


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
def main():
    """Lance l'application de simulation de trafic urbain."""
    app = QApplication(sys.argv)

    # Graphe de la ville synthétique (6×6, espacement 100 px)
    G   = create_city_grid_map(rows=5, cols=5, spacing=100.0)

    # Moteur de simulation (intègre Markov + Files d'attente)
    sim = TrafficSimulation(G, n_vehicles=30, seed=123)

    # Interface graphique principale (IHM PySide6 – Module IHM)
    window = TrafficV1Window(G, sim)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()