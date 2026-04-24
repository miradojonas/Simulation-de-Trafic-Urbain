"""
Module 4 – Optimisation des feux tricolores
Objectif : améliorer la circulation en trouvant le meilleur plan de feux.

Méthode : recherche exhaustive sur grille (grid search) des paramètres :
  - durée de la phase verte  (green_seconds)
  - durée de la phase jaune  (yellow_seconds)
  - durée du rouge total     (all_red_seconds)
  - mode de décalage         (offset_mode)

La fonction de coût à minimiser est :
    score = 1.0 × avg_queue + 0.002 × wait_total − 0.5 × throughput_per_1000

Un score faible correspond à moins de files d'attente, moins d'attente
et un meilleur débit – soit une circulation améliorée.
"""

from statistics import mean
from simulation import TrafficSimulation


# ---------------------------------------------------------------------------
# Évaluation d'un plan de feux
# ---------------------------------------------------------------------------
def evaluate_light_plan(
    G,
    plan:       dict,
    runs:       int   = 8,
    n_ticks:    int   = 500,
    n_vehicles: int   = 30,
    base_seed:  int   = 2000,
) -> dict:
    """
    Évalue un plan de feux tricolores sur `runs` simulations indépendantes.

    Paramètres
    ----------
    G          : graphe routier
    plan       : dict {green_seconds, yellow_seconds, all_red_seconds, offset_mode}
    runs       : nombre de runs d'évaluation
    n_ticks    : durée de chaque run
    n_vehicles : nombre de véhicules par run
    base_seed  : seed de base (seed_i = base_seed + i)

    Retour
    ------
    dict avec le plan, le score moyen et les métriques détaillées
    """
    scores  = []
    details = []

    for i in range(runs):
        sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=base_seed + i)
        # Application du plan de feux à tester
        sim.configure_traffic_lights(
            enabled=True,
            green_seconds=plan["green_seconds"],
            yellow_seconds=plan["yellow_seconds"],
            all_red_seconds=plan["all_red_seconds"],
            offset_mode=plan.get("offset_mode", "checkerboard"),
        )
        for _ in range(n_ticks):
            sim.step()

        avg_q  = sim.avg_queue()
        wait   = sum(v.wait_ticks for v in sim.vehicles)
        flow   = sim.throughput_per_1000_ticks()

        # Fonction de coût (à minimiser)
        # - pénalité pour les files d'attente longues
        # - pénalité pour le temps d'attente cumulé
        # - récompense pour le débit
        score = 1.0 * avg_q + 0.002 * wait - 0.5 * flow

        scores.append(score)
        details.append({
            "avg_queue":       avg_q,
            "max_queue":       sim.max_queue(),
            "wait_total":      wait,
            "throughput_1000": flow,
            "obs":             sim.queue_observation(),
            "state":           sim.traffic_state(),
        })

    return {
        "plan":                plan,
        "score_mean":          mean(scores),
        "score_min":           min(scores),
        "score_max":           max(scores),
        "avg_queue_mean":      mean(d["avg_queue"]       for d in details),
        "max_queue_mean":      mean(d["max_queue"]       for d in details),
        "wait_total_mean":     mean(d["wait_total"]      for d in details),
        "throughput_1000_mean":mean(d["throughput_1000"] for d in details),
        "details":             details,
    }


def evaluate_baseline_no_lights(
    G,
    runs:       int   = 8,
    n_ticks:    int   = 500,
    n_vehicles: int   = 30,
    base_seed:  int   = 2000,
) -> dict:
    """Évalue une baseline sans feux tricolores sur plusieurs runs."""
    details = []
    for i in range(runs):
        sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=base_seed + i)
        sim.configure_traffic_lights(enabled=False)
        for _ in range(n_ticks):
            sim.step()

        avg_q = sim.avg_queue()
        wait = sum(v.wait_ticks for v in sim.vehicles)
        flow = sim.throughput_per_1000_ticks()
        details.append({
            "avg_queue":       avg_q,
            "max_queue":       sim.max_queue(),
            "wait_total":      wait,
            "throughput_1000": flow,
            "obs":             sim.queue_observation(),
            "state":           sim.traffic_state(),
        })

    return {
        "avg_queue_mean":       mean(d["avg_queue"] for d in details),
        "max_queue_mean":       mean(d["max_queue"] for d in details),
        "wait_total_mean":      mean(d["wait_total"] for d in details),
        "throughput_1000_mean": mean(d["throughput_1000"] for d in details),
        "details":              details,
    }


# ---------------------------------------------------------------------------
# Recherche sur grille (grid search)
# ---------------------------------------------------------------------------
def optimize_lights_grid(
    G,
    green_candidates:   tuple = (12, 15, 18, 22),
    yellow_candidates:  tuple = (2, 3, 4),
    all_red_candidates: tuple = (0, 1, 2),
    offset_modes:       tuple = ("checkerboard", "hash"),
    runs:       int = 6,
    n_ticks:    int = 500,
    n_vehicles: int = 30,
) -> tuple:
    """
    Recherche exhaustive du meilleur plan de feux par grid search.

    Teste toutes les combinaisons de (green, yellow, all_red, offset_mode)
    et retourne le plan minimisant la fonction de coût.

    Retour
    ------
    (best_result, all_results_sorted)
      best_result        : dict du meilleur plan évalué
      all_results_sorted : liste triée par score croissant
    """
    best        = None
    all_results = []

    total = (
        len(green_candidates) *
        len(yellow_candidates) *
        len(all_red_candidates) *
        len(offset_modes)
    )
    evaluated = 0

    for g in green_candidates:
        for y in yellow_candidates:
            for r in all_red_candidates:
                for mode in offset_modes:
                    plan = {
                        "green_seconds":   g,
                        "yellow_seconds":  y,
                        "all_red_seconds": r,
                        "offset_mode":     mode,
                    }
                    res = evaluate_light_plan(
                        G,
                        plan=plan,
                        runs=runs,
                        n_ticks=n_ticks,
                        n_vehicles=n_vehicles,
                    )
                    all_results.append(res)
                    evaluated += 1

                    # Mise à jour du meilleur plan
                    if best is None or res["score_mean"] < best["score_mean"]:
                        best = res

    return best, sorted(all_results, key=lambda x: x["score_mean"])