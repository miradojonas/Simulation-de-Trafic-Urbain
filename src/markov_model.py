"""
Module 1 – Chaîne de Markov
Modélise l'évolution macro-état du trafic urbain.

États possibles (conformément au projet) :
  FLUIDE   : circulation normale
  RALENTI  : trafic dégradé
  BOUCHON  : congestion forte

Le trafic évolue de manière probabiliste entre ces trois états
à chaque appel à step().
"""

from dataclasses import dataclass, field
import random

# Ensemble des états reconnus – ordre stable pour la matrice de transition
STATES = ["FLUIDE", "RALENTI", "BOUCHON"]

# Facteurs de vitesse associés à chaque état macro
SPEED_FACTORS = {
    "FLUIDE":  1.00,
    "RALENTI": 0.65,
    "BOUCHON": 0.30,
}

# Matrice de transition P[état_courant] = [p_FLUIDE, p_RALENTI, p_BOUCHON]
# Chaque ligne somme à 1.0
TRANSITION_MATRIX = {
    "FLUIDE":  [0.75, 0.22, 0.03],
    "RALENTI": [0.20, 0.60, 0.20],
    "BOUCHON": [0.05, 0.35, 0.60],
}


@dataclass
class MarkovTrafficModel:
    """
    Chaîne de Markov à temps discret pour le trafic urbain.

    Attributs
    ---------
    seed          : graine aléatoire (reproductibilité)
    initial_state : état de départ parmi STATES
    state         : état courant (mis à jour par step())
    history       : historique des états successifs
    """
    seed: int = 123
    initial_state: str = "FLUIDE"
    history: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        if self.initial_state not in STATES:
            raise ValueError(
                f"initial_state '{self.initial_state}' invalide. "
                f"Choisir parmi : {STATES}"
            )
        self.rng = random.Random(self.seed)
        self.state = self.initial_state
        self.history = [self.state]
        # Exposer la matrice et les états pour l'IHM / rapports
        self.P = TRANSITION_MATRIX
        self.states = STATES

    # ------------------------------------------------------------------
    # Évolution de la chaîne
    # ------------------------------------------------------------------
    def step(self) -> str:
        """
        Effectue une transition probabiliste vers le prochain état.
        Retourne le nouvel état.
        """
        probs = self.P[self.state]
        r = self.rng.random()
        cumul = 0.0
        for s, p in zip(STATES, probs):
            cumul += p
            if r <= cumul:
                self.state = s
                break
        self.history.append(self.state)
        return self.state

    # ------------------------------------------------------------------
    # Métriques
    # ------------------------------------------------------------------
    def speed_factor(self) -> float:
        """Retourne le facteur de vitesse lié à l'état courant."""
        return SPEED_FACTORS[self.state]

    def state_distribution(self) -> dict:
        """
        Calcule la distribution empirique des états sur tout l'historique.
        Utile pour les analyses Monte Carlo et rapports.
        """
        if not self.history:
            return {s: 0.0 for s in STATES}
        n = len(self.history)
        return {s: self.history.count(s) / n for s in STATES}

    def reset(self, initial_state: str | None = None):
        """Remet la chaîne à son état initial (ou à l'état fourni)."""
        if initial_state is not None:
            if initial_state not in STATES:
                raise ValueError(f"État invalide : {initial_state}")
            self.initial_state = initial_state
        self.state = self.initial_state
        self.rng = random.Random(self.seed)
        self.history = [self.state]