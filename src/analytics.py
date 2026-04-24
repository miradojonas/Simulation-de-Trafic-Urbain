"""
Module 3 – Simulation Monte Carlo
Exécute un ou plusieurs scénarios aléatoires indépendants et résume
les métriques pour comparaison et analyse.

Conformément au projet :
  - Génération aléatoire du trafic (seeds différentes par run)
  - Simulation de scénarios : arrivée des véhicules, variation du flux
  - Indicateurs résumés : vitesse, files d'attente, états Markov, débits
"""

from statistics import mean
from simulation import TrafficSimulation
from optimization import optimize_lights_grid


# ---------------------------------------------------------------------------
# Exécution d'un scénario unique
# ---------------------------------------------------------------------------
def run_scenario(G, n_ticks: int = 400, n_vehicles: int = 10, seed: int = 123) -> dict:
    """
    Lance un scénario unique et retourne les métriques finales.

    Paramètres
    ----------
    G          : graphe routier (NetworkX)
    n_ticks    : durée de la simulation en ticks
    n_vehicles : nombre de véhicules générés (arrivée aléatoire)
    seed       : graine pour la reproductibilité

    Retour
    ------
    dict avec : avg_speed, avg_queue, max_queue, state, obs,
                stops_total, wait_total, throughput
    """
    sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=seed)
    for _ in range(n_ticks):
        sim.step()

    has_vehicles = len(sim.vehicles) > 0
    return {
        "seed":        int(seed),
        "n_ticks":     int(n_ticks),
        "n_vehicles":  int(n_vehicles),
        "avg_speed":   sim.avg_speed(),
        "avg_queue":   sim.avg_queue(),
        "max_queue":   sim.max_queue(),
        "state":       sim.traffic_state(),
        "obs":         sim.queue_observation(),
        "stops_total": sum(v.stops       for v in sim.vehicles) if has_vehicles else 0,
        "wait_total":  sum(v.wait_ticks  for v in sim.vehicles) if has_vehicles else 0,
        "throughput":  sim.throughput_per_1000_ticks(),
    }


# ---------------------------------------------------------------------------
# Monte Carlo – version courte (appelée depuis l'IHM)
# ---------------------------------------------------------------------------
def monte_carlo(G, runs: int = 20, n_ticks: int = 400, n_vehicles: int = 10) -> dict:
    """
    Exécute `runs` scénarios indépendants (seeds 1000, 1001, …) et
    retourne un résumé statistique compact.

    Utilisée par le bouton « Monte Carlo » de l'interface graphique.
    """
    results = [
        run_scenario(G, n_ticks=n_ticks, n_vehicles=n_vehicles, seed=1000 + i)
        for i in range(runs)
    ]
    summary = _summarize(results, runs)
    summary["details"] = results
    return summary


# ---------------------------------------------------------------------------
# Monte Carlo – version complète avec métriques étendues
# ---------------------------------------------------------------------------
def run_monte_carlo(
    G,
    runs:       int = 30,
    n_ticks:    int = 400,
    n_vehicles: int = 30,
    base_seed:  int = 1000,
) -> dict:
    """
    Exécute `runs` scénarios indépendants avec des seeds différentes.
    Retourne un résumé étendu incluant stops, wait_total et throughput.

    Paramètres
    ----------
    G          : graphe routier
    runs       : nombre de runs Monte Carlo
    n_ticks    : durée de chaque run
    n_vehicles : nombre de véhicules par run (variation du flux)
    base_seed  : seed du premier run ; les suivants utilisent base_seed + i
    """
    results = [
        run_scenario(G, n_ticks=n_ticks, n_vehicles=n_vehicles, seed=base_seed + i)
        for i in range(runs)
    ]
    summary = _summarize(results, runs)
    summary["details"] = results
    return summary


# ---------------------------------------------------------------------------
# Comparaison baseline (sans feux) vs plan optimisé
# ---------------------------------------------------------------------------
def compare_baseline_vs_optimized(
    G,
    runs:       int = 10,
    n_ticks:    int = 500,
    n_vehicles: int = 30,
) -> dict:
    """
    Compare la simulation sans feux (baseline) au meilleur plan de feux
    trouvé par l'optimisation (Module 4).

    Retour
    ------
    dict {
        "baseline_no_lights" : résumé Monte Carlo sans feux,
        "best_light_plan"    : meilleur plan selon optimize_lights_grid,
    }
    """
    # Baseline – simulation sans feux tricolores
    baseline = run_monte_carlo(
        G, runs=runs, n_ticks=n_ticks, n_vehicles=n_vehicles, base_seed=1000
    )

    # Recherche du meilleur plan de feux (Module 4 – Optimisation)
    best, _ = optimize_lights_grid(
        G,
        runs=max(4, runs // 2),
        n_ticks=n_ticks,
        n_vehicles=n_vehicles,
    )

    return {
        "baseline_no_lights": baseline,
        "best_light_plan":    best,
    }


# ---------------------------------------------------------------------------
# Fonction interne de résumé statistique
# ---------------------------------------------------------------------------
def _summarize(results: list, runs: int) -> dict:
    """
    Construit le dictionnaire de résumé statistique à partir d'une liste
    de résultats de scénarios.
    """
    avg_speeds    = [r["avg_speed"]   for r in results]
    avg_queues    = [r["avg_queue"]   for r in results]
    max_queues    = [r["max_queue"]   for r in results]
    stops_totals  = [r["stops_total"] for r in results]
    wait_totals   = [r["wait_total"]  for r in results]
    throughputs   = [r["throughput"]  for r in results]

    # Décompte des états finaux Markov observés sur l'ensemble des runs
    state_counts: dict = {}
    for r in results:
        st = r["state"]
        state_counts[st] = state_counts.get(st, 0) + 1

    # Décompte des phénomènes d'écoulement observés (Module 2)
    obs_counts: dict = {}
    for r in results:
        ob = r.get("obs", "N/A")
        obs_counts[ob] = obs_counts.get(ob, 0) + 1

    return {
        "runs": runs,
        # Vitesse moyenne des véhicules
        "avg_speed_mean": mean(avg_speeds),
        "avg_speed_min":  min(avg_speeds),
        "avg_speed_max":  max(avg_speeds),
        # File d'attente moyenne
        "avg_queue_mean": mean(avg_queues),
        "avg_queue_min":  min(avg_queues),
        "avg_queue_max":  max(avg_queues),
        # File d'attente maximale
        "max_queue_mean": mean(max_queues),
        "max_queue_min":  min(max_queues),
        "max_queue_max":  max(max_queues),
        # Nombre d'arrêts cumulés
        "stops_total_mean": mean(stops_totals),
        "stops_total_min":  min(stops_totals),
        "stops_total_max":  max(stops_totals),
        # Temps d'attente cumulé
        "wait_total_mean": mean(wait_totals),
        "wait_total_min":  min(wait_totals),
        "wait_total_max":  max(wait_totals),
        # Débit (trajets / 1000 ticks)
        "throughput_mean": mean(throughputs),
        "throughput_min":  min(throughputs),
        "throughput_max":  max(throughputs),
        # Distribution des états Markov finaux
        "state_counts": state_counts,
        # Distribution des phénomènes d'écoulement (Module 2)
        "obs_counts": obs_counts,
    }