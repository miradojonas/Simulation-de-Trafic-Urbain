from simulation import TrafficSimulation
import networkx as nx


def create_city_grid_map(rows: int = 6, cols: int = 6, spacing: float = 1.0):
    rows = max(4, int(rows))
    cols = max(4, int(cols))
    spacing = max(0.2, float(spacing))

    G = nx.MultiDiGraph()
    G.graph["map_type"] = "city_grid"
    G.graph["rows"] = rows
    G.graph["cols"] = cols

    for r in range(rows + 1):
        for c in range(cols + 1):
            node_id = f"I_{r}_{c}"
            G.add_node(node_id, x=c * spacing, y=r * spacing)

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
    G = create_city_grid_map(rows=6, cols=6, spacing=1.0)
    sim = TrafficSimulation(G, n_vehicles=20, seed=123)

    n_ticks = 300
    for _ in range(n_ticks):
        sim.step()

    print("Simulation headless terminée")
    print(f"tick={sim.tick_count}")
    print(f"vehicles={len(sim.vehicles)}")
    print(f"state={sim.traffic_state()}")
    print(f"avg_speed={sim.avg_speed():.4f}")
    print(f"avg_q={sim.avg_queue():.2f}")
    print(f"max_q={sim.max_queue()}")


if __name__ == "__main__":
    main()
