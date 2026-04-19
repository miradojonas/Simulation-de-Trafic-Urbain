from dataclasses import dataclass
import random

@dataclass
class QueueSystem:
    seed: int = 123
    arrival_base: float= 0.35 # Prob d'arrivé
    service_base: float= 0.40 # Prob de service

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.queues = {} # node_id -> longueur

    def init_intersections(self, node_ids):
        self.queues = {nid: 0 for nid in node_ids}

    def step(self, state: str):
        # facteur selon état Markov
        if state == "FLUIDE":
            arrival, service = self.arrival_base * 0.8, self.service_base * 1.2
        elif state == "RALENTI":
            arrival, service = self.arrival_base * 1.0, self.service_base * 0.9
        else : #Bouchon
            arrival, service = self.arrival_base * 1.2, self.service_base * 0.6

        for nid in self.queues:
            # arrivée
            if self.rng.random() < arrival:
                self.queues[nid] += 1
            # service
            if self.queues[nid] > 0 and self.rng.random() < service:
                self.queues[nid] -= 1

    def avg_queue(self):
        if not self.queues:
            return 0.0
        return sum(self.queues.values()) / len(self.queues)
    
    def max_queue(self):
        return max(self.queues.values()) if self.queues else 0