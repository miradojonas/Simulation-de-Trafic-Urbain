"""
Charge le graphe routier depuis un fichier OSM XML local
"""

from pathlib import Path
import math
import osmnx as ox


DEFAULT_SPEED_KPH = 30.0
DEFAULT_LENGTH_M = 1.0


def _to_valid_positive_float(value, default_value: float) -> float:
    """Convertit une valeur en float positif fini, sinon retourne default."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default_value

    if not math.isfinite(v) or v <= 0:
        return default_value
    return v

def load_graph_from_osm_xml(osm_xml_path: str):
    """
    Charge un graphe routier depuis un fichier .osm XML
    Param : osm_xml_path : chemin du fichier OSM XML
    Retour : networkx.MultiDiGraph (Graphe routier prêt pour la simulation)
    """
    osm_file = Path(osm_xml_path)
    if not osm_file.exists():
        raise FileNotFoundError(f"Fichier introuvable: {osm_file}")
    
    cache_file = osm_file.with_suffix(".graphml")
    use_cache = (
        cache_file.exists()
        and cache_file.stat().st_mtime >= osm_file.stat().st_mtime
    )

    if use_cache:
        # Chargement rapide depuis le cache
        G = ox.load_graphml(cache_file)
    else:
        # Chargement du graphe à partir du XML local
        G = ox.graph_from_xml(osm_file, simplify=True, retain_all=False)

        # Certains extraits OSM peuvent contenir des arêtes incomplètes
        # (length/speed_kph null). On normalise avant le calcul des temps.
        G = ox.distance.add_edge_lengths(G)

        for _u, _v, _k, data in G.edges(keys=True, data=True):
            data["length"] = _to_valid_positive_float(
                data.get("length"),
                DEFAULT_LENGTH_M,
            )

        # Ajouts des attributs utiles : vitesses et temps de parcours
        G = ox.routing.add_edge_speeds(G, fallback=DEFAULT_SPEED_KPH)

        for _u, _v, _k, data in G.edges(keys=True, data=True):
            data["speed_kph"] = _to_valid_positive_float(
                data.get("speed_kph"),
                DEFAULT_SPEED_KPH,
            )

        G = ox.routing.add_edge_travel_times(G)

        # Sauvegarde pour accélérer les prochains démarrages
        ox.save_graphml(G, cache_file)

    return G

def extract_place_labels(G):
    """
    Extrait les lieux nommés depuis la carte
    Rerour : liste des dicts {name, x , y, place}
    """
    places = []
    for _nid, data in G.nodes(data=True):
        name = data.get("name")
        place_type = data.get("place")
        x = data.get("x")
        y = data.get("y")

        if not name or not place_type:
            continue
        if x is None or y is None:
            continue

        places.append({
            "name": str(name),
            "place": str(place_type),
            "x": float(x),
            "y": float(y),
        })

    return places

import json
from pathlib import Path

def load_places_from_geojson(path: str):
    fp = Path(path)
    if not fp.exists():
        return []
    
    with fp.open("r", encoding="utf-8") as f:
        gj = json.load(f)

    places = []
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})

        if geom.get("type") != "Point":
            continue

        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue

        name = props.get("name")
        place_type = props.get("place")
        if not name or not place_type:
            continue

        places.append({
            "name": str(name),
            "place": str(place_type),
            "x": float(coords[0]),
            "y": float(coords[1]),
        })

    return places