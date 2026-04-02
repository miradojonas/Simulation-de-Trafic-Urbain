from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
from data_loader import load_graph_from_osm_xml, extract_place_labels, load_places_from_geojson
from simulation import TrafficSimulation
from ui import TrafficWindow

def main():
    # Fichier OSM XML : on privilégie un sous-dataset plus léger
    osm_xml = Path("antananarivo_core.osm")
    if not osm_xml.exists():
        osm_xml = Path("antananarivo.osm")

    if not osm_xml.exists():
        raise FileNotFoundError(
            "Aucun fichier OSM trouvé. "
            "Attendu: antananarivo_core.osm ou antananarivo.osm."
        )

    # Chargement graphe + simulation
    G = load_graph_from_osm_xml(str(osm_xml))
    places = load_places_from_geojson("antananarivo_places.geojson")

    sim = TrafficSimulation(G, n_vehicles=10, seed=123)

    # Lancement interface Qt
    app = QApplication(sys.argv)
    window = TrafficWindow(G, sim, places=places)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()