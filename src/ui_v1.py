"""
Module IHM – Interface graphique principale (PySide6)
Fenêtre de simulation de trafic urbain avec :
  - Visualisation du réseau routier (carte + marquages)
  - Animation des véhicules orientés (sprites)
  - Tableau de bord temps réel (état Markov, files d'attente, métriques)
  - Interaction utilisateur : Play/Pause, Reset, Vitesse, Monte Carlo, Feux
"""

import math
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import (
    QBrush, QColor, QGuiApplication, QImage,
    QPainter, QPen, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analytics import monte_carlo
from optimization import optimize_lights_grid, evaluate_baseline_no_lights




class TrafficV1Window(QMainWindow):
    """
    Fenêtre principale de la simulation de trafic urbain.

    Intègre :
      - Rendu de la carte (routes, bâtiments, intersections)
      - Animation des véhicules (sprites SVG ou fallback coloré)
      - Tableau de bord : état Markov, files d'attente, phénomène observé
      - Boutons : Play/Pause, Reset, Vitesse ×1/×2/×4, Monte Carlo, Feux
    """

    def __init__(self, G, sim):
        super().__init__()
        self.G   = G
        self.sim = sim

        self.setWindowTitle("Simulation de Trafic Urbain – Modélisation Stochastique")

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.resize(screen.availableGeometry().size() * 0.92)
        else:
            self.resize(1400, 900)

        # ── État interne ─────────────────────────────────────────────────
        self.running          = True
        self.speed_multiplier = 1   # ×1 / ×2 / ×4

        # Optimisation (module 4)
        self._optim_thread = None
        self._optim_result = None
        self._optim_error = None
        self._optim_poll_timer = None

        # Monte Carlo : dernier résultat (pour export)
        self._last_mc_result = None
        self._last_mc_meta = None

        # Debug/diagnostic : dernière exception capturée dans le tick
        self._last_tick_exception = None

        # Dictionnaires de suivi pour le rendu fluide
        self.vehicle_items    : dict = {}
        self.prev_positions   : dict = {}
        self.prev_dirs        : dict = {}
        self.prev_angles      : dict = {}
        self.display_positions: dict = {}
        self.lane_side_by_veh : dict = {}

        # Paramètres de fluidité visuelle
        self.lane_offset_px         = 12.0
        self.max_turn_deg_per_tick  = 12.0
        self.base_interp_alpha      = 0.42
        self.intersection_radius_px = 40.0
        self.turn_blend_start       = 0.70

        # Cache des coordonnées d'intersections
        self._intersection_points = [
            (float(self.G.nodes[n]["x"]), float(self.G.nodes[n]["y"]))
            for n in self.G.nodes
        ]

        # Sprites véhicules
        self.vehicle_pixmaps = self._build_vehicle_pixmaps()

        # Feux tricolores (items graphiques)
        self._light_items: dict = {}
        self._light_size_px = 8.0
        self._light_offset_px = 18.0
        self._light_nodes = self._get_signal_nodes_from_sim()

        # ── Construction de l'UI ─────────────────────────────────────────
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Barre de contrôle supérieure
        controls = QHBoxLayout()
        self.btn_play   = QPushButton("Pause")
        self.btn_reset  = QPushButton("Reset")
        self.btn_speed  = QPushButton("Vitesse ×1")
        self.btn_lights = QPushButton("Feux : OFF")
        self.btn_opt    = QPushButton("Optimiser feux")
        self.btn_mc     = QPushButton("Monte Carlo")
        self.btn_export = QPushButton("Export PDF")
        self.info_label = QLabel("tick=0")

        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_reset)
        controls.addWidget(self.btn_speed)
        controls.addWidget(self.btn_lights)
        controls.addWidget(self.btn_opt)
        controls.addWidget(self.btn_mc)
        controls.addWidget(self.btn_export)
        controls.addStretch(1)
        controls.addWidget(self.info_label)
        layout.addLayout(controls)

        self.btn_export.setEnabled(False)

        # Tableau de bord (lisible, multi-lignes)
        self.dashboard_widget = QWidget()
        dash_layout = QGridLayout(self.dashboard_widget)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setHorizontalSpacing(10)
        dash_layout.setVerticalSpacing(2)

        self.dashboard_label_main = QLabel(
            "État Markov : –  |  Vitesse : –  |  Feux : OFF  |  Débit/1000 : –"
        )
        self.dashboard_label_secondary = QLabel(
            "Files : moy – / max –  |  Attente : –  |  Arrêts : –  |  Réservations : –"
        )
        self.dashboard_label_extra = QLabel(
            "Feux (config) : –  |  Top files : –"
        )

        dash_style = (
            "background:#1a1a2e; color:#e0e0ff; padding:4px 8px; "
            "font-family:monospace; font-size:12px; border-radius:4px;"
        )
        for lab in (self.dashboard_label_main, self.dashboard_label_secondary, self.dashboard_label_extra):
            lab.setStyleSheet(dash_style)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        dash_layout.addWidget(self.dashboard_label_main, 0, 0)
        dash_layout.addWidget(self.dashboard_label_secondary, 1, 0)
        dash_layout.addWidget(self.dashboard_label_extra, 2, 0)
        layout.addWidget(self.dashboard_widget)

        # Scène graphique (carte + véhicules)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor("#e9f4e9")))
        self.view  = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        layout.addWidget(self.view, 1)

        # Dessin initial de la carte (une seule fois)
        self._draw_map_once()
        self._create_traffic_lights_visual()
        self._update_traffic_lights_visual()
        self._fit_scene()

        # Connexions des boutons
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_reset.clicked.connect(self._reset_sim)
        self.btn_speed.clicked.connect(self._cycle_speed)
        self.btn_lights.clicked.connect(self._toggle_lights)
        self.btn_opt.clicked.connect(self._optimize_lights)
        self.btn_mc.clicked.connect(self._run_monte_carlo)
        self.btn_export.clicked.connect(self._export_monte_carlo_pdf)

        # Timer d'animation (~30 FPS)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ===================================================================
    # CHARGEMENT DES SPRITES VÉHICULES
    # ===================================================================
    def _build_vehicle_pixmaps(self) -> dict:
        """
        Construit les mini-sprites véhicules depuis le SVG de la planche,
        ou génère des formes colorées de secours si le fichier est absent.
        """
        project_root = Path(__file__).resolve().parent.parent
        svg_path     = project_root / "vehicle_models_top_view.svg"

        if svg_path.exists():
            renderer = QSvgRenderer(str(svg_path))
            if renderer.isValid():
                ds     = renderer.defaultSize()
                width  = ds.width()  if ds.width()  > 0 else 680
                height = ds.height() if ds.height() > 0 else 544

                canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.GlobalColor.transparent)
                p = QPainter(canvas)
                renderer.render(p)
                p.end()

                crop_rects = {
                    "car":   (66,  64,  108, 142),
                    "bus":   (394, 64,  132, 222),
                    "truck": (64,  362, 112, 176),
                }
                out = {}
                for name, (x, y, w, h) in crop_rects.items():
                    pm = QPixmap.fromImage(canvas.copy(x, y, w, h))
                    out[name] = pm.scaled(
                        max(1, int(pm.width()  * 0.24)),
                        max(1, int(pm.height() * 0.24)),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                return out

        # Fallback : formes colorées simples
        return {
            "car":   self._make_fallback_pixmap(QColor("#2980b9"), 18, 10),
            "bus":   self._make_fallback_pixmap(QColor("#f39c12"), 22, 12),
            "truck": self._make_fallback_pixmap(QColor("#546e7a"), 24, 12),
        }

    def _make_fallback_pixmap(self, color: QColor, w: int, h: int) -> QPixmap:
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(color))
        p.setPen(QPen(Qt.GlobalColor.black, 1))
        p.drawRoundedRect(0, 0, w - 1, h - 1, 3, 3)
        p.end()
        return pm

    # ===================================================================
    # RENDU DE LA CARTE
    # ===================================================================
    def _draw_map_once(self):
        """
        Dessine la carte du réseau routier :
          1. Blocs bâtiments (îlots entre intersections)
          2. Routes larges avec marquage central en pointillés
          3. Intersections (disques concentriques)
        """
        bg_color       = QColor("#d8e2dc")
        building_color = QColor("#b0bec5")
        road_color     = QColor("#2c3e50")
        lane_color     = QColor("#ecf0f1")
        cross_color    = QColor("#34495e")

        self.scene.setBackgroundBrush(QBrush(bg_color))

        road_pen = QPen(road_color)
        road_pen.setWidth(56)
        road_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        road_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        lane_pen = QPen(lane_color)
        lane_pen.setWidth(6)
        lane_pen.setStyle(Qt.PenStyle.DashLine)
        lane_pen.setDashPattern([16, 12])
        lane_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # ── 1) Bâtiments ─────────────────────────────────────────────────
        rows = self.G.graph.get("rows", 0)
        cols = self.G.graph.get("cols", 0)

        for r in range(rows):
            for c in range(cols):
                n1 = f"I_{r}_{c}"
                n2 = f"I_{r+1}_{c+1}"
                if n1 not in self.G.nodes or n2 not in self.G.nodes:
                    continue
                x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
                x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
                padding = 40
                w = (x2 - x1) - 2 * padding
                h = (y2 - y1) - 2 * padding
                if w <= 0 or h <= 0:
                    continue
                rect = self.scene.addRect(
                    x1 + padding, y1 + padding, w, h,
                    Qt.PenStyle.NoPen,
                    QBrush(building_color),
                )
                rect.setZValue(-2)

        # ── 2) Routes + marquage central ─────────────────────────────────
        drawn = set()
        for u, v, _k in self.G.edges(keys=True):
            key = tuple(sorted((u, v)))
            if key in drawn:
                continue
            drawn.add(key)
            x1, y1 = self.G.nodes[u]["x"], self.G.nodes[u]["y"]
            x2, y2 = self.G.nodes[v]["x"], self.G.nodes[v]["y"]

            road = QGraphicsLineItem(x1, y1, x2, y2)
            road.setPen(road_pen)
            road.setZValue(0)
            self.scene.addItem(road)

            lane = QGraphicsLineItem(x1, y1, x2, y2)
            lane.setPen(lane_pen)
            lane.setZValue(1)
            self.scene.addItem(lane)

        # ── 3) Intersections ─────────────────────────────────────────────
        for node_id in self.G.nodes:
            x, y = self.G.nodes[node_id]["x"], self.G.nodes[node_id]["y"]
            for d, col, z in [(30, cross_color, 2), (12, QColor("#90a4b2"), 3)]:
                ell = self.scene.addEllipse(
                    x - d / 2, y - d / 2, d, d,
                    Qt.PenStyle.NoPen,
                    QBrush(col),
                )
                ell.setZValue(z)

    def _fit_scene(self):
        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        )
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ===================================================================
    # BOUCLE D'ANIMATION
    # ===================================================================
    def _sprite_key(self, kind: str) -> str:
        """Associe le type de véhicule au sprite disponible."""
        if kind in ("bus",):    return "bus"
        if kind in ("truck",):  return "truck"
        return "car"   # car + suv

    def _dist_nearest_intersection(self, x: float, y: float) -> float:
        if not self._intersection_points:
            return float("inf")
        return min(math.hypot(x - nx, y - ny) for nx, ny in self._intersection_points)

    def _tick(self):
        """
        Tick principal d'animation :
          1. Avance la simulation (× speed_multiplier)
          2. Met à jour la position et l'orientation de chaque véhicule
          3. Supprime les items des véhicules disparus
          4. Rafraîchit le tableau de bord
        """
        try:
            if self.running:
                for _ in range(self.speed_multiplier):
                    self.sim.step()

            vehicle_data = self.sim.vehicle_render_data()
        except Exception as exc:
            self._last_tick_exception = exc
            tb = traceback.format_exc(limit=12)
            print("[UI] Exception in _tick():", repr(exc))
            print(tb)

            # Stopper l'animation pour éviter une boucle d'erreurs
            try:
                self.timer.stop()
            except Exception:
                pass
            self.running = False
            self.btn_play.setText("Play")

            # Afficher l'erreur dans le dashboard
            self.dashboard_label_main.setText(f"Erreur runtime : {exc}")
            self.dashboard_label_secondary.setText("Voir la console pour la trace.")
            self.dashboard_label_extra.setText("")
            return
        active_ids   = set()

        for i, v in enumerate(vehicle_data):
            active_ids.add(i)
            x    = float(v["x"])
            y    = float(v["y"])
            kind = v["kind"]

            lane_side = v.get("lane_side")
            if lane_side not in (-1, 1):
                if i not in self.lane_side_by_veh:
                    self.lane_side_by_veh[i] = -1 if (i % 2 == 0) else 1
                lane_side = self.lane_side_by_veh[i]
            sprite_key = self._sprite_key(kind)
            pixmap     = self.vehicle_pixmaps[sprite_key]

            # Création ou récupération de l'item graphique
            if i not in self.vehicle_items:
                item = QGraphicsPixmapItem(pixmap)
                item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
                item.setTransformOriginPoint(0, 0)
                item.setZValue(10)
                self.scene.addItem(item)
                self.vehicle_items[i] = item
            else:
                item = self.vehicle_items[i]
                if item.pixmap().cacheKey() != pixmap.cacheKey():
                    item.setPixmap(pixmap)
                    item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)

            # ── Calcul de la direction depuis l'arête courante ────────────
            ux, uy        = self.prev_dirs.get(i, (0.0, -1.0))
            target_angle  = self.prev_angles.get(i, 0.0)

            veh_obj = self.sim.vehicles[i] if i < len(self.sim.vehicles) else None
            if veh_obj is not None and veh_obj.edge_index < len(veh_obj.path) - 1:
                n1 = veh_obj.path[veh_obj.edge_index]
                n2 = veh_obj.path[veh_obj.edge_index + 1]
                x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
                x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]
                dx, dy  = x2 - x1, y2 - y1
                length  = math.hypot(dx, dy)
                if length > 1e-9:
                    ux, uy = dx / length, dy / length

                # Pré-virage : blend vers la direction de l'arête suivante
                p = float(getattr(veh_obj, "progress", 0.0))
                if p >= self.turn_blend_start and veh_obj.edge_index < len(veh_obj.path) - 2:
                    n3 = veh_obj.path[veh_obj.edge_index + 2]
                    x3, y3 = self.G.nodes[n3]["x"], self.G.nodes[n3]["y"]
                    ndx, ndy = x3 - x2, y3 - y2
                    nlen     = math.hypot(ndx, ndy)
                    if nlen > 1e-9:
                        nux, nuy = ndx / nlen, ndy / nlen
                        t    = (p - self.turn_blend_start) / max(1e-6, 1.0 - self.turn_blend_start)
                        bx   = (1.0 - t) * ux + t * nux
                        by   = (1.0 - t) * uy + t * nuy
                        blen = math.hypot(bx, by)
                        if blen > 1e-9:
                            ux, uy = bx / blen, by / blen

                self.prev_dirs[i] = (ux, uy)
                target_angle = math.degrees(math.atan2(uy, ux)) + 90.0

            elif i in self.prev_positions:
                px, py = self.prev_positions[i]
                dx, dy = x - px, y - py
                if abs(dx) + abs(dy) > 1e-6:
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length
                    self.prev_dirs[i] = (ux, uy)
                    target_angle = math.degrees(math.atan2(dy, dx)) + 90.0

            # Interpolation angulaire douce
            current_angle    = self.prev_angles.get(i, target_angle)
            delta            = (target_angle - current_angle + 180.0) % 360.0 - 180.0
            dist_to_cross    = self._dist_nearest_intersection(x, y)
            near_inter       = dist_to_cross < self.intersection_radius_px
            max_turn         = 7.0 if near_inter else self.max_turn_deg_per_tick
            new_angle        = current_angle + max(-max_turn, min(max_turn, delta))
            item.setRotation(new_angle)
            self.prev_angles[i] = new_angle

            # Décalage latéral (file gauche / droite)
            lx = -uy
            ly =  ux
            target_dx = x + lane_side * self.lane_offset_px * lx
            target_dy = y + lane_side * self.lane_offset_px * ly

            # Interpolation de position
            alpha = 0.35 if near_inter else 0.72
            if i in self.display_positions:
                pdx, pdy  = self.display_positions[i]
                display_x = pdx + alpha * (target_dx - pdx)
                display_y = pdy + alpha * (target_dy - pdy)
            else:
                display_x, display_y = target_dx, target_dy

            self.display_positions[i] = (display_x, display_y)
            item.setPos(display_x, display_y)
            self.prev_positions[i] = (x, y)

        # ── Suppression des véhicules disparus ───────────────────────────
        for vid in list(self.vehicle_items.keys()):
            if vid not in active_ids:
                self.scene.removeItem(self.vehicle_items.pop(vid))
                self.prev_positions.pop(vid, None)
                self.prev_dirs.pop(vid, None)
                self.prev_angles.pop(vid, None)
                self.display_positions.pop(vid, None)
                self.lane_side_by_veh.pop(vid, None)

        # ── Rafraîchissement du tableau de bord ──────────────────────────
        self._refresh_dashboard(len(vehicle_data))

        # ── Mise à jour des feux tricolores ─────────────────────────────
        self._update_traffic_lights_visual()

    def _get_signal_nodes_from_sim(self) -> list:
        nodes = getattr(self.sim, "signal_nodes", None)
        if nodes is None:
            return []
        try:
            return list(nodes)
        except Exception:
            return []

    def _create_traffic_lights_visual(self):
        """Crée des voyants (NS/EW) pour chaque intersection."""
        self._light_items.clear()

        # Synchronise à chaque création (au cas où sim.signal_nodes change)
        self._light_nodes = self._get_signal_nodes_from_sim()

        size = float(self._light_size_px)
        off = float(self._light_offset_px)

        for node_id in self._light_nodes:
            x = float(self.G.nodes[node_id]["x"])
            y = float(self.G.nodes[node_id]["y"])

            ns_item = self.scene.addEllipse(
                x - size / 2,
                y - off - size / 2,
                size,
                size,
                QPen(QColor("#1f1f1f"), 1),
                QBrush(QColor("#7f8c8d")),
            )
            ns_item.setZValue(50)

            ew_item = self.scene.addEllipse(
                x + off - size / 2,
                y - size / 2,
                size,
                size,
                QPen(QColor("#1f1f1f"), 1),
                QBrush(QColor("#7f8c8d")),
            )
            ew_item.setZValue(50)

            self._light_items[node_id] = (ns_item, ew_item)

    def _light_color(self, state: str) -> QColor:
        state = (state or "").lower()
        if state == "green":
            return QColor("#2ecc71")
        if state == "yellow":
            return QColor("#f1c40f")
        if state == "red":
            return QColor("#e74c3c")
        return QColor("#7f8c8d")

    def _update_traffic_lights_visual(self):
        """Met à jour la couleur des voyants NS/EW selon l'état des feux."""
        if not self._light_items:
            return

        enabled = bool(getattr(self.sim, "enable_traffic_lights", False))

        # Si feux désactivés, on cache totalement les voyants
        if not enabled:
            for ns_item, ew_item in self._light_items.values():
                ns_item.setVisible(False)
                ew_item.setVisible(False)
            return

        for ns_item, ew_item in self._light_items.values():
            ns_item.setVisible(True)
            ew_item.setVisible(True)

        snapshot = None
        if enabled and hasattr(self.sim, "traffic_lights_snapshot"):
            try:
                snapshot = self.sim.traffic_lights_snapshot()
            except Exception:
                snapshot = None

        for node_id, (ns_item, ew_item) in self._light_items.items():
            if not enabled or not snapshot or node_id not in snapshot:
                ns_item.setBrush(QBrush(QColor("#7f8c8d")))
                ew_item.setBrush(QBrush(QColor("#7f8c8d")))
                continue

            st = snapshot.get(node_id, {})
            ns_item.setBrush(QBrush(self._light_color(st.get("NS"))))
            ew_item.setBrush(QBrush(self._light_color(st.get("EW"))))

    def _refresh_dashboard(self, n_vehicles: int):
        """
        Met à jour le tableau de bord avec toutes les métriques :
          - État Markov (FLUIDE / RALENTI / BOUCHON)
          - Files d'attente moyennes et maximales
          - Phénomène observé (SATURATION FAIBLE / ATTENTE / CONGESTION)
          - Compteurs par type de véhicule
        """
        state  = self.sim.traffic_state()
        avg_q  = self.sim.avg_queue()
        max_q  = self.sim.max_queue()
        obs    = self.sim.queue_observation()
        tick   = self.sim.tick_count
        completed = int(getattr(self.sim, "completed_trips", 0) or 0)
        speed  = self.sim.avg_speed()
        speed_factor = float(getattr(self.sim, "current_speed_factor", 1.0))

        lights_enabled = bool(getattr(self.sim, "enable_traffic_lights", False))
        lights = "ON" if lights_enabled else "OFF"
        flow = float(self.sim.throughput_per_1000_ticks()) if hasattr(self.sim, "throughput_per_1000_ticks") else 0.0

        stops_total = 0
        wait_total = 0
        for veh in getattr(self.sim, "vehicles", []):
            stops_total += int(getattr(veh, "stops", 0) or 0)
            wait_total += int(getattr(veh, "wait_ticks", 0) or 0)
        avg_wait = (wait_total / max(1, n_vehicles)) if n_vehicles else 0.0

        reservations_on = bool(getattr(self.sim, "enable_intersection_reservations", False))
        reservations = "ON" if reservations_on else "OFF"

        # Distribution Markov récente (fenêtre courte)
        markov_recent_txt = "–"
        try:
            markov_obj = getattr(self.sim, "markov", None)
            hist = list(getattr(markov_obj, "history", []) or [])
            update_every = int(getattr(self.sim, "markov_update_every", 20) or 20)
            # Fenêtre ~200 ticks (en nombre de transitions Markov)
            window = max(5, int(200 / max(1, update_every)))
            recent = hist[-window:] if hist else []
            if recent:
                total = len(recent)
                f = 100.0 * (sum(1 for s in recent if s == "FLUIDE") / total)
                r = 100.0 * (sum(1 for s in recent if s == "RALENTI") / total)
                b = 100.0 * (sum(1 for s in recent if s == "BOUCHON") / total)
                markov_recent_txt = f"F {f:>3.0f}% | R {r:>3.0f}% | B {b:>3.0f}%"
        except Exception:
            pass

        cfg = getattr(self.sim, "light_config", {}) or {}
        cfg_txt = (
            f"G={cfg.get('green_seconds', '–')}s "
            f"Y={cfg.get('yellow_seconds', '–')}s "
            f"R={cfg.get('all_red_seconds', '–')}s "
            f"mode={cfg.get('offset_mode', '–')}"
        )

        # Top intersections par file (limité pour rester léger)
        top_txt = "–"
        if hasattr(self.sim, "queue_snapshot"):
            try:
                snap = self.sim.queue_snapshot() or {}
                items = [(k, int(v)) for k, v in snap.items()]
                items.sort(key=lambda kv: kv[1], reverse=True)
                top = [f"{k}:{v}" for k, v in items[:3] if v > 0]
                if top:
                    top_txt = ", ".join(top)
            except Exception:
                pass

        counts = {"car": 0, "suv": 0, "truck": 0, "bus": 0}
        for veh in self.sim.vehicles:
            counts[veh.kind] = counts.get(veh.kind, 0) + 1

        # Couleur selon l'état Markov
        state_colors = {
            "FLUIDE":  "#00c851",
            "RALENTI": "#ffbb33",
            "BOUCHON": "#ff4444",
        }
        color = state_colors.get(state, "#ffffff")

        self.info_label.setText(
            f"tick={tick} | véhicules={n_vehicles} | "
            f"C={counts['car']} SUV={counts['suv']} "
            f"T={counts['truck']} B={counts['bus']}"
        )

        self.dashboard_label_main.setText(
            f"État Markov : <span style='color:{color};font-weight:bold'>{state}</span>"
            f"  |  Vitesse : {speed:.4f} (×{speed_factor:.2f})"
            f"  |  Feux : {lights}"
            f"  |  Débit/1000 : {flow:.1f}"
            f"  |  Trips : {completed}"
        )
        self.dashboard_label_main.setTextFormat(Qt.TextFormat.RichText)

        self.dashboard_label_secondary.setText(
            f"Files : moy {avg_q:.2f} / max {max_q}  |  Obs : {obs}"
            f"  |  Attente : total {wait_total} (moy {avg_wait:.1f}/veh)"
            f"  |  Arrêts : {stops_total}"
            f"  |  Réservations : {reservations}"
        )

        signal_nodes = getattr(self.sim, "signal_nodes", None)
        n_signals = len(signal_nodes) if hasattr(signal_nodes, "__len__") else 0
        self.dashboard_label_extra.setText(
            f"Feux (config) : {cfg_txt}  |  Intersections à feux : {n_signals}"
            f"  |  Markov récent : {markov_recent_txt}"
            f"  |  Top files : {top_txt}"
        )

    # ===================================================================
    # BOUTONS
    # ===================================================================
    def _toggle_play(self):
        """Bascule entre lecture et pause."""
        self.running = not self.running
        self.btn_play.setText("Play" if not self.running else "Pause")

    def _reset_sim(self):
        """Réinitialise la simulation et nettoie le rendu."""
        self.sim.reset()
        for item in self.vehicle_items.values():
            self.scene.removeItem(item)
        self.vehicle_items.clear()
        self.prev_positions.clear()
        self.prev_dirs.clear()
        self.prev_angles.clear()
        self.display_positions.clear()
        self.lane_side_by_veh.clear()

    def _cycle_speed(self):
        """Passe la vitesse d'animation à ×1 → ×2 → ×4 → ×1."""
        cycle = {1: 2, 2: 4, 4: 1}
        self.speed_multiplier = cycle.get(self.speed_multiplier, 1)
        self.btn_speed.setText(f"Vitesse ×{self.speed_multiplier}")

    def _toggle_lights(self):
        """Active ou désactive les feux tricolores."""
        new_state = not getattr(self.sim, "enable_traffic_lights", False)
        if hasattr(self.sim, "configure_traffic_lights"):
            self.sim.configure_traffic_lights(enabled=new_state)
        else:
            self.sim.enable_traffic_lights = new_state
        state = "ON" if getattr(self.sim, "enable_traffic_lights", False) else "OFF"
        self.btn_lights.setText(f"Feux : {state}")
        self._update_traffic_lights_visual()

    def _optimize_lights(self):
        """Lance l'optimisation des feux (Module 4) sans bloquer l'IHM."""
        if self._optim_thread is not None and self._optim_thread.is_alive():
            return

        self._optim_result = None
        self._optim_error = None
        self.btn_opt.setEnabled(False)
        self.btn_opt.setText("Optimisation…")
        self.dashboard_label_main.setText("Optimisation des feux en cours…")
        self.dashboard_label_secondary.setText("")
        self.dashboard_label_extra.setText("")

        def _worker():
            try:
                n_veh = len(self.sim.vehicles) if getattr(self.sim, "vehicles", None) else 30
                runs = 6
                n_ticks = 450
                best, _all_results = optimize_lights_grid(
                    self.G,
                    runs=runs,
                    n_ticks=n_ticks,
                    n_vehicles=max(10, int(n_veh)),
                )
                baseline = evaluate_baseline_no_lights(
                    self.G,
                    runs=max(4, runs // 2),
                    n_ticks=n_ticks,
                    n_vehicles=max(10, int(n_veh)),
                )
                self._optim_result = {"best": best, "baseline": baseline}
            except Exception as exc:
                self._optim_error = exc

        self._optim_thread = threading.Thread(target=_worker, daemon=True)
        self._optim_thread.start()

        if self._optim_poll_timer is None:
            self._optim_poll_timer = QTimer(self)
            self._optim_poll_timer.setInterval(120)
            self._optim_poll_timer.timeout.connect(self._poll_optimization)
        self._optim_poll_timer.start()

    def _poll_optimization(self):
        if self._optim_error is not None:
            self._optim_poll_timer.stop()
            self.btn_opt.setEnabled(True)
            self.btn_opt.setText("Optimiser feux")
            self.dashboard_label_main.setText(f"Optimisation – erreur : {self._optim_error}")
            return

        if self._optim_result is None:
            return

        self._optim_poll_timer.stop()
        payload = self._optim_result
        best = payload.get("best", {}) if isinstance(payload, dict) else payload
        baseline = payload.get("baseline", {}) if isinstance(payload, dict) else {}
        plan = best.get("plan", {}) if isinstance(best, dict) else {}

        if hasattr(self.sim, "configure_traffic_lights"):
            self.sim.configure_traffic_lights(
                enabled=True,
                green_seconds=plan.get("green_seconds"),
                yellow_seconds=plan.get("yellow_seconds"),
                all_red_seconds=plan.get("all_red_seconds"),
                offset_mode=plan.get("offset_mode"),
            )
        else:
            self.sim.enable_traffic_lights = True

        self.btn_lights.setText("Feux : ON")
        self.btn_opt.setEnabled(True)
        self.btn_opt.setText("Optimiser feux")

        score = (best.get("score_mean", 0.0) if isinstance(best, dict) else 0.0) or 0.0
        self.dashboard_label_main.setText(
            "Plan feux appliqué : "
            f"G={plan.get('green_seconds')}s "
            f"Y={plan.get('yellow_seconds')}s "
            f"R={plan.get('all_red_seconds')}s "
            f"mode={plan.get('offset_mode')} "
            f"| score={score:.3f}"
        )

        try:
            bq = float(baseline.get("avg_queue_mean", 0.0) or 0.0)
            bw = float(baseline.get("wait_total_mean", 0.0) or 0.0)
            bf = float(baseline.get("throughput_1000_mean", 0.0) or 0.0)

            oq = float(best.get("avg_queue_mean", 0.0) or 0.0)
            ow = float(best.get("wait_total_mean", 0.0) or 0.0)
            of = float(best.get("throughput_1000_mean", 0.0) or 0.0)

            dq = oq - bq
            dw = ow - bw
            df = of - bf
            self.dashboard_label_secondary.setText(
                "Comparaison (moyennes) — "
                f"File: {bq:.2f} → {oq:.2f} ({dq:+.2f})  |  "
                f"Attente: {bw:.0f} → {ow:.0f} ({dw:+.0f})  |  "
                f"Débit/1000: {bf:.1f} → {of:.1f} ({df:+.1f})"
            )
        except Exception:
            self.dashboard_label_secondary.setText("Comparaison baseline/optimisé : indisponible")

        self.dashboard_label_extra.setText("(Le tableau de bord temps réel reprend au tick suivant)")

        # Laisse le refresh normal reprendre au tick suivant

    def _run_monte_carlo(self):
        """
        Lance une analyse Monte Carlo (Module 3) et affiche le résumé
        dans le tableau de bord.
        """
        n_veh = len(self.sim.vehicles) if self.sim.vehicles else 10
        self.dashboard_label_main.setText("Monte Carlo en cours…")
        self.dashboard_label_secondary.setText("")
        self.dashboard_label_extra.setText("")
        try:
            runs = 20
            n_ticks = 300
            res = monte_carlo(self.G, runs=runs, n_ticks=n_ticks, n_vehicles=n_veh)

            # Stocke pour export
            self._last_mc_result = res
            self._last_mc_meta = {
                "created_at": datetime.now(),
                "runs": int(runs),
                "n_ticks": int(n_ticks),
                "n_vehicles": int(n_veh),
                "lights_enabled": bool(getattr(self.sim, "enable_traffic_lights", False)),
                "light_config": dict(getattr(self.sim, "light_config", {}) or {}),
                "reservations_enabled": bool(getattr(self.sim, "enable_intersection_reservations", False)),
                "reservation_scope": str(getattr(self.sim, "reservation_scope", "")),
                "occupancy_enabled": bool(getattr(self.sim, "enable_intersection_occupancy", False)),
                "graph_nodes": int(len(getattr(self.G, "nodes", []))),
                "graph_edges": int(len(getattr(self.G, "edges", []))),
            }
            self.btn_export.setEnabled(True)

            self.dashboard_label_main.setText(
                f"MC runs={res['runs']} | "
                f"avg_q={res['avg_queue_mean']:.2f} "
                f"[{res['avg_queue_min']:.2f} – {res['avg_queue_max']:.2f}] | "
                f"max_q moy={res['max_queue_mean']:.2f} | "
                f"états={res['state_counts']} | "
                f"obs={res.get('obs_counts', {})}"
            )
        except Exception as exc:
            self.dashboard_label_main.setText(f"Monte Carlo – erreur : {exc}")

    def _export_monte_carlo_pdf(self):
        """Exporte le dernier résultat Monte Carlo en PDF à la racine du projet (option A)."""
        if not self._last_mc_result:
            self.dashboard_label_main.setText("Export PDF : lance Monte Carlo d'abord")
            self.dashboard_label_secondary.setText("")
            self.dashboard_label_extra.setText("")
            return

        try:
            from matplotlib.backends.backend_pdf import PdfPages
            import matplotlib.pyplot as plt
        except Exception as exc:
            self.dashboard_label_main.setText(f"Export PDF : matplotlib indisponible ({exc})")
            self.dashboard_label_secondary.setText("Installe les dépendances puis réessaie")
            self.dashboard_label_extra.setText("")
            return

        project_root = Path(__file__).resolve().parent.parent
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = project_root / f"monte_carlo_report_{ts}.pdf"

        res = self._last_mc_result
        meta = self._last_mc_meta or {}
        details = list(res.get("details", []) or [])

        def _safe_get(d: dict, key: str, default=0.0):
            try:
                return d.get(key, default)
            except Exception:
                return default

        # --- Page 1 : Résumé texte ---
        with PdfPages(out_path) as pdf:
            fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape approx
            fig.suptitle("Rapport Monte Carlo — Simulation de trafic", fontsize=16, fontweight="bold")
            ax = fig.add_subplot(111)
            ax.axis("off")

            created_at = meta.get("created_at")
            created_txt = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else ts
            lights_enabled = bool(meta.get("lights_enabled", False))
            cfg = meta.get("light_config", {}) or {}
            cfg_txt = (
                f"G={cfg.get('green_seconds', '–')}s, "
                f"Y={cfg.get('yellow_seconds', '–')}s, "
                f"R={cfg.get('all_red_seconds', '–')}s, "
                f"mode={cfg.get('offset_mode', '–')}"
            )

            lines = [
                f"Date/heure : {created_txt}",
                f"Graphe : {meta.get('graph_nodes', '–')} nœuds, {meta.get('graph_edges', '–')} arêtes",
                f"Paramètres : runs={meta.get('runs', '–')}, n_ticks={meta.get('n_ticks', '–')}, n_vehicles={meta.get('n_vehicles', '–')}",
                f"Règles : feux={'ON' if lights_enabled else 'OFF'} | config feux: {cfg_txt}",
                f"Règles : réservations={'ON' if meta.get('reservations_enabled') else 'OFF'} (scope={meta.get('reservation_scope','–')}) | occupancy={'ON' if meta.get('occupancy_enabled') else 'OFF'}",
                "",
                "Résumé (moyennes / extrêmes) :",
                f"- Vitesse moyenne : mean={res.get('avg_speed_mean', 0.0):.5f}  min={res.get('avg_speed_min', 0.0):.5f}  max={res.get('avg_speed_max', 0.0):.5f}",
                f"- File moyenne   : mean={res.get('avg_queue_mean', 0.0):.2f}   min={res.get('avg_queue_min', 0.0):.2f}   max={res.get('avg_queue_max', 0.0):.2f}",
                f"- File max       : mean={res.get('max_queue_mean', 0.0):.2f}   min={res.get('max_queue_min', 0.0):.0f}   max={res.get('max_queue_max', 0.0):.0f}",
                f"- Attente totale : mean={res.get('wait_total_mean', 0.0):.0f}  min={res.get('wait_total_min', 0.0):.0f}  max={res.get('wait_total_max', 0.0):.0f}",
                f"- Arrêts totaux  : mean={res.get('stops_total_mean', 0.0):.0f} min={res.get('stops_total_min', 0.0):.0f} max={res.get('stops_total_max', 0.0):.0f}",
                f"- Débit/1000     : mean={res.get('throughput_mean', 0.0):.1f}  min={res.get('throughput_min', 0.0):.1f}  max={res.get('throughput_max', 0.0):.1f}",
                "",
                f"États Markov (finaux) : {res.get('state_counts', {})}",
                f"Phénomènes (Module 2) : {res.get('obs_counts', {})}",
            ]
            ax.text(0.02, 0.96, "\n".join(lines), va="top", ha="left", fontsize=11, family="monospace")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

            # --- Page 2 : Graphiques distributions ---
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.suptitle("Distributions (runs)", fontsize=14, fontweight="bold")
            gs = fig.add_gridspec(2, 2)

            # Etats Markov
            ax1 = fig.add_subplot(gs[0, 0])
            state_counts = dict(res.get("state_counts", {}) or {})
            states = ["FLUIDE", "RALENTI", "BOUCHON"]
            vals = [int(state_counts.get(s, 0)) for s in states]
            ax1.bar(states, vals)
            ax1.set_title("États Markov (finaux)")
            ax1.set_ylabel("Runs")

            # Observations
            ax2 = fig.add_subplot(gs[0, 1])
            obs_counts = dict(res.get("obs_counts", {}) or {})
            obs_labels = list(obs_counts.keys())
            obs_vals = [int(obs_counts[k]) for k in obs_labels]
            ax2.bar(range(len(obs_labels)), obs_vals)
            ax2.set_title("Phénomènes (files d'attente)")
            ax2.set_ylabel("Runs")
            ax2.set_xticks(range(len(obs_labels)))
            ax2.set_xticklabels(obs_labels, rotation=15, ha="right")

            # Throughput distribution (simple)
            ax3 = fig.add_subplot(gs[1, :])
            thr = [float(_safe_get(d, "throughput", 0.0)) for d in details]
            if thr:
                ax3.hist(thr, bins=min(12, max(4, len(thr) // 2)))
            ax3.set_title("Débit/1000 — distribution")
            ax3.set_xlabel("Trajets / 1000 ticks")
            ax3.set_ylabel("Runs")

            fig.tight_layout(rect=[0, 0, 1, 0.95])
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

            # --- Pages suivantes : table détails run par run ---
            if not details:
                fig = plt.figure(figsize=(11.69, 8.27))
                ax = fig.add_subplot(111)
                ax.axis("off")
                ax.text(0.02, 0.95, "Aucun détail run-par-run disponible.", va="top")
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)
            else:
                rows_per_page = 26
                headers = [
                    "run", "seed", "avg_q", "max_q", "wait", "stops", "thr/1000", "state", "obs"
                ]
                for page_start in range(0, len(details), rows_per_page):
                    chunk = details[page_start: page_start + rows_per_page]
                    table_rows = []
                    for i, d in enumerate(chunk, start=page_start):
                        table_rows.append([
                            i,
                            int(_safe_get(d, "seed", 0)),
                            f"{float(_safe_get(d, 'avg_queue', 0.0)):.2f}",
                            int(_safe_get(d, "max_queue", 0)),
                            int(_safe_get(d, "wait_total", 0)),
                            int(_safe_get(d, "stops_total", 0)),
                            f"{float(_safe_get(d, 'throughput', 0.0)):.1f}",
                            str(_safe_get(d, "state", "")),
                            str(_safe_get(d, "obs", "")),
                        ])

                    fig = plt.figure(figsize=(11.69, 8.27))
                    fig.suptitle("Détails run par run", fontsize=14, fontweight="bold")
                    ax = fig.add_subplot(111)
                    ax.axis("off")
                    tbl = ax.table(
                        cellText=table_rows,
                        colLabels=headers,
                        loc="upper left",
                        cellLoc="center",
                    )
                    tbl.auto_set_font_size(False)
                    tbl.set_fontsize(9)
                    tbl.scale(1.0, 1.2)
                    ax.text(0.02, -0.03, f"Lignes {page_start} à {page_start + len(chunk) - 1}", transform=ax.transAxes)
                    fig.tight_layout(rect=[0, 0.02, 1, 0.93])
                    pdf.savefig(fig, bbox_inches="tight")
                    plt.close(fig)

        self.dashboard_label_main.setText(f"Export PDF OK : {out_path.name}")
        self.dashboard_label_secondary.setText("(Fichier enregistré à la racine du projet)")
        self.dashboard_label_extra.setText("")