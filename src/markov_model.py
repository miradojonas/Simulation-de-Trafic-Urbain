from dataclasses import dataclass
import random

STATES = ["FLUIDE", "RALENTI", "BOUCHON"]

@dataclass
class MarkovTrafficModel:
    seed: int = 123
    initial_state: str= "FLUIDE"

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        self.state = self.initial_state

        # Matrice de transition simple (somme des lignes = 1)
        self.P = {
            "FLUIDE": [0.75, 0.22, 0.03],
            "RALENTI": [0.20, 0.60, 0.20],
            "BOUCHON": [0.05, 0.35, 0.60],
        }

    def step(self):
        probs = self.P[self.state]
        r = self.rng.random()
        c = 0.0
        for s, p in zip(STATES, probs):
            c += p
            if r <= c:
                self.state = s
                break
        return self.state
        
    def speed_factor(self):
        return {
            "FLUIDE": 1.00,
            "RALENTI": 0.65,
            "BOUCHON": 0.30,
        }[self.state]