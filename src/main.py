import sys
from PySide6.QtWidgets import QApplication
from simulation import TrafficSimulation
import networkx as nx
from ui_v1 import TrafficV1Window


def create_city_grid_map(rows: int = 6, cols: int = 6, spacing: float = 120.0):
    rows = max(4, int(rows))
    cols = max(4, int(cols))
    spacing = max(20.0, float(spacing))

    G = nx.MultiDiGraph()
    G.graph["rows"] = rows
    G.graph["cols"] = cols

    # Noeuds avec coordonnées écran directes
    for r in range(rows + 1):
        for c in range(cols + 1):
            node_id = f"I_{r}_{c}"
            x = c * spacing
            y = r * spacing
            G.add_node(node_id, x=x, y=y)

    # Arêtes bidirectionnelles
    for r in range(rows + 1):
        for c in range(cols):
            u = f"I_{r}_{c}"
            v = f"I_{r}_{c + 1}"
            speed = 45.0 if (r % 3 == 0) else 30.0
            attrs = {"length": spacing, "speed_kph": speed, "travel_time": spacing / speed}
            G.add_edge(u, v, **attrs)
            G.add_edge(v, u, **attrs)

    for c in range(cols + 1):
        for r in range(rows):
            u = f"I_{r}_{c}"
            v = f"I_{r + 1}_{c}"
            speed = 45.0 if (c % 4 == 0) else 30.0
            attrs = {"length": spacing, "speed_kph": speed, "travel_time": spacing / speed}
            G.add_edge(u, v, **attrs)
            G.add_edge(v, u, **attrs)

    return G


def main():
    """Entrée principale en mode headless (sans interface graphique)."""
    app = QApplication(sys.argv)

    G = create_city_grid_map(rows=6, cols=6, spacing=1.0)
    sim = TrafficSimulation(G, n_vehicles=10, seed=123)

    window = TrafficV1Window(G, sim)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
