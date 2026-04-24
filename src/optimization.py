from statistics import mean

from simulation import TrafficSimulation


def evaluate_light_plan(
    G,
    plan: dict,
    runs: int = 8,
    n_ticks: int = 500,
    n_vehicles: int = 30,
    base_seed: int = 2000,
):
    scores = []
    details = []

    for i in range(runs):
        sim = TrafficSimulation(G, n_vehicles=n_vehicles, seed=base_seed + i)
        sim.configure_traffic_lights(
            enabled=True,
            green_seconds=plan["green_seconds"],
            yellow_seconds=plan["yellow_seconds"],
            all_red_seconds=plan["all_red_seconds"],
            offset_mode=plan.get("offset_mode", "checkerboard"),
        )

        for _ in range(n_ticks):
            sim.step()

        avg_q = sim.avg_queue()
        wait = sum(v.wait_ticks for v in sim.vehicles)
        flow = sim.throughput_per_1000_ticks()

        # Fonction coût (à minimiser)
        score = 1.0 * avg_q + 0.002 * wait - 0.5 * flow
        scores.append(score)

        details.append({
            "avg_queue": avg_q,
            "max_queue": sim.max_queue(),
            "wait_total": wait,
            "throughput_1000": flow,
            "state": sim.traffic_state(),
        })

    return {
        "plan": plan,
        "score_mean": mean(scores),
        "avg_queue_mean": mean(d["avg_queue"] for d in details),
        "max_queue_mean": mean(d["max_queue"] for d in details),
        "wait_total_mean": mean(d["wait_total"] for d in details),
        "throughput_1000_mean": mean(d["throughput_1000"] for d in details),
    }


def optimize_lights_grid(
    G,
    green_candidates=(12, 15, 18, 22),
    yellow_candidates=(2, 3, 4),
    all_red_candidates=(0, 1, 2),
    offset_modes=("checkerboard", "hash"),
    runs=6,
    n_ticks=500,
    n_vehicles=30,
):
    best = None
    all_results = []

    for g in green_candidates:
        for y in yellow_candidates:
            for r in all_red_candidates:
                for mode in offset_modes:
                    plan = {
                        "green_seconds": g,
                        "yellow_seconds": y,
                        "all_red_seconds": r,
                        "offset_mode": mode,
                    }
                    res = evaluate_light_plan(
                        G,
                        plan=plan,
                        runs=runs,
                        n_ticks=n_ticks,
                        n_vehicles=n_vehicles,
                    )
                    all_results.append(res)
                    if best is None or res["score_mean"] < best["score_mean"]:
                        best = res

    return best, sorted(all_results, key=lambda x: x["score_mean"])