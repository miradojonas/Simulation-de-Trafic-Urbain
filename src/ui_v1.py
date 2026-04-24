# ui_v1.py
# ------------------------------------------------------------
# Fenêtre V1:
# - dessine la carte (routes)
# - affiche des mini-voitures (pixmaps) au lieu de points
# - oriente chaque véhicule selon sa direction de déplacement
# - boutons: Play/Pause, Reset, Vitesse
# ------------------------------------------------------------

import math
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPixmap, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TrafficV1Window(QMainWindow):
    def __init__(self, G, sim):
        super().__init__()
        self.G = G
        self.sim = sim

        self.setWindowTitle("Traffic V1 - Mini voitures orientées")
        # Agrandir la fenêtre pour remplir davantage l'interface.
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.resize(screen.availableGeometry().size() * 0.92)
        else:
            self.resize(1400, 900)

        # Etat lecture + vitesse
        self.running = True
        self.speed_multiplier = 1  # x1 -> x2 -> x4

        # Dictionnaires runtime:
        # - vehicle_items: id -> item graphique du véhicule
        # - prev_positions: id -> (x, y) position précédente (pour angle)
        self.vehicle_items = {}
        self.prev_positions = {}
        self.prev_dirs = {}
        self.prev_angles = {}
        self.display_positions = {}
        # Affectation de file par véhicule: -1 (gauche) / +1 (droite)
        self.lane_side_by_vehicle = {}
        # Décalage latéral en pixels depuis l'axe médian de la route
        self.lane_offset_px = 12.0
        # Limite de rotation par tick pour un virage visuellement fluide
        self.max_turn_deg_per_tick = 12.0
        # Paramètres de fluidité visuelle
        self.base_interp_alpha = 0.42
        self.intersection_interp_alpha = 0.20
        self.intersection_radius_px = 40.0
        self.turn_blend_start = 0.70
        # Cache des coordonnées d'intersections pour le calcul de proximité
        self._intersection_points = [
            (float(self.G.nodes[n]["x"]), float(self.G.nodes[n]["y"]))
            for n in self.G.nodes
        ]

        # Charger les pixmaps véhicules (car, bus, truck)
        self.vehicle_pixmaps = self._build_vehicle_pixmaps()

        # ---------- UI root ----------
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Barre de contrôle
        controls = QHBoxLayout()
        self.btn_play = QPushButton("Pause")
        self.btn_reset = QPushButton("Reset")
        self.btn_speed = QPushButton("Vitesse x1")
        self.info = QLabel("tick=0 | vehicles=0 | state=-")

        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_reset)
        controls.addWidget(self.btn_speed)
        controls.addStretch(1)
        controls.addWidget(self.info)
        layout.addLayout(controls)

        # Scene + View
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor("#e9f4e9")))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        layout.addWidget(self.view, 1)

        # Dessiner les routes une seule fois
        self._draw_map_once()
        self._fit_scene()

        # Connecter les boutons
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_reset.clicked.connect(self._reset_sim)
        self.btn_speed.clicked.connect(self._cycle_speed)

        # Timer d'animation (~30 FPS)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # -----------------------------------------------------------------
    # CHARGEMENT SPRITES
    # -----------------------------------------------------------------
    def _build_vehicle_pixmaps(self):
        """
        Construit les mini-voitures:
        - priorité: découpe depuis vehicle_models_top_view.svg si présent
        - fallback: pixmaps simples colorés (si le fichier manque)
        """
        project_root = Path(__file__).resolve().parent.parent
        svg_path = project_root / "vehicle_models_top_view.svg"

        if svg_path.exists():
            renderer = QSvgRenderer(str(svg_path))
            if renderer.isValid():
                default_size = renderer.defaultSize()
                width = default_size.width() if default_size.width() > 0 else 680
                height = default_size.height() if default_size.height() > 0 else 544

                # Rendu du SVG complet sur image
                canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.GlobalColor.transparent)

                painter = QPainter(canvas)
                renderer.render(painter)
                painter.end()

                # Zones de découpe des modèles sur votre planche SVG
                crop_rects = {
                    "car": (66, 64, 108, 142),
                    "bus": (394, 64, 132, 222),
                    "truck": (64, 362, 112, 176),
                }

                out = {}
                for name, (x, y, w, h) in crop_rects.items():
                    pm = QPixmap.fromImage(canvas.copy(x, y, w, h))
                    # Réduction pour mini-voitures
                    out[name] = pm.scaled(
                        max(1, int(pm.width() * 0.24)),
                        max(1, int(pm.height() * 0.24)),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                return out

        # Fallback propre si SVG absent/invalide
        return {
            "car": self._make_fallback_pixmap(QColor("#2980b9"), 18, 10),
            "bus": self._make_fallback_pixmap(QColor("#f39c12"), 22, 12),
            "truck": self._make_fallback_pixmap(QColor("#546e7a"), 24, 12),
        }

    def _make_fallback_pixmap(self, color: QColor, w: int, h: int) -> QPixmap:
        """
        Crée une mini-forme simple (fallback) pour éviter un crash visuel.
        """
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(color))
        p.setPen(QPen(Qt.GlobalColor.black, 1))
        p.drawRoundedRect(0, 0, w - 1, h - 1, 3, 3)
        p.end()
        return pm

    # -----------------------------------------------------------------
    # CARTE
    # -----------------------------------------------------------------
    def _draw_map_once(self):
        """
        Rendu stylisé de la carte NetworkX:
        - bâtiments (îlots)
        - routes épaisses
        - marquage central
        - intersections
        Inspiré visuellement de urban_map_6x6_large.svg
        """

        # Palette "urbaine" inspirée du SVG
        bg_color = QColor("#d8e2dc")         # fond global doux
        building_color = QColor("#b0bec5")   # blocs bâtiments
        road_color = QColor("#2c3e50")       # route principale
        lane_color = QColor("#ecf0f1")       # marquage central
        cross_color = QColor("#34495e")      # intersections

        self.scene.setBackgroundBrush(QBrush(bg_color))

        # Épaisseur de route
        road_pen = QPen(road_color)
        # Route encore plus large pour un rendu 2 files très clair.
        road_pen.setWidth(56)
        road_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        road_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # Marquage central (ligne claire)
        lane_pen = QPen(lane_color)
        # Ligne centrale très visible pour bien séparer les 2 files.
        lane_pen.setWidth(6)
        lane_pen.setStyle(Qt.PenStyle.DashLine)
        lane_pen.setDashPattern([16, 12])
        lane_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        building_brush = QBrush(building_color)

        # ------------------------------------------------
        # 1) BÂTIMENTS (dessinés d'abord, sous les routes)
        # ------------------------------------------------
        rows = self.G.graph["rows"]
        cols = self.G.graph["cols"]

        for r in range(rows):
            for c in range(cols):
                n1 = f"I_{r}_{c}"
                n2 = f"I_{r+1}_{c+1}"

                x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
                x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]

                # padding intérieur pour laisser passer les routes
                # Padding plus grand pour laisser des routes très larges autour des blocs.
                padding = 40

                w = (x2 - x1) - 2 * padding
                h = (y2 - y1) - 2 * padding
                if w <= 0 or h <= 0:
                    continue

                rect = self.scene.addRect(x1 + padding, y1 + padding, w, h)
                rect.setBrush(building_brush)
                rect.setPen(Qt.PenStyle.NoPen)
                rect.setZValue(-2)

        # -------------------------
        # 2) ROUTES + MARQUAGE
        # -------------------------
        drawn = set()
        for u, v, _k in self.G.edges(keys=True):
            edge_key = tuple(sorted((u, v)))
            if edge_key in drawn:
                continue
            drawn.add(edge_key)

            x1, y1 = self.G.nodes[u]["x"], self.G.nodes[u]["y"]
            x2, y2 = self.G.nodes[v]["x"], self.G.nodes[v]["y"]

            # route large
            road = QGraphicsLineItem(x1, y1, x2, y2)
            road.setPen(road_pen)
            road.setZValue(0)
            self.scene.addItem(road)

            # ligne centrale
            lane = QGraphicsLineItem(x1, y1, x2, y2)
            lane.setPen(lane_pen)
            lane.setZValue(1)
            self.scene.addItem(lane)

        # -------------------------
        # 3) INTERSECTIONS
        # -------------------------
        inter_outer_brush = QBrush(cross_color)
        inter_inner_brush = QBrush(QColor("#90a4b2"))
        inter_pen = QPen(Qt.PenStyle.NoPen)

        for node_id in self.G.nodes:
            x, y = self.G.nodes[node_id]["x"], self.G.nodes[node_id]["y"]
            # Intersection plus propre: disque externe + noyau interne.
            d_outer = 30
            outer = self.scene.addEllipse(
                x - d_outer / 2,
                y - d_outer / 2,
                d_outer,
                d_outer,
                inter_pen,
                inter_outer_brush,
            )
            outer.setZValue(2)

            d_inner = 12
            inner = self.scene.addEllipse(
                x - d_inner / 2,
                y - d_inner / 2,
                d_inner,
                d_inner,
                inter_pen,
                inter_inner_brush,
            )
            inner.setZValue(3)

    def _fit_scene(self):
        """
        Cadre la vue sur tout le contenu.
        """
        # Marges réduites pour que la carte remplisse mieux la fenêtre.
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # -----------------------------------------------------------------
    # MAPPING TYPE -> SPRITE
    # -----------------------------------------------------------------
    def _sprite_key_for_kind(self, kind: str) -> str:
        """
        kind vient de simulation.py: car / suv / truck / bus
        """
        if kind == "bus":
            return "bus"
        if kind == "truck":
            return "truck"
        # suv + car => modèle car pour V1
        return "car"

    def _distance_to_nearest_intersection(self, x: float, y: float) -> float:
        """Distance euclidienne au nœud d'intersection le plus proche."""
        if not self._intersection_points:
            return float("inf")
        return min(math.hypot(x - nx, y - ny) for nx, ny in self._intersection_points)

    # -----------------------------------------------------------------
    # BOUCLE TEMPS
    # -----------------------------------------------------------------
    def _tick(self):
        """
        Tick d'animation:
        1) avance simulation
        2) met à jour/crée les items véhicules
        3) calcule rotation avec position précédente
        4) nettoie les items disparus
        """
        if self.running:
            for _ in range(self.speed_multiplier):
                self.sim.step()

        vehicle_data = self.sim.vehicle_render_data()
        active_ids = set()

        for i, v in enumerate(vehicle_data):
            active_ids.add(i)
            x = float(v["x"])
            y = float(v["y"])
            kind = v["kind"]

            # Attribution stable de la file (gauche/droite) par véhicule.
            if i not in self.lane_side_by_vehicle:
                self.lane_side_by_vehicle[i] = -1 if (i % 2 == 0) else 1
            lane_side = self.lane_side_by_vehicle[i]

            sprite_key = self._sprite_key_for_kind(kind)
            pixmap = self.vehicle_pixmaps[sprite_key]

            # Création item si nouveau
            if i not in self.vehicle_items:
                item = QGraphicsPixmapItem(pixmap)
                # Centre le sprite sur (x, y)
                item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
                # Pivot au centre pour rotation naturelle
                item.setTransformOriginPoint(0, 0)
                item.setZValue(2)
                self.scene.addItem(item)
                self.vehicle_items[i] = item
            else:
                item = self.vehicle_items[i]
                # Si type change, on met à jour le sprite
                if item.pixmap().cacheKey() != pixmap.cacheKey():
                    item.setPixmap(pixmap)
                    item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)

            # Direction locale basée sur la géométrie réelle de l'arête courante
            # (plus stable que le delta de position visuel).
            ux, uy = self.prev_dirs.get(i, (0.0, -1.0))
            target_angle = self.prev_angles.get(i, 0.0)

            veh_obj = self.sim.vehicles[i] if i < len(self.sim.vehicles) else None
            if veh_obj is not None and veh_obj.edge_index < len(veh_obj.path) - 1:
                n1 = veh_obj.path[veh_obj.edge_index]
                n2 = veh_obj.path[veh_obj.edge_index + 1]
                x1, y1 = self.G.nodes[n1]["x"], self.G.nodes[n1]["y"]
                x2, y2 = self.G.nodes[n2]["x"], self.G.nodes[n2]["y"]

                dx = x2 - x1
                dy = y2 - y1
                length = math.hypot(dx, dy)
                if length > 1e-9:
                    ux, uy = dx / length, dy / length

                # Pré-virage fluide: on blend vers la direction de l'arête suivante
                # quand on approche d'une intersection.
                p = float(getattr(veh_obj, "progress", 0.0))
                if p >= self.turn_blend_start and veh_obj.edge_index < len(veh_obj.path) - 2:
                    n3 = veh_obj.path[veh_obj.edge_index + 2]
                    x3, y3 = self.G.nodes[n3]["x"], self.G.nodes[n3]["y"]
                    ndx = x3 - x2
                    ndy = y3 - y2
                    nlen = math.hypot(ndx, ndy)
                    if nlen > 1e-9:
                        nux, nuy = ndx / nlen, ndy / nlen
                        t = (p - self.turn_blend_start) / max(1e-6, (1.0 - self.turn_blend_start))
                        bx = (1.0 - t) * ux + t * nux
                        by = (1.0 - t) * uy + t * nuy
                        blen = math.hypot(bx, by)
                        if blen > 1e-9:
                            ux, uy = bx / blen, by / blen

                self.prev_dirs[i] = (ux, uy)
                target_angle = math.degrees(math.atan2(uy, ux)) + 90.0
            elif i in self.prev_positions:
                # Fallback si données véhicule indisponibles
                px, py = self.prev_positions[i]
                dx = x - px
                dy = y - py
                if abs(dx) + abs(dy) > 1e-6:
                    length = math.hypot(dx, dy)
                    ux, uy = dx / length, dy / length
                    self.prev_dirs[i] = (ux, uy)
                    target_angle = math.degrees(math.atan2(dy, dx)) + 90.0

            # Interpolation angulaire (évite les rotations "d'un coup")
            current_angle = self.prev_angles.get(i, target_angle)
            delta = (target_angle - current_angle + 180.0) % 360.0 - 180.0
            dist_to_cross = self._distance_to_nearest_intersection(x, y)
            near_intersection = dist_to_cross < self.intersection_radius_px
            max_turn = 7.0 if near_intersection else self.max_turn_deg_per_tick
            turn_step = max(-max_turn, min(max_turn, delta))
            new_angle = current_angle + turn_step
            item.setRotation(new_angle)
            self.prev_angles[i] = new_angle

            # Décalage latéral pour placer chaque véhicule dans une file
            # (à gauche ou à droite) au lieu du milieu.
            nx, ny = -uy, ux
            target_display_x = x + lane_side * self.lane_offset_px * nx
            target_display_y = y + lane_side * self.lane_offset_px * ny

            # Interpolation de position: plus lente au voisinage des intersections
            # pour rendre les virages plus naturels/moins brusques.
            alpha = 0.35 if near_intersection else 0.72
            if i in self.display_positions:
                px_disp, py_disp = self.display_positions[i]
                display_x = px_disp + alpha * (target_display_x - px_disp)
                display_y = py_disp + alpha * (target_display_y - py_disp)
            else:
                display_x, display_y = target_display_x, target_display_y
            self.display_positions[i] = (display_x, display_y)

            # Position actuelle (toujours appliquée)
            item.setPos(display_x, display_y)
            self.prev_positions[i] = (x, y)

        # Suppression items obsolètes
        for vid in list(self.vehicle_items.keys()):
            if vid not in active_ids:
                self.scene.removeItem(self.vehicle_items[vid])
                del self.vehicle_items[vid]
                self.prev_positions.pop(vid, None)
                self.prev_dirs.pop(vid, None)
                self.prev_angles.pop(vid, None)
                self.display_positions.pop(vid, None)
                self.lane_side_by_vehicle.pop(vid, None)

        # Infos UI
        self.info.setText(
            f"tick={self.sim.tick_count} | vehicles={len(vehicle_data)} | state={self.sim.traffic_state()}"
        )

    # -----------------------------------------------------------------
    # BOUTONS
    # -----------------------------------------------------------------
    def _toggle_play(self):
        self.running = not self.running
        self.btn_play.setText("Play" if not self.running else "Pause")

    def _reset_sim(self):
        self.sim.reset()
        for item in self.vehicle_items.values():
            self.scene.removeItem(item)
        self.vehicle_items.clear()
        self.prev_positions.clear()
        self.prev_dirs.clear()
        self.prev_angles.clear()
        self.display_positions.clear()
        self.lane_side_by_vehicle.clear()

    def _cycle_speed(self):
        if self.speed_multiplier == 1:
            self.speed_multiplier = 2
        elif self.speed_multiplier == 2:
            self.speed_multiplier = 4
        else:
            self.speed_multiplier = 1
        self.btn_speed.setText(f"Vitesse x{self.speed_multiplier}")