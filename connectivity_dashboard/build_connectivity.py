import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, shape
from shapely.ops import transform
from shapely.prepared import prep
from shapely.strtree import STRtree


BASE = Path("/Users/bharatoraon/Desktop/Project_1")
DATA = BASE / "data"
OUT = BASE / "connectivity_dashboard"
OUT.mkdir(parents=True, exist_ok=True)

CRS_WGS84 = "EPSG:4326"
CRS_METERS = "EPSG:32644"
PROJECT_TO_METERS = Transformer.from_crs(CRS_WGS84, CRS_METERS, always_xy=True).transform


def read_geojson(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_geojson(name, features):
    fc = {"type": "FeatureCollection", "features": features}
    path = OUT / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    return path


def normalize_name(value):
    value = (value or "").lower()
    value = re.sub(r"\b(bus|mtc|terminus|terminal|stand|depot|jn|junction)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def route_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        routes = []
        for part in re.split(r"[,;/]", value):
            cleaned = part.strip().strip("[]'\" ")
            if cleaned:
                routes.append(cleaned)
        return routes
    return []


def geom_endpoints(geom):
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        return Point(coords[0]), Point(coords[-1])
    if isinstance(geom, MultiLineString):
        parts = list(geom.geoms)
        if not parts:
            return None, None
        return Point(list(parts[0].coords)[0]), Point(list(parts[-1].coords)[-1])
    return None, None


def feature(geometry, props):
    return {"type": "Feature", "geometry": geometry.__geo_interface__, "properties": props}


def to_meters(geometry):
    return transform(PROJECT_TO_METERS, geometry)


def bucket_for_buses(buses):
    if buses is None:
        return "No route connection"
    if buses == 1:
        return "Direct"
    if buses == 2:
        return "2 buses"
    if buses == 3:
        return "3 buses"
    return "4+ buses"


def bucket_for_multimodal(routes_count):
    if routes_count is None:
        return "No route connection"
    if routes_count == 1:
        return "Direct"
    if routes_count == 2:
        return "2 routes"
    if routes_count == 3:
        return "3 routes"
    return "4+ routes"


def run_raptor(nodes, routes, stop_routes, target_nodes, footpaths, allowed_route_types=None):
    min_routes = {nid: float("inf") for nid in nodes}
    accessible_targets = {nid: set() for nid in nodes}
    reached = set()

    for t in target_nodes:
        if t in min_routes:
            min_routes[t] = 0
            accessible_targets[t].add(t)
            reached.add(t)
            if t in footpaths:
                for nbr in footpaths[t]:
                    if nbr in min_routes:
                        min_routes[nbr] = 0
                        accessible_targets[nbr].add(t)
                        reached.add(nbr)

    current_stops = reached
    for r in range(1, 4):
        route_targets = {}
        for stop in current_stops:
            if stop in stop_routes:
                for route_id in stop_routes[stop]:
                    if allowed_route_types is not None:
                        route_type = "bus"
                        if route_id.startswith("metro_"):
                            route_type = "metro"
                        elif route_id.startswith("suburban_"):
                            route_type = "suburban"
                        if route_type not in allowed_route_types:
                            continue
                    if route_id not in route_targets:
                        route_targets[route_id] = set()
                    route_targets[route_id].update(accessible_targets[stop])

        new_stops = set()
        for route_id, tgts in route_targets.items():
            if route_id in routes:
                for stop in routes[route_id]:
                    if stop not in min_routes:
                        continue
                    if min_routes[stop] > r:
                        min_routes[stop] = r
                        new_stops.add(stop)
                    if min_routes[stop] == r:
                        accessible_targets[stop].update(tgts)

        walk_stops = set()
        for stop in new_stops:
            if stop in footpaths:
                for nbr in footpaths[stop]:
                    if allowed_route_types is not None and len(allowed_route_types) == 1:
                        # Bus-only mode: only walk to bus stops or terminals
                        if not (nbr.startswith("stop_") or nbr.startswith("terminal_") or nbr.startswith("depot_")):
                            continue
                    if nbr not in min_routes:
                        continue
                    if min_routes[nbr] > r:
                        min_routes[nbr] = r
                        walk_stops.add(nbr)
                    if min_routes[nbr] == r:
                        accessible_targets[nbr].update(accessible_targets[stop])

        current_stops = new_stops.union(walk_stops)
        if not current_stops:
            break

    return min_routes, accessible_targets


def main():
    print("Loading boundaries and source layers...", flush=True)
    cma = gpd.read_file(DATA / "CMA.geojson").to_crs(CRS_WGS84)
    cma_union = cma.geometry.union_all()
    cma_prepared = prep(cma_union)

    # 1. Load Bus layers
    routes_raw = read_geojson(DATA / "all_mtc_routes.geojson")
    stops_raw = read_geojson(DATA / "mtc_bus_stops_all.geojson")
    termini_raw = read_geojson(DATA / "bus_terminus.geojson")

    # 2. Load Metro layers
    blue_line_metro_stations = read_geojson(DATA / "blue_line_metro_stations.geojson")
    green_line_metro_stations = read_geojson(DATA / "green_line_metro_stations.geojson")

    # 3. Load Suburban layers
    suburban_stations_raw = read_geojson(DATA / "suburban stations.geojson")

    print("Building bus route and stop transfer network...", flush=True)
    routes = []
    route_names = set()
    endpoint_name_to_routes = defaultdict(set)
    route_endpoint_points = defaultdict(list)
    for ft in routes_raw["features"]:
        props = ft.get("properties", {})
        route = str(props.get("route_name", "")).strip()
        if not route:
            continue
        geom = shape(ft["geometry"])
        route_names.add(route)
        start, end = geom_endpoints(geom)
        for label, point in [(props.get("source"), start), (props.get("destinatio"), end)]:
            label_norm = normalize_name(label)
            if label_norm:
                endpoint_name_to_routes[label_norm].add(route)
            if point:
                route_endpoint_points[route].append((label or "", point))
        routes.append(ft)

    stops = []
    stop_routes_bus = {}
    route_to_stops = defaultdict(set)
    for i, ft in enumerate(stops_raw["features"]):
        props = ft.get("properties", {})
        sid = str(props.get("Stop Id") or f"stop_{i}")
        rs = sorted(set(r for r in route_list(props.get("route name")) if r in route_names))
        stop_routes_bus[sid] = rs
        for route in rs:
            route_to_stops[route].add(sid)
        stops.append((sid, ft, rs))

    facilities = []
    terminal_features = []
    terminal_routes = defaultdict(set)

    print("Linking route endpoints to bus terminals/facilities...", flush=True)
    endpoint_points_m = []
    for route, endpoints in route_endpoint_points.items():
        for label, point in endpoints:
            endpoint_points_m.append((route, label, to_meters(point)))

    for i, ft in enumerate(termini_raw["features"]):
        geom = shape(ft["geometry"])
        name = ft["properties"].get("Name of th") or f"Bus facility {i + 1}"
        norm = normalize_name(name)
        served = set(endpoint_name_to_routes.get(norm, set()))
        point_m = to_meters(geom)
        for route, label, endpoint_m in endpoint_points_m:
            if point_m.distance(endpoint_m) <= 650:
                served.add(route)
        props = {
            "facility_id": f"terminal_{i + 1}",
            "name": name,
            "facility_type": "Terminal",
            "ownership": ft["properties"].get("Ownership"),
            "served_routes": sorted(served),
            "served_route_count": len(served),
            "source": "bus_terminus.geojson",
            "inside_cma": bool(cma_prepared.covers(geom)),
        }
        facilities.append(feature(geom, props))
        terminal_features.append(feature(geom, props))
        terminal_routes[props["facility_id"]] = served

    depot_mentions = defaultdict(list)
    depot_routes = defaultdict(set)
    for route, endpoints in route_endpoint_points.items():
        for label, point in endpoints:
            if "depot" in (label or "").lower():
                norm = normalize_name(label)
                if norm:
                    depot_mentions[norm].append((label, point))
                    depot_routes[norm].add(route)

    depot_features = []
    for i, (norm, mentions) in enumerate(sorted(depot_mentions.items()), start=1):
        label = Counter(label for label, _ in mentions).most_common(1)[0][0]
        geom = MultiPoint([p for _, p in mentions]).centroid
        did = f"depot_{i}"
        served = depot_routes[norm]
        props = {
            "facility_id": did,
            "name": label,
            "facility_type": "Terminal",
            "ownership": "Inferred",
            "served_routes": sorted(served),
            "served_route_count": len(served),
            "source": "inferred terminal/facility from all_mtc_routes source/destination endpoint",
            "inside_cma": bool(cma_prepared.covers(geom)),
        }
        f = feature(geom, props)
        facilities.append(f)
        depot_features.append(f)

    # 4. Construct unified nodes representation
    print("Building unified transit graph nodes...", flush=True)
    nodes = {}

    # Bus stops
    for sid, ft, rs in stops:
        geom = shape(ft["geometry"])
        nodes[sid] = {
            "id": sid,
            "type": "bus",
            "name": ft["properties"].get("Stop Name") or ft["properties"].get("Name") or sid,
            "geom": geom,
            "geom_m": to_meters(geom),
            "raw_properties": ft["properties"],
        }

    # Bus terminals
    for f in facilities:
        fid = f["properties"]["facility_id"]
        geom = shape(f["geometry"])
        nodes[fid] = {
            "id": fid,
            "type": "terminal",
            "name": f["properties"]["name"],
            "geom": geom,
            "geom_m": to_meters(geom),
            "raw_properties": f["properties"],
        }

    # Metro stations
    metro_station_features = []
    for ft in blue_line_metro_stations["features"]:
        geom = shape(ft["geometry"])
        if not cma_prepared.covers(geom):
            continue
        name = ft["properties"]["Name"]
        mid = f"metro_{normalize_name(name)}"
        if mid not in nodes:
            nodes[mid] = {
                "id": mid,
                "type": "metro",
                "name": name,
                "geom": geom,
                "geom_m": to_meters(geom),
                "raw_properties": {"Name": name, "Line": ["Blue"]},
            }
        else:
            if "Blue" not in nodes[mid]["raw_properties"]["Line"]:
                nodes[mid]["raw_properties"]["Line"].append("Blue")

    for ft in green_line_metro_stations["features"]:
        geom = shape(ft["geometry"])
        if not cma_prepared.covers(geom):
            continue
        name = ft["properties"]["Name"]
        mid = f"metro_{normalize_name(name)}"
        if mid not in nodes:
            nodes[mid] = {
                "id": mid,
                "type": "metro",
                "name": name,
                "geom": geom,
                "geom_m": to_meters(geom),
                "raw_properties": {"Name": name, "Line": ["Green"]},
            }
        else:
            if "Green" not in nodes[mid]["raw_properties"]["Line"]:
                nodes[mid]["raw_properties"]["Line"].append("Green")

    for mid, node in nodes.items():
        if node["type"] == "metro":
            metro_station_features.append(feature(node["geom"], node["raw_properties"]))

    # Suburban stations
    suburban_station_features = []
    for ft in suburban_stations_raw["features"]:
        geom = shape(ft["geometry"])
        if not cma_prepared.covers(geom):
            continue
        name = ft["properties"]["STATION NA"]
        sub_id = f"suburban_{normalize_name(name)}"
        nodes[sub_id] = {
            "id": sub_id,
            "type": "suburban",
            "name": name,
            "geom": geom,
            "geom_m": to_meters(geom),
            "raw_properties": ft["properties"],
        }
        suburban_station_features.append(feature(geom, ft["properties"]))

    # 5. Build Routes dict
    print("Building unified routes dict...", flush=True)
    routes_dict = {}
    stop_routes = defaultdict(set)

    # Bus
    for r_name, sids in route_to_stops.items():
        routes_dict[r_name] = list(sids)
        for sid in sids:
            stop_routes[sid].add(r_name)

    # Metro
    blue_line_seq = [
        "WIMCO NAGAR DEPOT",
        "WIMCO NAGAR METRO",
        "THIRUVOTRIYUR",
        "THIRUVOTRIYUR THERADI",
        "KALADIPET",
        "TOLLGATE",
        "NEW WASHERMENPET",
        "TONDIARPET",
        "THIYAGARAYA COLLEGE",
        "WASHERMANPET",
        "MANNADI",
        "HIGH COURT",
        "CENTRAL METRO",
        "GOVERNMENT ESTATe",
        "LIC",
        "THOUSAND LIGHT",
        "TEYNAMPET",
        "AG-DMS",
        "NANDANAM",
        "SAIDAPET",
        "LITTLE MOUNT",
        "GUINDY",
        "ALANDUR",
        "OTA - NANGANALLUR ROAD",
        "MEENAMBAKKAM",
        "CHENNAI AIRPORT",
    ]
    blue_line_ids = [f"metro_{normalize_name(name)}" for name in blue_line_seq]
    routes_dict["metro_blue_line"] = blue_line_ids
    for mid in blue_line_ids:
        stop_routes[mid].add("metro_blue_line")

    green_line_seq = [
        "CENTRAL METRO",
        "EGMORE",
        "NEHRU PARK",
        "KILPAUK",
        "PACHAIAPPA S COLLEGE",
        "SHENOY NAGAR",
        "ANNA NAGAR EAST",
        "ANNA NAGAR TOWER",
        "THIRUMANGALAM",
        "KOYAMBEDU",
        "KOYAMBEDU DEPOT",
        "CMBT",
        "ARUMBAKKAM",
        "VADAPALANI",
        "ASHOK NAGAR",
        "EKKATTUTHANGAL",
        "ALANDUR",
        "St. THOMAS MOUNT",
    ]
    green_line_ids = [f"metro_{normalize_name(name)}" for name in green_line_seq]
    routes_dict["metro_green_line"] = green_line_ids
    for mid in green_line_ids:
        stop_routes[mid].add("metro_green_line")

    # Suburban
    suburban_lines_def = {
        "suburban_south_line": [
            "CHENNAI BEACH JN.",
            "CHENNAI FORT",
            "CHENNAI PARK",
            "CHENNAI EGMORE",
            "CHENNAI CHETPAT",
            "NUNGAMBAKKAM",
            "KODAMBAKKAM",
            "MAMBALAM",
            "SAIDAPET",
            "GUINDY",
            "ST. THOMAS MOUNT",
            "PALAVANTANGAL",
            "MINAMBAKKAM",
            "TIRUSULAM",
            "PALLAVARAM",
            "CHROMEPET",
            "TAMBARAM SANATORIUM",
            "TAMBARAM",
            "PERUNGALALATTUR",
            "VANDALUR",
            "URAPPAKKAM",
            "GUDUVANCHERI",
            "POTHERI",
            "KATTANGULATUR",
            "MARAIMALAI NAGAR KAMARAJAR",
            "SINGAPERUMALKOIL",
            "PARANUR",
            "CHENGALPATTU JN.",
            "OTTIVAKKAM",
        ],
        "suburban_west_line": [
            "CHENNAI CENTRAL SUBURBAN",
            "CHENNAI CENTRAL",
            "BASIN BRIDGE JN.(MADRAS)",
            "VYASARPADI JEEVA",
            "PERAMBUR",
            "PERAMBUR CARRIAGE WORKS",
            "PERAMBUR LOCO WORKS",
            "VILLIVAKKAM",
            "KORATTUR",
            "PATTARAVAKKAM",
            "AMBATTUR",
            "ANNANUR",
            "AVADI",
            "HINDU COLLEGE",
            "PATTABIRAM",
            "NEMILICHERY",
            "TIRUNINRAVUR",
            "VEPPAMPATTU",
            "SEVVAPET ROAD",
            "PUTLUR HALT",
            "TIRUVALLUR",
            "EGATTUR",
            "KADAMBATTUR",
            "SENJI PANAMBAKKAM",
            "MANAVUR",
            "TIRUVALANGADU",
            "MOSUR",
            "PULIYAMANGALAM",
            "ARAKKONAM",
        ],
        "suburban_north_line_central": [
            "CHENNAI CENTRAL SUBURBAN",
            "CHENNAI CENTRAL",
            "BASIN BRIDGE JN.(MADRAS)",
            "KORUKKUPET",
            "TONDIARPET",
            "VOC NAGAR",
            "TIRUVOTTIYUR",
            "WIMCO NAGAR",
            "KATHIVAKKAM",
            "ENNORE",
            "ATTIPATTU PUDU NAGAR.H",
            "ATTIPPATTU",
            "NANDIYAMPAKKAM",
            "MINJUR",
            "ANUPPAMBATTU",
            "PONNERI",
            "KAVARAIPPETTAI",
            "GUMMIDIPUNDI",
            "ELAVUR",
            "ARAMBAKKAM",
        ],
        "suburban_north_line_beach": [
            "CHENNAI BEACH JN.",
            "ROYAPURAM",
            "WASHERMANPET",
            "KORUKKUPET",
            "TONDIARPET",
            "VOC NAGAR",
            "TIRUVOTTIYUR",
            "WIMCO NAGAR",
            "KATHIVAKKAM",
            "ENNORE",
            "ATTIPATTU PUDU NAGAR.H",
            "ATTIPPATTU",
            "NANDIYAMPAKKAM",
            "MINJUR",
            "ANUPPAMBATTU",
            "PONNERI",
            "KAVARAIPPETTAI",
            "GUMMIDIPUNDI",
            "ELAVUR",
            "ARAMBAKKAM",
        ],
        "suburban_chengalpattu_arakkonam_line": [
            "CHENGALPATTU JN.",
            "REDDIPALAYAM",
            "VILLIYAMBAKKAM",
            "PALUR",
            "PALAYASIVARAM",
            "WALAJABAD",
            "NATHAPETTAI",
            "KANCHIPURAM EAST",
            "KANCHIPURAM",
            "TIRUMALPUR",
            "TAKKOLAM",
            "ARAKKONAM",
        ],
    }

    for line_name, stops_list in suburban_lines_def.items():
        sub_ids = [f"suburban_{normalize_name(name)}" for name in stops_list]
        routes_dict[line_name] = sub_ids
        for sub_id in sub_ids:
            stop_routes[sub_id].add(line_name)

    # 6. Build transfer footpaths
    print("Building spatial index for 200m walking transfers...", flush=True)
    all_node_list = list(nodes.values())
    node_points_m = [n["geom_m"] for n in all_node_list]
    tree = STRtree(node_points_m)

    footpaths = defaultdict(set)
    for i, pt in enumerate(node_points_m):
        nid_a = all_node_list[i]["id"]
        indices = tree.query(pt.buffer(200))
        for idx in indices:
            if idx != i:
                nid_b = all_node_list[idx]["id"]
                dist = pt.distance(node_points_m[idx])
                if dist <= 200:
                    footpaths[nid_a].add(nid_b)

    # 7. Define target sets
    print("Defining target destinations...", flush=True)
    bus_only_targets = set()
    for nid, node in nodes.items():
        if node["type"] in ("terminal", "depot"):
            bus_only_targets.add(nid)
            # Add all stops within 250m
            if nid in footpaths:
                for nbr in footpaths[nid]:
                    if nodes[nbr]["type"] == "bus":
                        bus_only_targets.add(nbr)

    multimodal_targets = set(bus_only_targets)
    for nid, node in nodes.items():
        if node["type"] in ("metro", "suburban"):
            multimodal_targets.add(nid)

    # 8. Run RAPTOR
    print("Running Round-Based (RAPTOR) connectivity analysis...", flush=True)
    print("  Evaluating Bus-Only connectivity...", flush=True)
    bus_only_dist, bus_only_acc = run_raptor(
        nodes=nodes,
        routes=routes_dict,
        stop_routes=stop_routes,
        target_nodes=bus_only_targets,
        footpaths=footpaths,
        allowed_route_types={"bus"},
    )

    print("  Evaluating Multimodal connectivity...", flush=True)
    multimodal_dist, multimodal_acc = run_raptor(
        nodes=nodes,
        routes=routes_dict,
        stop_routes=stop_routes,
        target_nodes=multimodal_targets,
        footpaths=footpaths,
        allowed_route_types={"bus", "metro", "suburban"},
    )

    # Apply manual QA facility overrides
    qa_facility_overrides = {
        "UgzfanVk": "Validated facility stop: Kundrathur Bus Depot is treated as a terminal/facility location; route attribute is malformed in source stop layer.",
        "pdQlgkSh": "Validated facility stop: Chennai Koyambedu Mofussil Bus Stand is a terminal/CMBT facility location; route layer does not carry these SP services.",
    }
    for sid in qa_facility_overrides:
        if sid in nodes:
            bus_only_dist[sid] = 1
            multimodal_dist[sid] = 1
            if sid not in bus_only_acc:
                bus_only_acc[sid] = set()
            bus_only_acc[sid].add(sid)
            if sid not in multimodal_acc:
                multimodal_acc[sid] = set()
            multimodal_acc[sid].add(sid)

    # 9. Enrich and export Bus Stops
    print("Enriching bus stops connectivity metadata...", flush=True)
    enriched_stops = []
    stop_rows = []
    for sid, ft, rs in stops:
        geom = shape(ft["geometry"])
        in_cma = bool(cma_prepared.covers(geom))

        # Bus-Only
        bo_d = bus_only_dist.get(sid, float("inf"))
        terminal_buses = None if bo_d == float("inf") else (1 if bo_d == 0 else bo_d)

        # Multimodal
        mm_d = multimodal_dist.get(sid, float("inf"))
        multimodal_routes = None if mm_d == float("inf") else (1 if mm_d == 0 else mm_d)

        # Compile names of accessible terminals and hubs
        acc_terms = sorted(list(set(nodes[tid]["name"] for tid in bus_only_acc.get(sid, []) if tid in nodes)))
        acc_hubs = sorted(list(set(nodes[tid]["name"] for tid in multimodal_acc.get(sid, []) if tid in nodes)))

        props = dict(ft.get("properties", {}))
        qa_note = qa_facility_overrides.get(sid, "")
        props.update(
            {
                "route_count": len(rs),
                "routes_clean": rs,
                "inside_cma": in_cma,
                "accessible_terminals": acc_terms,
                "accessible_hubs": acc_hubs,
                # Bus-only metrics (Keep keys same to maintain backward compatibility where needed)
                "terminal_min_buses": terminal_buses,
                "terminal_connectivity": bucket_for_buses(terminal_buses),
                "facility_min_buses": terminal_buses,
                "facility_connectivity": bucket_for_buses(terminal_buses),
                # Multimodal metrics
                "multimodal_min_routes": multimodal_routes,
                "multimodal_connectivity": bucket_for_multimodal(multimodal_routes),
                "connectivity_qa_note": qa_note,
            }
        )
        enriched_stops.append(feature(geom, props))
        stop_rows.append(props)

    # 10. Enrich and export routes
    print("Scoring routes by connectivity coverage...", flush=True)
    enriched_routes = []
    for ft in routes:
        route = str(ft["properties"].get("route_name", "")).strip()
        served_stop_ids = route_to_stops.get(route, set())
        geom = shape(ft["geometry"])
        clipped_geom = geom.intersection(cma_union)
        if clipped_geom.is_empty:
            continue
        props = dict(ft["properties"])
        props.update(
            {
                "stop_count_in_dataset": len(served_stop_ids),
                "serves_terminal": any(sid in bus_only_targets for sid in served_stop_ids),
                "serves_facility": any(sid in bus_only_targets for sid in served_stop_ids),
            }
        )
        enriched_routes.append(feature(clipped_geom, props))

    # Compile counts and summary
    cma_stops = [p for p in stop_rows if p["inside_cma"]]
    cma_facilities = [f["properties"] for f in facilities if f["properties"]["inside_cma"]]

    terminal_counts = Counter(p["terminal_connectivity"] for p in cma_stops)
    multimodal_counts = Counter(p["multimodal_connectivity"] for p in cma_stops)

    summary = {
        "generated_from": str(DATA),
        "method": {
            "bus_only_connectivity": "RAPTOR Round-Based Transit routing on MTC bus routes only.",
            "multimodal_connectivity": "Multimodal RAPTOR routing incorporating Bus + Metro (Blue/Green) + Suburban Rail lines with walking transfers under 200m.",
            "qa_corrections": "Manual validation overrides applied for CMBT and Kundrathur depot stop locations.",
        },
        "counts": {
            "routes": len(route_names),
            "bus_stops": len(stop_rows),
            "bus_stops_inside_cma": len(cma_stops),
            "metro_stations": len(metro_station_features),
            "suburban_stations": len(suburban_station_features),
            "bus_facilities_total": len(facilities),
            "bus_facilities_inside_cma": len(cma_facilities),
            "inferred_terminal_points": len(depot_features),
        },
        "bus_only_connectivity_counts": dict(terminal_counts),
        "multimodal_connectivity_counts": dict(multimodal_counts),
    }

    print("Writing enriched geospatial outputs to dashboard folder...", flush=True)
    write_geojson("bus_stops_connectivity.geojson", [s for s in enriched_stops if s["properties"]["inside_cma"]])
    write_geojson("bus_routes_enriched.geojson", enriched_routes)
    write_geojson("bus_facilities_enriched.geojson", [f for f in facilities if f["properties"]["inside_cma"]])
    write_geojson("metro_stations_enriched.geojson", metro_station_features)
    write_geojson("suburban_stations_enriched.geojson", suburban_station_features)

    # Copy CMA.geojson
    with open(DATA / "CMA.geojson", "r", encoding="utf-8") as src, open(OUT / "CMA.geojson", "w", encoding="utf-8") as dst:
        dst.write(src.read())

    # Load, clip, and write corridors
    for name in [
        "blue_line_metro_corridor.geojson",
        "green_line_metro_corridor.geojson",
        "suburban_corridor.geojson",
    ]:
        corridor_raw = read_geojson(DATA / name)
        clipped_features = []
        for ft in corridor_raw["features"]:
            geom = shape(ft["geometry"])
            clipped_geom = geom.intersection(cma_union)
            if not clipped_geom.is_empty:
                clipped_features.append(feature(clipped_geom, ft.get("properties", {})))
        
        write_geojson(name, {"type": "FeatureCollection", "features": clipped_features})

    with open(OUT / "connectivity_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2))
    print("ETL complete. Outputs written to", OUT)


if __name__ == "__main__":
    main()
