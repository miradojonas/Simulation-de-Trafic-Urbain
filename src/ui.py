"""Interface graphique PySide6 + rendu Kenney (routes + véhicules)."""

from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import ( FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT)
from matplotlib.patches import Rectangle
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import matplotlib.image as mpimg
import matplotlib.patheffects as pe
from analytics import monte_carlo

class TrafficWindow(QMainWindow):
    # Fenêtre principale du programme
    def __init__(self, G, sim, places=None):
        super().__init__()
        self.G = G
        self.sim = sim
        self._frame_count = 0
        self.grid_mode = False
        self.grid_patches = []
        self._road_midpoints = []
        self._node_iso = {}
        self._vehicle_artists = []
        self.places = places or []
        self.place_text_artists = []
        self.max_place_labels = 80
        self.tile_w = 100.0
        self.tile_h = 65.0
        self.map_padding = 90.0
        self.setWindowTitle("Simulation de Trafic Urbain - Ville Synthétique")

        # Taille de fenêtre calée sur la surface utile de l'écran
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            self.setGeometry(geom)
        else:
            self.resize(1200, 800)
        # Forcer une occupation maximale de l'écran (fiable selon WM Linux)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

        # Widget central + layout principal
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Figure matplotlib intégrée
        self.fig = Figure(figsize=(10, 7))
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

        # Barre de contrôle (boutons + infos)
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(8, 6, 8, 6)
        controls_layout.setSpacing(8)
        root_layout.addLayout(controls_layout, 0)
        root_layout.setStretch(0, 0)
        root_layout.setStretch(1, 1)
        root_layout.setStretch(2, 0)

        self.btn_toggle = QPushButton("Play / Pause")
        self.btn_reset = QPushButton("Reset")
        self.btn_zoom = QPushButton("Zoom")
        self.btn_back = QPushButton("Arrière")
        self.btn_home = QPushButton("Reset Vue")
        self.btn_grid = QPushButton("Vue Carrés")
        # Bouton du module 3
        self.btn_mc = QPushButton("Monte Carlo")
        self.mc_label = QLabel("MC : -")
        self.info_label = QLabel("")

        controls_layout.addWidget(self.btn_toggle)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.info_label)
        controls_layout.addWidget(self.btn_zoom)
        controls_layout.addWidget(self.btn_back)
        controls_layout.addWidget(self.btn_home)
        controls_layout.addWidget(self.btn_grid)
        controls_layout.addWidget(self.btn_mc)
        controls_layout.addWidget(self.mc_label)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_zoom.clicked.connect(self._on_zoom)
        self.btn_back.clicked.connect(self._on_back)
        self.btn_home.clicked.connect(self._on_home)
        self.btn_mc.clicked.connect(self._on_monte_carlo)
        self.btn_grid.clicked.connect(self._on_toggle_grid)

        # Cette vue n'utilise plus l'ancien overlay carrés
        self.btn_grid.setVisible(False)

        # Chargement des assets + dessin initial de la carte Kenney
        self._load_assets()
        self._draw_roads_once()

        # Couche dynamique pour véhicules et congestion
        self.queue_scatter = self.ax.scatter([], [], s=[], c=[], alpha=0.55, zorder=4)
        self._draw_vehicle_sprites()

        #Timer Qt : appelle _tick() tous les 80ms
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._refresh_info()
        self.canvas.draw_idle()
        QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self):
        # Ajuste la fenêtre à l'écran réel après création (plus fiable selon WM Linux).
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        geom = screen.availableGeometry()
        self.setGeometry(geom)
        self.showMaximized()

    def _safe_load_image(self, path: Path):
        if path.exists():
            return mpimg.imread(path)
        return None

    def _load_assets(self):
        root = Path(__file__).resolve().parent.parent

        roads_dir = root / "kenney_isometric-roads" / "png"
        vehicles_dir = root / "kenney_pixel-vehicle-pack" / "PNG" / "Cars"

        tile_names = [
            "grass", "roadNS", "roadEW", "roadNE", "roadNW", "roadES", "roadSW",
            "crossroad", "crossroadNES", "crossroadNEW", "crossroadNSW", "crossroadESW",
            "endN", "endE", "endS", "endW",
        ]
        self.road_tiles = {}
        for name in tile_names:
            img = self._safe_load_image(roads_dir / f"{name}.png")
            if img is not None:
                self.road_tiles[name] = img

        if "grass" not in self.road_tiles:
            raise FileNotFoundError("Tuile manquante: kenney_isometric-roads/png/grass.png")

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

    def _graph_to_iso(self, x, y):
        ix = (x - y) * (self.tile_w / 2.0)
        iy = (x + y) * (self.tile_h / 2.0)
        return ix, iy

    def _tile_key_from_dirs(self, n, e, s, w):
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

    def _has_edge_between(self, u, v):
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
            max_r = 0
            max_c = 0
            for nid in self.G.nodes:
                parts = str(nid).split("_")
                if len(parts) == 3 and parts[0] == "I":
                    max_r = max(max_r, int(parts[1]))
                    max_c = max(max_c, int(parts[2]))
            rows, cols = max_r, max_c

        self._road_midpoints = []

        for r in range(rows + 1):
            for c in range(cols + 1):
                nid = f"I_{r}_{c}"
                if nid not in self.G.nodes:
                    continue
                x = self.G.nodes[nid]["x"]
                y = self.G.nodes[nid]["y"]
                ix, iy = self._graph_to_iso(x, y)
                self._node_iso[nid] = (ix, iy)

                grass = self.road_tiles["grass"]
                self.ax.imshow(
                    grass,
                    extent=[ix - self.tile_w / 2, ix + self.tile_w / 2, iy - self.tile_h / 2, iy + self.tile_h / 2],
                    zorder=1,
                )

        for r in range(rows + 1):
            for c in range(cols + 1):
                nid = f"I_{r}_{c}"
                if nid not in self.G.nodes:
                    continue

                n_id = f"I_{r + 1}_{c}"
                s_id = f"I_{r - 1}_{c}"
                e_id = f"I_{r}_{c + 1}"
                w_id = f"I_{r}_{c - 1}"

                key = self._tile_key_from_dirs(
                    self._has_edge_between(nid, n_id),
                    self._has_edge_between(nid, e_id),
                    self._has_edge_between(nid, s_id),
                    self._has_edge_between(nid, w_id),
                )
                tile = self.road_tiles.get(key, self.road_tiles["grass"])

                ix, iy = self._node_iso[nid]
                self.ax.imshow(
                    tile,
                    extent=[ix - self.tile_w / 2, ix + self.tile_w / 2, iy - self.tile_h / 2, iy + self.tile_h / 2],
                    zorder=10,
                )

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

    def _clear_vehicle_artists(self):
        for artist in self._vehicle_artists:
            artist.remove()
        self._vehicle_artists = []

    def _draw_vehicle_sprites(self):
        self._clear_vehicle_artists()
        if not hasattr(self.sim, "vehicle_render_data"):
            return

        for item in self.sim.vehicle_render_data():
            sprite_name = item.get("sprite", "sedan")
            img = self.vehicle_sprites.get(sprite_name)
            if img is None:
                img = self.vehicle_sprites.get("sedan")
            if img is None:
                continue

            x = float(item["x"])
            y = float(item["y"])
            ix, iy = self._graph_to_iso(x, y)

            kind = item.get("kind", "car")
            zoom = 1.20
            if kind == "suv":
                zoom = 1.28
            elif kind == "truck":
                zoom = 1.40
            elif kind == "bus":
                zoom = 1.48

            oi = OffsetImage(img, zoom=zoom)
            ab = AnnotationBbox(oi, (ix, iy - 2.0), frameon=False, zorder=60)
            self.ax.add_artist(ab)
            self._vehicle_artists.append(ab)

    def _density_color(self, t):
        # Dégradé vert -> jaune -> rouge
        t = max(0.0, min(1.0, float(t)))
        if t < 0.5:
            k = t / 0.5
            r, g, b = (0.2 + 0.8 * k, 0.7 + 0.2 * k, 0.2)
        else:
            k = (t - 0.5) / 0.5
            r, g, b = (1.0, 0.9 - 0.8 * k, 0.2 - 0.2 * k)
        return (r, g, b)

    def _clear_grid_overlay(self):
        for patch in self.grid_patches:
            patch.remove()
        self.grid_patches = []

    def _update_grid_overlay(self):
        if not self.grid_mode:
            return

        self._clear_grid_overlay()

        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()

        nx = 26
        ny = 26
        dx = (x_max - x_min) / nx if nx else 1.0
        dy = (y_max - y_min) / ny if ny else 1.0
        if dx <= 0 or dy <= 0:
            return

        counts = [[0 for _ in range(nx)] for _ in range(ny)]

        for mx, my in self._road_midpoints:
            if not (x_min <= mx <= x_max and y_min <= my <= y_max):
                continue
            ix = int((mx - x_min) / dx)
            iy = int((my - y_min) / dy)
            if ix == nx:
                ix = nx - 1
            if iy == ny:
                iy = ny - 1
            if 0 <= ix < nx and 0 <= iy < ny:
                counts[iy][ix] += 1

        max_count = max((c for row in counts for c in row), default=0)
        if max_count <= 0:
            return

        for iy in range(ny):
            for ix in range(nx):
                c = counts[iy][ix]
                if c <= 0:
                    continue
                t = c / max_count
                color = self._density_color(t)
                rect = Rectangle(
                    (x_min + ix * dx, y_min + iy * dy),
                    dx,
                    dy,
                    facecolor=color,
                    edgecolor=(1, 1, 1, 0.30),
                    linewidth=0.25,
                    alpha=0.55,
                    zorder=2,
                )
                self.ax.add_patch(rect)
                self.grid_patches.append(rect)

    def _on_toggle_grid(self):
        # Vue Kenney: ancien mode grille désactivé.
        return

    def _on_toggle(self):
        # Bouton Play et Pause
        self.sim.toggle()
        self._refresh_info()

    def _on_reset(self):
        # Réinitialise la simulation
        self.sim.reset()
        self._clear_vehicle_artists()
        self._draw_vehicle_sprites()
        self._refresh_info()
        self.canvas.draw_idle()

    def _refresh_info(self):
        # Rafraichit le bandeau d'information avec metriques M1 + M2
        status = "RUN" if self.sim.running else "PAUSE"
        state = self.sim.traffic_state() if hasattr(self.sim, "traffic_state") else "N/A"
        avg_q = self.sim.avg_queue() if hasattr(self.sim, "avg_queue") else 0.0
        max_q = self.sim.max_queue() if hasattr(self.sim, "max_queue") else 0
        obs = self._queue_observation(avg_q, max_q)
        counts = {"car": 0, "suv": 0, "truck": 0, "bus": 0}
        for v in self.sim.vehicles:
            counts[v.kind] = counts.get(v.kind, 0) + 1

        self.info_label.setText(
            f"status={status} | state={state} | tick={self.sim.tick_count} |"
            f"vehicles={len(self.sim.vehicles)} | avg_speed={self.sim.avg_speed():.4f} | "
            f"avg_q={avg_q:.2f} | max_q={max_q} | obs={obs} | "
            f"C={counts['car']} SUV={counts['suv']} T={counts['truck']} B={counts['bus']}"
        )


    def _tick(self):
        # Tick d'animation : avance simulation + rafraichit d'affichage
        self.sim.step()
        self._frame_count += 1

        self._draw_vehicle_sprites()

        self._refresh_info()
        if self._frame_count % 10 == 0:
            self._update_place_labels()
        if self.grid_mode and self._frame_count % 8 == 0:
            self._update_grid_overlay()
        self.canvas.draw_idle()
        self._update_queue_overlay()

    def _on_zoom(self):
        # Active, desactive le zoom de la toolbar matplotlib
        self.nav_toolbar.zoom()

    def _on_back(self):
        # Revient à la vue précédent
        self.nav_toolbar.back()
        if self.grid_mode:
            self._update_grid_overlay()
        self._update_place_labels()
        self.canvas.draw_idle()

    def _on_home(self):
        # Reinitialise la vue
        self.nav_toolbar.home()
        if self.grid_mode:
            self._update_grid_overlay()
        self._update_place_labels()
        self.canvas.draw_idle()

    def _clear_place_labels(self):
        for artist in self.place_text_artists:
            artist.remove()
        self.place_text_artists = []

    def _place_priority(self, place_type: str) -> int:
        # plus petit = prioritaire
        order = {
            "city": 0,
            "town": 1,
            "suburb": 2,
            "neighbourhood": 3,
            "village": 4,
            "hamlet": 5,
        }
        return order.get(place_type, 9)

    def _update_place_labels(self):
        self._clear_place_labels()

        if not self.places:
            return

        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()

        # Taille de la vue. Plus petit => plus zoomé
        span_x = abs(x_max - x_min)
        span_y = abs(y_max - y_min)
        span = max(span_x, span_y)

        # Filtre par niveau de zoom
        if span > 0.20:
            allowed = {"city", "town"}
        elif span > 0.10:
            allowed = {"city", "town", "suburb"}
        elif span > 0.05:
            allowed = {"city", "town", "suburb", "neighbourhood"}
        else:
            allowed = {"city", "town", "suburb", "neighbourhood", "village"}

        visible = []
        for p in self.places:
            if p["place"] not in allowed:
                continue
            if not (x_min <= p["x"] <= x_max and y_min <= p["y"] <= y_max):
                continue
            visible.append(p)

        # Trier: priorité type + nom
        visible.sort(key=lambda p: (self._place_priority(p["place"]), p["name"]))

        # Limiter le nombre de labels
        visible = visible[:self.max_place_labels]

        for p in visible:
            t = self.ax.text(
                p["x"], p["y"], p["name"],
                fontsize=8,
                color="#202020",
                ha="center",
                va="center",
                zorder=6,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white", alpha=0.9)],
            )
            self.place_text_artists.append(t)

    def _queue_observation(self, avg_q, max_q):
        # Module 2: Interprétation qualitative de l'état d'écoulement
        if max_q >= 8 or avg_q >= 4:
            return "CONGESTION"
        if max_q >= 4 or avg_q >= 2:
            return "ATTENTE"
        return "SATURATION FAIBLE"
        
    def _update_queue_overlay(self):
        # Met à jour la couche visuelle des files d'attentes:
        # Plus la file est longue, plus le point est grand et rouge
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

            x = self.G.nodes[nid]["x"]
            y = self.G.nodes[nid]["y"]
            ix, iy = self._graph_to_iso(x, y)
            xs.append(ix)
            ys.append(iy)

            # Taille proportionnelle à la file
            sizes.append(20 + 10 * q)

            # Couleur via gradient existant (vert -> rouge)
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

    def _on_monte_carlo(self):
        # LAnce une analyse Monte Carlo et affiche un résumé compact dans l'UI
        n_veh = len(self.sim.vehicles) if hasattr(self.sim, "vehicles") else 10
        self.mc_label.setText("MC: calcul ...")
        self.canvas.draw_idle()

        try:
            res = monte_carlo(self.G, runs=20, n_ticks=300, n_vehicles=n_veh)
            self.mc_label.setText(
                "MC "
                f"runs={res['runs']} | "
                f"avg_q={res['avg_queue_mean']:.2f} "
                f"[{res['avg_queue_min']:.2f}-{res['avg_queue_max']:.2f}] | "
                f"max_q={res['max_queue_mean']:.2f}"
            )
        except Exception as e:
            self.mc_label.setText(f"MC erreur: {e}")