"""
Module 3: Executer un ou plusieurs scenarios
Resumer metrique pour comparaison
"""

from statistics import mean
from simulation import TrafficSimulation
from optimization import optimize_lights_grid

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

def run_monte_carlo(G, runs=30, n_ticks=400, n_vehicles=30, base_seed=1000):
    results = []
    for i in range(runs):
        sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=base_seed + i)
        for _ in range(n_ticks):
            sim.step()
        has_vehicles = len(sim.vehicles) > 0
        results.append({
            "avg_speed": sim.avg_speed(),
            "avg_queue": sim.avg_queue(),
            "max_queue": sim.max_queue(),
            "state": sim.traffic_state(),
            "stops_total": sum(v.stops for v in sim.vehicles) if has_vehicles else 0,
            "wait_total": sum(v.wait_ticks for v in sim.vehicles) if has_vehicles else 0,
        })

    avg_speeds = [r["avg_speed"] for r in results]
    avg_queues = [r["avg_queue"] for r in results]
    max_queues = [r["max_queue"] for r in results]
    stops_totals = [r["stops_total"] for r in results]
    wait_totals = [r["wait_total"] for r in results]

    state_counts = {}
    for r in results:
        st = r["state"]
        state_counts[st] = state_counts.get(st, 0) + 1

    summary = {
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
        "stops_total_mean": mean(stops_totals),
        "stops_total_min": min(stops_totals),
        "stops_total_max": max(stops_totals),
        "wait_total_mean": mean(wait_totals),
        "wait_total_min": min(wait_totals),
        "wait_total_max": max(wait_totals),
        "state_counts": state_counts,
    }
    return summary

def compare_baseline_vs_optimized(G, runs=10, n_ticks=500, n_vehicles=30):
    # Baseline sans feux
    baseline = run_monte_carlo(
        G, runs=runs, n_ticks=n_ticks, n_vehicles=n_vehicles, base_seed=1000
    )

    # Recherche du meilleur plan de feux
    best, _ = optimize_lights_grid(
        G,
        runs=max(4, runs // 2),
        n_ticks=n_ticks,
        n_vehicles=n_vehicles,
    )

    return {
        "baseline_no_lights": baseline,
        "best_light_plan": best,
    }