"""
Module IHM – Interface graphique Kenney (rendu isométrique)
Fenêtre alternative avec :
  - Rendu isométrique des routes (tuiles Kenney)
  - Animation des véhicules (sprites PNG Kenney)
  - Tableau de bord complet (Markov + Files d'attente + Monte Carlo)
  - Interaction utilisateur complète
"""

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSizePolicy,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT,
)
from matplotlib.patches import Rectangle
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import matplotlib.image as mpimg
import matplotlib.patheffects as pe

from analytics import monte_carlo


class TrafficWindow(QMainWindow):
    """
    Fenêtre principale avec rendu isométrique (tuiles Kenney).

    Intègre :
      - Carte routière isométrique (tuiles grass, roadNS, roadEW, …)
      - Animation des véhicules (sprites PNG Kenney par catégorie)
      - Tableau de bord : état Markov, files, phénomène observé
      - Bouton Monte Carlo (Module 3)
    """

    def __init__(self, G, sim, places=None):
        super().__init__()
        self.G           = G
        self.sim         = sim
        self._frame_count= 0
        self._road_midpoints = []
        self._node_iso   = {}
        self._vehicle_artists = []
        self.places      = places or []
        self.place_text_artists = []
        self.max_place_labels   = 80

        # Dimensions des tuiles isométriques
        self.tile_w      = 100.0
        self.tile_h      = 65.0
        self.map_padding = 90.0

        self.setWindowTitle("Simulation de Trafic Urbain – Vue Isométrique Kenney")

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        else:
            self.resize(1200, 800)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        # ── Widget central ────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Figure matplotlib
        self.fig    = Figure(figsize=(10, 7))
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.nav_toolbar = NavigationToolbar2QT(self.canvas, self)
        self.nav_toolbar.setVisible(False)
        self.ax = self.fig.add_subplot(111)
        self.fig.patch.set_facecolor("#8fd470")
        self.ax.set_facecolor("#8fd470")
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        root_layout.addWidget(self.nav_toolbar, 0)
        root_layout.addWidget(self.canvas, 1)

        # ── Barre de contrôle ─────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(8, 6, 8, 6)
        ctrl.setSpacing(8)
        root_layout.addLayout(ctrl, 0)

        self.btn_toggle = QPushButton("Play / Pause")
        self.btn_reset  = QPushButton("Reset")
        self.btn_zoom   = QPushButton("Zoom")
        self.btn_back   = QPushButton("Arrière")
        self.btn_home   = QPushButton("Reset Vue")
        self.btn_mc     = QPushButton("Monte Carlo")
        self.info_label = QLabel("")
        self.mc_label   = QLabel("MC : –")

        ctrl.addWidget(self.btn_toggle)
        ctrl.addWidget(self.btn_reset)
        ctrl.addStretch(1)
        ctrl.addWidget(self.info_label)
        ctrl.addWidget(self.btn_zoom)
        ctrl.addWidget(self.btn_back)
        ctrl.addWidget(self.btn_home)
        ctrl.addWidget(self.btn_mc)
        ctrl.addWidget(self.mc_label)

        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_zoom.clicked.connect(self._on_zoom)
        self.btn_back.clicked.connect(self._on_back)
        self.btn_home.clicked.connect(self._on_home)
        self.btn_mc.clicked.connect(self._on_monte_carlo)

        # Chargement des assets Kenney
        self._load_assets()
        self._draw_roads_once()

        # Couche de densité (scatter files d'attente)
        self.queue_scatter = self.ax.scatter([], [], s=[], c=[], alpha=0.55, zorder=4)
        self._draw_vehicle_sprites()

        # Timer Qt (~6 FPS par défaut pour le rendu Kenney)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._refresh_info()
        self.canvas.draw_idle()
        QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self):
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.availableGeometry())
        self.showMaximized()

    # ===================================================================
    # CHARGEMENT DES ASSETS KENNEY
    # ===================================================================
    def _safe_load_image(self, path: Path):
        return mpimg.imread(path) if path.exists() else None

    def _load_assets(self):
        root = Path(__file__).resolve().parent.parent
        roads_dir    = root / "kenney_isometric-roads" / "png"
        vehicles_dir = root / "kenney_pixel-vehicle-pack" / "PNG" / "Cars"

        tile_names = [
            "grass", "roadNS", "roadEW", "roadNE", "roadNW",
            "roadES", "roadSW", "crossroad",
            "crossroadNES", "crossroadNEW", "crossroadNSW", "crossroadESW",
            "endN", "endE", "endS", "endW",
        ]
        self.road_tiles = {}
        for name in tile_names:
            img = self._safe_load_image(roads_dir / f"{name}.png")
            if img is not None:
                self.road_tiles[name] = img

        if "grass" not in self.road_tiles:
            raise FileNotFoundError(
                "Tuile manquante : kenney_isometric-roads/png/grass.png"
            )

        sprite_names = [
            "sedan", "taxi", "sports_red", "sports_yellow",
            "suv", "suv_green", "suv_large",
            "truck", "truckdelivery", "towtruck",
            "bus", "bus_school", "transport",
        ]
        self.vehicle_sprites = {}
        for name in sprite_names:
            img = self._safe_load_image(vehicles_dir / f"{name}.png")
            if img is not None:
                self.vehicle_sprites[name] = img

    # ===================================================================
    # RENDU DE LA CARTE ISOMÉTRIQUE
    # ===================================================================
    def _graph_to_iso(self, x, y):
        """Transforme des coordonnées graphe en coordonnées isométriques."""
        ix = (x - y) * (self.tile_w / 2.0)
        iy = (x + y) * (self.tile_h / 2.0)
        return ix, iy

    def _tile_key_from_dirs(self, n, e, s, w) -> str:
        dirs = (bool(n), bool(e), bool(s), bool(w))
        mapping = {
            (1, 1, 1, 1): "crossroad",
            (1, 1, 1, 0): "crossroadNES",
            (1, 1, 0, 1): "crossroadNEW",
            (1, 0, 1, 1): "crossroadNSW",
            (0, 1, 1, 1): "crossroadESW",
            (1, 0, 1, 0): "roadNS",
            (0, 1, 0, 1): "roadEW",
            (1, 1, 0, 0): "roadNE",
            (1, 0, 0, 1): "roadNW",
            (0, 1, 1, 0): "roadES",
            (0, 0, 1, 1): "roadSW",
            (1, 0, 0, 0): "endN",
            (0, 1, 0, 0): "endE",
            (0, 0, 1, 0): "endS",
            (0, 0, 0, 1): "endW",
        }
        return mapping.get(dirs, "grass")

    def _has_edge_between(self, u, v) -> bool:
        if u not in self.G or v not in self.G:
            return False
        return self.G.has_edge(u, v) or self.G.has_edge(v, u)

    def _draw_roads_once(self):
        self.ax.clear()
        self.ax.set_facecolor("#8fd470")
        self._node_iso = {}

        rows = int(self.G.graph.get("rows", 0))
        cols = int(self.G.graph.get("cols", 0))
        if rows <= 0 or cols <= 0:
            max_r, max_c = 0, 0
            for nid in self.G.nodes:
                parts = str(nid).split("_")
                if len(parts) == 3 and parts[0] == "I":
                    max_r = max(max_r, int(parts[1]))
                    max_c = max(max_c, int(parts[2]))
            rows, cols = max_r, max_c

        self._road_midpoints = []

        # ── Tuiles herbe ──────────────────────────────────────────────────
        for r in range(rows + 1):
            for c in range(cols + 1):
                nid = f"I_{r}_{c}"
                if nid not in self.G.nodes:
                    continue
                x  = self.G.nodes[nid]["x"]
                y  = self.G.nodes[nid]["y"]
                ix, iy = self._graph_to_iso(x, y)
                self._node_iso[nid] = (ix, iy)
                grass = self.road_tiles["grass"]
                self.ax.imshow(
                    grass,
                    extent=[ix - self.tile_w/2, ix + self.tile_w/2,
                            iy - self.tile_h/2, iy + self.tile_h/2],
                    zorder=1,
                )

        # ── Tuiles routes ─────────────────────────────────────────────────
        for r in range(rows + 1):
            for c in range(cols + 1):
                nid = f"I_{r}_{c}"
                if nid not in self.G.nodes:
                    continue
                key = self._tile_key_from_dirs(
                    self._has_edge_between(nid, f"I_{r+1}_{c}"),
                    self._has_edge_between(nid, f"I_{r}_{c+1}"),
                    self._has_edge_between(nid, f"I_{r-1}_{c}"),
                    self._has_edge_between(nid, f"I_{r}_{c-1}"),
                )
                tile = self.road_tiles.get(key, self.road_tiles["grass"])
                ix, iy = self._node_iso[nid]
                self.ax.imshow(
                    tile,
                    extent=[ix - self.tile_w/2, ix + self.tile_w/2,
                            iy - self.tile_h/2, iy + self.tile_h/2],
                    zorder=10,
                )

        # ── Midpoints des arêtes (pour la densité) ────────────────────────
        for u, v, _data in self.G.edges(keys=False, data=True):
            x1, y1 = self.G.nodes[u]["x"], self.G.nodes[u]["y"]
            x2, y2 = self.G.nodes[v]["x"], self.G.nodes[v]["y"]
            self._road_midpoints.append(((x1 + x2) * 0.5, (y1 + y2) * 0.5))

        if self._node_iso:
            xs = [p[0] for p in self._node_iso.values()]
            ys = [p[1] for p in self._node_iso.values()]
            self.ax.set_xlim(min(xs) - self.map_padding, max(xs) + self.map_padding)
            self.ax.set_ylim(max(ys) + self.map_padding, min(ys) - self.map_padding)

        self.ax.set_aspect("equal")
        self.ax.set_axis_off()

    # ===================================================================
    # RENDU DES VÉHICULES
    # ===================================================================
    def _clear_vehicle_artists(self):
        for artist in self._vehicle_artists:
            artist.remove()
        self._vehicle_artists = []

    def _draw_vehicle_sprites(self):
        """Dessine les sprites des véhicules à leur position isométrique."""
        self._clear_vehicle_artists()
        if not hasattr(self.sim, "vehicle_render_data"):
            return

        for item in self.sim.vehicle_render_data():
            sprite_name = item.get("sprite", "sedan")
            img = self.vehicle_sprites.get(sprite_name) or self.vehicle_sprites.get("sedan")
            if img is None:
                continue

            x, y   = float(item["x"]), float(item["y"])
            ix, iy = self._graph_to_iso(x, y)
            kind   = item.get("kind", "car")
            zoom   = {"suv": 1.28, "truck": 1.40, "bus": 1.48}.get(kind, 1.20)

            oi = OffsetImage(img, zoom=zoom)
            ab = AnnotationBbox(oi, (ix, iy - 2.0), frameon=False, zorder=60)
            self.ax.add_artist(ab)
            self._vehicle_artists.append(ab)

    # ===================================================================
    # OVERLAY FILES D'ATTENTE
    # ===================================================================
    def _density_color(self, t):
        """Gradient vert → rouge selon le taux de congestion t ∈ [0, 1]."""
        t = max(0.0, min(1.0, float(t)))
        if t < 0.5:
            k = t / 0.5
            return (0.2 + 0.8 * k, 0.7 + 0.2 * k, 0.2)
        k = (t - 0.5) / 0.5
        return (1.0, 0.9 - 0.8 * k, 0.2 - 0.2 * k)

    def _update_queue_overlay(self):
        """
        Met à jour l'overlay de densité des files d'attente.
        Cercles colorés proportionnels à la longueur des files (Module 2).
        """
        if not hasattr(self.sim, "queue_snapshot"):
            return
        queues = self.sim.queue_snapshot()
        if not queues:
            self.queue_scatter.set_offsets([])
            self.queue_scatter.set_sizes([])
            self.queue_scatter.set_color([])
            return

        max_q = max(queues.values()) if queues else 0
        xs, ys, sizes, colors = [], [], [], []
        for nid, q in queues.items():
            if nid not in self.G.nodes:
                continue
            x  = self.G.nodes[nid]["x"]
            y  = self.G.nodes[nid]["y"]
            ix, iy = self._graph_to_iso(x, y)
            xs.append(ix)
            ys.append(iy)
            sizes.append(20 + 10 * q)
            t = 0.0 if max_q == 0 else q / max_q
            colors.append(self._density_color(t))

        if xs:
            self.queue_scatter.set_offsets(list(zip(xs, ys)))
            self.queue_scatter.set_sizes(sizes)
            self.queue_scatter.set_color(colors)
        else:
            self.queue_scatter.set_offsets([])
            self.queue_scatter.set_sizes([])
            self.queue_scatter.set_color([])

    # ===================================================================
    # BOUCLE DE MISE À JOUR
    # ===================================================================
    def _tick(self):
        """Avance la simulation + rafraîchit le rendu."""
        self.sim.step()
        self._frame_count += 1
        self._draw_vehicle_sprites()
        self._refresh_info()
        if self._frame_count % 10 == 0:
            self._update_place_labels()
        self._update_queue_overlay()
        self.canvas.draw_idle()

    def _refresh_info(self):
        """Met à jour le bandeau d'information."""
        status = "RUN" if self.sim.running else "PAUSE"
        state  = self.sim.traffic_state()
        avg_q  = self.sim.avg_queue()
        max_q  = self.sim.max_queue()
        obs    = self.sim.queue_observation()

        counts = {"car": 0, "suv": 0, "truck": 0, "bus": 0}
        for veh in self.sim.vehicles:
            counts[veh.kind] = counts.get(veh.kind, 0) + 1

        self.info_label.setText(
            f"{status} | {state} | tick={self.sim.tick_count} | "
            f"n={len(self.sim.vehicles)} | spd={self.sim.avg_speed():.4f} | "
            f"avg_q={avg_q:.2f} | max_q={max_q} | obs={obs} | "
            f"C={counts['car']} S={counts['suv']} T={counts['truck']} B={counts['bus']}"
        )

    # ===================================================================
    # ÉTIQUETTES DE LIEUX
    # ===================================================================
    def _clear_place_labels(self):
        for artist in self.place_text_artists:
            artist.remove()
        self.place_text_artists = []

    def _place_priority(self, place_type: str) -> int:
        return {"city": 0, "town": 1, "suburb": 2,
                "neighbourhood": 3, "village": 4, "hamlet": 5}.get(place_type, 9)

    def _update_place_labels(self):
        self._clear_place_labels()
        if not self.places:
            return
        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()
        span = max(abs(x_max - x_min), abs(y_max - y_min))

        if span > 0.20:   allowed = {"city", "town"}
        elif span > 0.10: allowed = {"city", "town", "suburb"}
        elif span > 0.05: allowed = {"city", "town", "suburb", "neighbourhood"}
        else:             allowed = {"city", "town", "suburb", "neighbourhood", "village"}

        visible = [
            p for p in self.places
            if p["place"] in allowed
            and x_min <= p["x"] <= x_max
            and y_min <= p["y"] <= y_max
        ]
        visible.sort(key=lambda p: (self._place_priority(p["place"]), p["name"]))
        visible = visible[:self.max_place_labels]

        for p in visible:
            t = self.ax.text(
                p["x"], p["y"], p["name"],
                fontsize=8, color="#202020",
                ha="center", va="center", zorder=6,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white", alpha=0.9)],
            )
            self.place_text_artists.append(t)

    # ===================================================================
    # ACTIONS DES BOUTONS
    # ===================================================================
    def _on_toggle(self):
        self.sim.toggle()
        self._refresh_info()

    def _on_reset(self):
        self.sim.reset()
        self._clear_vehicle_artists()
        self._draw_vehicle_sprites()
        self._refresh_info()
        self.canvas.draw_idle()

    def _on_zoom(self):
        self.nav_toolbar.zoom()

    def _on_back(self):
        self.nav_toolbar.back()
        self._update_place_labels()
        self.canvas.draw_idle()

    def _on_home(self):
        self.nav_toolbar.home()
        self._update_place_labels()
        self.canvas.draw_idle()

    def _on_monte_carlo(self):
        """
        Lance une analyse Monte Carlo (Module 3) et affiche le résumé
        dans l'étiquette MC du tableau de bord.
        """
        n_veh = len(self.sim.vehicles) if self.sim.vehicles else 10
        self.mc_label.setText("MC : calcul…")
        self.canvas.draw_idle()
        try:
            res = monte_carlo(self.G, runs=20, n_ticks=300, n_vehicles=n_veh)
            self.mc_label.setText(
                f"MC runs={res['runs']} | "
                f"avg_q={res['avg_queue_mean']:.2f} "
                f"[{res['avg_queue_min']:.2f}–{res['avg_queue_max']:.2f}] | "
                f"max_q moy={res['max_queue_mean']:.2f} | "
                f"états={res['state_counts']}"
            )
        except Exception as exc:
            self.mc_label.setText(f"MC erreur : {exc}")