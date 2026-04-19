"""
Module 3: Executer un ou plusieurs scenarios
Resumer metrique pour comparaison
"""

from statistics import mean
from simulation import TrafficSimulation

def run_scenario(G, n_ticks=400, n_vehicles=10, seed=123):
    """Lance un scénario et retourne les métriques finales."""
    sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=seed)
    for _ in range(n_ticks):
        sim.step()

    return {
        # Vitesse moyenne des véhicules (pas la file d'attente)
        "avg_speed": sim.avg_speed(),
        "avg_queue": sim.avg_queue() if hasattr(sim, "avg_queue") else 0.0,
        "max_queue": sim.max_queue() if hasattr(sim, "max_queue") else 0,
        "state": sim.traffic_state() if hasattr(sim, "traffic_state") else "N/A",
    }

def monte_carlo(G, runs=20, n_ticks=400, n_vehicles=10):
    """Exécute plusieurs scénarios indépendants et calcule des statistiques."""
    # Exécuter N runs avec des seeds différentes
    results = [
        run_scenario(
            G,
            n_ticks=n_ticks,
            n_vehicles=n_vehicles,
            seed=1000 + i  # seed différente par run
        )
        for i in range(runs)
    ]

    # 2) Extraire les séries métriques
    avg_speeds = [r["avg_speed"] for r in results]
    avg_queues = [r["avg_queue"] for r in results]
    max_queues = [r["max_queue"] for r in results]

    # 3) Compter les états finaux observés
    state_counts = {}
    for r in results:
        st = r["state"]
        state_counts[st] = state_counts.get(st, 0) + 1

    # 4) Retourner un résumé propre
    return {
        "runs": runs,
        "avg_speed_mean": mean(avg_speeds),
        "avg_speed_min": min(avg_speeds),
        "avg_speed_max": max(avg_speeds),
        "avg_queue_mean": mean(avg_queues),
        "avg_queue_min": min(avg_queues),
        "avg_queue_max": max(avg_queues),
        "max_queue_mean": mean(max_queues),
        "max_queue_min": min(max_queues),
        "max_queue_max": max(max_queues),
        "state_counts": state_counts,
    }