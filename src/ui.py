"""
Interface graphique Pyside6 + matplotlib
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSizePolicy
)
from PySide6.QtCore import QTimer
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import ( FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT)
from matplotlib.collections import LineCollection
import matplotlib.patheffects as pe

class TrafficWindow(QMainWindow):
    # Fenêtre principale du programme
    def __init__(self, G, sim, places=None):
        super().__init__()
        self.G = G
        self.sim = sim
        self._frame_count = 0
        self.places = places or []
        self.place_text_artists = []
        self.max_place_labels = 80

        self.setWindowTitle("Simulation de Trafic Urbain d'Antananarivo")
        self.resize(1200, 800)
        self.showMaximized()

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
        self.ax = self.fig.add_subplot(111)
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
        self.info_label = QLabel("")

        controls_layout.addWidget(self.btn_toggle)
        controls_layout.addWidget(self.btn_reset)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.info_label)
        controls_layout.addWidget(self.btn_zoom)
        controls_layout.addWidget(self.btn_back)
        controls_layout.addWidget(self.btn_home)
        self.btn_toggle.clicked.connect(self._on_toggle)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_zoom.clicked.connect(self._on_zoom)
        self.btn_back.clicked.connect(self._on_back)
        self.btn_home.clicked.connect(self._on_home)

        # Dessin initial du réseau routier
        self._draw_roads_once()

        # Couche dynamique pour véhicules    self.places = places or []
        self.vehicle_scatter = self.ax.scatter([], [], s=24, c="#ff0000", alpha=0.95, zorder=5)

        #Timer Qt : appelle _tick() tous les 80ms
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._refresh_info()
        self.canvas.draw_idle()

    def _draw_roads_once(self):
        # Dessine les routes une seule fois (partie statique)
        segments = []
        xs = []
        ys = []
        max_edges = 30000
        edge_count = 0
        for u, v, _data in self.G.edges(keys=False, data=True):
            x1, y1 = self.G.nodes[u]["x"], self.G.nodes[u]["y"]
            x2, y2 = self.G.nodes[v]["x"], self.G.nodes[v]["y"]
            segments.append([(x1, y1), (x2, y2)])
            xs.extend((x1, x2))
            ys.extend((y1, y2))
            edge_count += 1
            if edge_count >= max_edges:
                break

        roads = LineCollection(segments, colors="#999999", linewidths=0.3, alpha=0.6, zorder=1)
        self.ax.add_collection(roads)
        self.ax.autoscale()

        # Zoom initial robuste: ignore les valeurs extrêmes qui écrasent la vue
        if xs and ys:
            xs_sorted = sorted(xs)
            ys_sorted = sorted(ys)

            def percentile(values, p):
                idx = int((len(values) - 1) * p)
                return values[idx]

            x_min = percentile(xs_sorted, 0.02)
            x_max = percentile(xs_sorted, 0.98)
            y_min = percentile(ys_sorted, 0.02)
            y_max = percentile(ys_sorted, 0.98)

            dx = max(x_max - x_min, 1e-9)
            dy = max(y_max - y_min, 1e-9)
            padx = dx * 0.05
            pady = dy * 0.05

            self.ax.set_xlim(x_min - padx, x_max + padx)
            self.ax.set_ylim(y_min - pady, y_max + pady)

        self.ax.set_aspect("auto")
        self.ax.set_axis_off()

        self._update_place_labels()

    def _on_toggle(self):
        # Bouton Play et Pause
        self.sim.toggle()
        self._refresh_info()

    def _on_reset(self):
        # Réinitialise la simulation
        self.sim.reset()
        self.vehicle_scatter.set_offsets([])
        self._refresh_info()
        self.canvas.draw_idle()

    def _refresh_info(self):
        # Mets à jour le petit dashboard texte
        status = "RUN" if self.sim.running else "PAUSE"
        self.info_label.setText(
            f"status={status} | tick={self.sim.tick_count} |"
            f"vehicles={len(self.sim.vehicles)} | avg_speed={self.sim.avg_speed():.4f}"
        )

    def _tick(self):
        # Tick d'animation : avance simulation + rafraichit d'affichage
        self.sim.step()
        positions = self.sim.vehicle_positions()
        self._frame_count += 1

        if positions:
            self.vehicle_scatter.set_offsets(positions)
        else:
            self.vehicle_scatter.set_offsets([])

        self._refresh_info()
        if self._frame_count % 10 == 0:
            self._update_place_labels()
        self.canvas.draw_idle()

    def _on_zoom(self):
        # Active, desactive le zoom de la toolbar matplotlib
        self.nav_toolbar.zoom()

    def _on_back(self):
        # Revient à la vue précédent
        self.nav_toolbar.back()
        self._update_place_labels()
        self.canvas.draw_idle()

    def _on_home(self):
        # Reinitialise la vue
        self.nav_toolbar.home()
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