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
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap, QPen
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
        self.resize(1200, 850)

        # Etat lecture + vitesse
        self.running = True
        self.speed_multiplier = 1  # x1 -> x2 -> x4

        # Dictionnaires runtime:
        # - vehicle_items: id -> item graphique du véhicule
        # - prev_positions: id -> (x, y) position précédente (pour angle)
        self.vehicle_items = {}
        self.prev_positions = {}

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
        Dessine les routes du graphe une seule fois.
        """
        road_pen = QPen(QColor("#607d8b"))
        road_pen.setWidth(3)

        drawn = set()
        for u, v, _k in self.G.edges(keys=True):
            edge_key = tuple(sorted((u, v)))  # évite doublons A<->B
            if edge_key in drawn:
                continue
            drawn.add(edge_key)

            x1, y1 = self.G.nodes[u]["x"], self.G.nodes[u]["y"]
            x2, y2 = self.G.nodes[v]["x"], self.G.nodes[v]["y"]

            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(road_pen)
            line.setZValue(0)
            self.scene.addItem(line)

    def _fit_scene(self):
        """
        Cadre la vue sur tout le contenu.
        """
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
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

            # Rotation basée sur déplacement
            # prev -> current
            if i in self.prev_positions:
                px, py = self.prev_positions[i]
                dx = x - px
                dy = y - py

                # Eviter rotation instable si déplacement trop faible
                if abs(dx) + abs(dy) > 1e-6:
                    angle_deg = math.degrees(math.atan2(dy, dx))
                    # Le sprite "regarde" vers le haut dans la planche,
                    # donc on ajoute +90° pour aligner avec axe X de Qt.
                    item.setRotation(angle_deg + 90.0)

            # Position actuelle
            item.setPos(x, y)
            self.prev_positions[i] = (x, y)

        # Suppression items obsolètes
        for vid in list(self.vehicle_items.keys()):
            if vid not in active_ids:
                self.scene.removeItem(self.vehicle_items[vid])
                del self.vehicle_items[vid]
                self.prev_positions.pop(vid, None)

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

    def _cycle_speed(self):
        if self.speed_multiplier == 1:
            self.speed_multiplier = 2
        elif self.speed_multiplier == 2:
            self.speed_multiplier = 4
        else:
            self.speed_multiplier = 1
        self.btn_speed.setText(f"Vitesse x{self.speed_multiplier}")