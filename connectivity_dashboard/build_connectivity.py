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


script_dir = Path(__file__).resolve().parent.parent
if (script_dir / "data").exists():
    BASE = script_dir
else:
    BASE = Path("/Users/bharatoraon/Desktop/Project_1")

if (script_dir / "CUMTA_GTFS").exists():
    GTFS_BASE = script_dir / "CUMTA_GTFS"
else:
    GTFS_BASE = Path("/Users/bharatoraon/Desktop/Project_1/CUMTA_GTFS")

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


def get_route_distance(stop_pt, hub_pt, route_name, route_geoms):
    if route_name in route_geoms:
        geom = route_geoms[route_name]
        try:
            d_stop = geom.project(stop_pt)
            d_hub = geom.project(hub_pt)
            route_dist = abs(d_stop - d_hub)
            euclidean_dist = stop_pt.distance(hub_pt)
            return max(euclidean_dist, route_dist)
        except Exception:
            pass
    return None


def calculate_ptal(stop_id, nodes, stop_routes, tree, all_node_list, gtfs_data=None, metro_to_gtfs=None, gps_data=None):
    stop_node = nodes[stop_id]
    stop_geom_m = stop_node["geom_m"]
    route_access_times = {}
    
    # Query STRtree with maximum walking buffer of 960 meters
    buffer_geom = stop_geom_m.buffer(960.0)
    candidate_indices = tree.query(buffer_geom)
    
    for idx in candidate_indices:
        node = all_node_list[idx]
        nid = node["id"]
        mode = node["type"]
        if mode in ("bus", "terminal", "depot"):
            walk_buffer = 640.0
            reliability_margin = 2.0
        elif mode == "metro":
            walk_buffer = 960.0
            reliability_margin = 0.75
        elif mode == "suburban":
            walk_buffer = 960.0
            reliability_margin = 1.50
        else:
            continue
            
        dist_m = stop_geom_m.distance(node["geom_m"])
        if dist_m > walk_buffer:
            continue
            
        walk_time = dist_m / 80.0
        routes_at_j = stop_routes.get(nid, set())
        n_routes = len(routes_at_j)
        if n_routes == 0:
            continue
            
        for r in routes_at_j:
            headway = None
            if mode in ("bus", "terminal", "depot"):
                if gps_data:
                    headway = gps_data.get("stop_route_metrics", {}).get(nid, {}).get(r, {}).get("mean_headway")
                if headway is None and gtfs_data:
                    bus_headways = gtfs_data.get("mtc_bus_headways", {})
                    if nid in bus_headways:
                        headway = bus_headways[nid].get(r)
                if headway is None:
                    # Fallback to heuristic
                    if n_routes > 10:
                        headway = 5.0
                    elif n_routes >= 5:
                        headway = 10.0
                    elif n_routes >= 2:
                        headway = 15.0
                    else:
                        headway = 30.0
            elif mode == "metro":
                if gtfs_data and metro_to_gtfs:
                    pid = metro_to_gtfs.get(nid)
                    if pid:
                        metro_headways = gtfs_data.get("cmrl_metro_headways", {}).get(pid, {})
                        matching_headways = []
                        for g_route, h_val in metro_headways.items():
                            if r == "metro_blue_line" and ("SWN" in g_route or "SAP" in g_route):
                                matching_headways.append(h_val)
                            elif r == "metro_green_line" and ("SMM" in g_route or "SCC" in g_route):
                                matching_headways.append(h_val)
                        if matching_headways:
                            headway = min(matching_headways)
                if headway is None:
                    headway = 10.0
            elif mode == "suburban":
                headway = 20.0
            else:
                continue

            swt = (0.5 * headway) + reliability_margin
            at = walk_time + swt
            
            if r not in route_access_times or at < route_access_times[r]:
                route_access_times[r] = at

    if not route_access_times:
        return 0.0, "0"
        
    sorted_routes = sorted(route_access_times.items(), key=lambda x: x[1])
    dom_route, dom_at = sorted_routes[0]
    
    ai = 30.0 / dom_at
    for r, at in sorted_routes[1:]:
        ai += 0.5 * (30.0 / at)
        
    if ai <= 0.0:
        grade = "0"
    elif ai <= 2.5:
        grade = "1a"
    elif ai <= 5.0:
        grade = "1b"
    elif ai <= 10.0:
        grade = "2"
    elif ai <= 15.0:
        grade = "3"
    elif ai <= 20.0:
        grade = "4"
    elif ai <= 25.0:
        grade = "5"
    elif ai <= 40.0:
        grade = "6a"
    else:
        grade = "6b"
        
    return round(ai, 2), grade


def get_gtfs_route_distance(stop_id, hub_id, route_name, gtfs_data):
    if not gtfs_data:
        return None
    dist_maps = gtfs_data.get("mtc_route_stop_distances", {}).get(route_name)
    if dist_maps:
        for dist_map in dist_maps:
            if stop_id in dist_map and hub_id in dist_map:
                return abs(dist_map[stop_id] - dist_map[hub_id])
    return None


def calculate_nhi(stop_id, nodes, stop_routes, footpaths, route_geoms, closest_hub_id, closest_hub_hops, gtfs_data=None, gps_data=None):
    if closest_hub_id is None or closest_hub_hops == float("inf"):
        s_directness = 0.0
        s_transfer = 0.0
    else:
        stop_node = nodes[stop_id]
        hub_node = nodes[closest_hub_id]
        
        if closest_hub_hops == 0:
            s_directness = 100.0
        else:
            euclidean_dist = stop_node["geom_m"].distance(hub_node["geom_m"])
            if closest_hub_hops == 1:
                stop_r = set(stop_routes.get(stop_id, []))
                hub_r = set(stop_routes.get(closest_hub_id, []))
                shared_r = stop_r.intersection(hub_r)
                
                route_dist = None
                for r in shared_r:
                    d = get_gtfs_route_distance(stop_id, closest_hub_id, r, gtfs_data)
                    if d is None:
                        d = get_route_distance(stop_node["geom_m"], hub_node["geom_m"], r, route_geoms)
                    if d is not None:
                        if route_dist is None or d < route_dist:
                            route_dist = d
                            
                if route_dist is not None:
                    circuity = route_dist / euclidean_dist if euclidean_dist > 0 else 1.0
                    s_directness = max(0.0, 100.0 * (2.0 - circuity))
                else:
                    s_directness = 80.0
            elif closest_hub_hops == 2:
                s_directness = 50.0
            elif closest_hub_hops == 3:
                s_directness = 0.0
            else:
                s_directness = 0.0
                
        if closest_hub_hops <= 1:
            s_transfer = 100.0
        elif closest_hub_hops == 2:
            s_transfer = 70.0
        elif closest_hub_hops == 3:
            s_transfer = 30.0
        else:
            s_transfer = 0.0
            
    is_multimodal_transfer = False
    candidates = {stop_id}
    if stop_id in footpaths:
        candidates.update(footpaths[stop_id])
        
    for nid in candidates:
        if nid in nodes and nodes[nid]["type"] in ("metro", "suburban"):
            is_multimodal_transfer = True
            break
            
    s_multimodal = 100.0 if is_multimodal_transfer else 0.0
    
    if gps_data:
        # Calculate GPS-empirical reliability and speed scores
        stop_r = stop_routes.get(stop_id, [])
        cvs = []
        speeds = []
        metrics = gps_data.get("stop_route_metrics", {}).get(stop_id, {})
        for r in stop_r:
            m = metrics.get(r)
            if m:
                cvs.append(m["cv_headway"])
                speeds.append(m["avg_speed"])
                
        if cvs:
            avg_cv = sum(cvs) / len(cvs)
            s_reliability = max(0.0, 100.0 * (1.0 - avg_cv))
        else:
            s_reliability = 70.0
            
        if speeds:
            avg_speed = sum(speeds) / len(speeds)
            s_speed = max(30.0, min(100.0, 30.0 + 70.0 * (avg_speed - 10.0) / 15.0))
        else:
            s_speed = 70.0
            
        nhi = 0.3 * s_directness + 0.3 * s_transfer + 0.2 * s_multimodal + 0.1 * s_reliability + 0.1 * s_speed
    else:
        routes_count = len(stop_routes.get(stop_id, []))
        if routes_count <= 1:
            s_resilience = 0.0
        else:
            import math
            s_resilience = 100.0 * (1.0 - math.exp(-0.3 * (routes_count - 1)))
        nhi = 0.3 * s_directness + 0.3 * s_transfer + 0.2 * s_multimodal + 0.2 * s_resilience
        
    return round(nhi, 1)



def run_raptor(nodes, routes, stop_routes, target_nodes, footpaths, allowed_route_types=None):
    # accessible_targets[nid] = {target_id: minimum_hops}
    accessible_targets = {nid: {} for nid in nodes}
    
    # Round 0: Direct terminal/depot and their walking neighbors
    for t in target_nodes:
        if t in accessible_targets:
            accessible_targets[t][t] = 0
            if t in footpaths:
                for nbr in footpaths[t]:
                    if nbr in accessible_targets:
                        accessible_targets[nbr][t] = 0
    
    last_round_updated = {nid for nid, targets in accessible_targets.items() if any(h == 0 for h in targets.values())}
    
    for r in range(1, 4):
        route_targets = {}
        for stop in last_round_updated:
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
                    for t, hops in accessible_targets[stop].items():
                        if hops == r - 1:
                            route_targets[route_id].add(t)
                            
        new_stops_updated = set()
        for route_id, tgts in route_targets.items():
            if route_id in routes:
                for stop in routes[route_id]:
                    if stop not in accessible_targets:
                        continue
                    updated_stop = False
                    for t in tgts:
                        if t not in accessible_targets[stop] or accessible_targets[stop][t] > r:
                            accessible_targets[stop][t] = r
                            updated_stop = True
                    if updated_stop:
                        new_stops_updated.add(stop)
                        
        walk_stops_updated = set()
        for stop in new_stops_updated:
            if stop in footpaths:
                for nbr in footpaths[stop]:
                    if allowed_route_types is not None and len(allowed_route_types) == 1:
                        if not (nbr.startswith("stop_") or nbr.startswith("terminal_") or nbr.startswith("depot_")):
                            continue
                    if nbr not in accessible_targets:
                        continue
                    updated_nbr = False
                    for t, hops in accessible_targets[stop].items():
                        if hops == r:
                            if t not in accessible_targets[nbr] or accessible_targets[nbr][t] > r:
                                accessible_targets[nbr][t] = r
                                updated_nbr = True
                    if updated_nbr:
                        walk_stops_updated.add(nbr)
                        
        last_round_updated = new_stops_updated.union(walk_stops_updated)
        if not last_round_updated:
            break
            
    min_routes = {}
    for nid, targets in accessible_targets.items():
        if targets:
            min_routes[nid] = min(targets.values())
        else:
            min_routes[nid] = float("inf")
            
    return min_routes, accessible_targets


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build connectivity metrics for Chennai transit network.")
    parser.add_argument("--period", type=str, default="morning", choices=["morning", "midday", "evening"], help="Time period to build")
    args = parser.parse_args()
    
    period = args.period
    print(f"Building connectivity metrics for period: {period}", flush=True)
    
    stop_routes = defaultdict(set)
    print("Loading boundaries and source layers...", flush=True)
    
    # Load precomputed GTFS schedules and distances
    gtfs_data = None
    try:
        gtfs_file = OUT / f"gtfs_precomputed_{period}.json"
        with open(gtfs_file, "r", encoding="utf-8") as f:
            gtfs_data = json.load(f)
        print(f"Loaded precomputed GTFS schedules and route distances from {gtfs_file.name} successfully.", flush=True)
    except Exception as e:
        print(f"Warning: Failed to load gtfs_precomputed_{period}.json: {e}", flush=True)

    # Load precomputed GPS metrics
    gps_data = None
    try:
        gps_file = OUT / f"gps_precomputed_{period}.json"
        with open(gps_file, "r", encoding="utf-8") as f:
            gps_data = json.load(f)
        print(f"Loaded precomputed GPS metrics from {gps_file.name} successfully.", flush=True)
    except Exception as e:
        print(f"Warning: Failed to load gps_precomputed_{period}.json: {e}", flush=True)

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
        for route in f["properties"].get("served_routes", []):
            stop_routes[fid].add(route)

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

    # Build route geometries dictionary for NHI calculations
    route_geoms = {}
    for ft in routes_raw["features"]:
        r_name = str(ft["properties"].get("route_name", "")).strip()
        if r_name:
            route_geoms[r_name] = to_meters(shape(ft["geometry"]))
            
    try:
        from shapely.ops import unary_union
        blue_fc = read_geojson(DATA / "blue_line_metro_corridor.geojson")
        route_geoms["metro_blue_line"] = to_meters(unary_union([shape(ft["geometry"]) for ft in blue_fc["features"]]))
        green_fc = read_geojson(DATA / "green_line_metro_corridor.geojson")
        route_geoms["metro_green_line"] = to_meters(unary_union([shape(ft["geometry"]) for ft in green_fc["features"]]))
    except Exception as e:
        print(f"Warning: Failed to load metro geometries: {e}", flush=True)
        
    try:
        from shapely.ops import unary_union
        sub_fc = read_geojson(DATA / "suburban_corridor.geojson")
        suburban_geom = to_meters(unary_union([shape(ft["geometry"]) for ft in sub_fc["features"]]))
        for line_name in suburban_lines_def.keys():
            route_geoms[line_name] = suburban_geom
    except Exception as e:
        print(f"Warning: Failed to load suburban geometries: {e}", flush=True)

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
                bus_only_acc[sid] = {}
            bus_only_acc[sid][sid] = 0
            if sid not in multimodal_acc:
                multimodal_acc[sid] = {}
            multimodal_acc[sid][sid] = 0

    # Map metro stations to GTFS parent station stops for schedule alignment
    print("Loading CMRL parent stations from GTFS for spatial mapping...", flush=True)
    cmrl_parent_stops_geom_m = {}
    try:
        import csv
        with open(GTFS_BASE / "CMRL" / "stops.txt", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, skipinitialspace=True)
            for row in reader:
                if row.get("location_type") == "1":
                    sid = row["stop_id"].strip()
                    lon = float(row["stop_lon"])
                    lat = float(row["stop_lat"])
                    cmrl_parent_stops_geom_m[sid] = to_meters(Point(lon, lat))
        print(f"Loaded {len(cmrl_parent_stops_geom_m)} parent metro stops.", flush=True)
    except Exception as e:
        print(f"Warning: Failed to load CMRL stops.txt for spatial join: {e}", flush=True)

    metro_to_gtfs = {}
    for mid, node in nodes.items():
        if node["type"] == "metro":
            geom_m = node["geom_m"]
            closest_pid = None
            min_dist = 250.0  # max 250m
            for pid, p_geom_m in cmrl_parent_stops_geom_m.items():
                dist = geom_m.distance(p_geom_m)
                if dist < min_dist:
                    min_dist = dist
                    closest_pid = pid
            if closest_pid:
                metro_to_gtfs[mid] = closest_pid
                print(f"Mapped metro station {node['name']} ({mid}) -> GTFS parent {closest_pid}", flush=True)
            else:
                print(f"Warning: Could not map metro station {node['name']} ({mid}) to any GTFS parent", flush=True)

    # 9. Enrich and export Bus Stops
    print("Enriching bus stops connectivity metadata...", flush=True)
    enriched_stops = []
    stop_rows = []
    for sid, ft, rs in stops:
        geom = shape(ft["geometry"])
        in_cma = bool(cma_prepared.covers(geom))

        # Compile names of accessible terminals and hubs
        acc_terms = sorted(list(set(nodes[tid]["name"] for tid in bus_only_acc.get(sid, {}) if tid in nodes)))
        acc_hubs = sorted(list(set(nodes[tid]["name"] for tid in multimodal_acc.get(sid, {}) if tid in nodes)))

        # Find closest accessible terminal geographically
        stop_geom_m = nodes[sid]["geom_m"]
        terminals_with_dist = []
        for tid, hops in bus_only_acc.get(sid, {}).items():
            if tid in nodes:
                dist_m = stop_geom_m.distance(nodes[tid]["geom_m"])
                terminals_with_dist.append((tid, nodes[tid]["name"], dist_m, hops))
        
        if terminals_with_dist:
            terminals_with_dist.sort(key=lambda x: x[2])
            closest_term_id = terminals_with_dist[0][0]
            closest_term_name = terminals_with_dist[0][1]
            closest_term_dist = round(terminals_with_dist[0][2] / 1000.0, 2)
            closest_term_hops = terminals_with_dist[0][3]
            terminal_buses = 1 if closest_term_hops <= 1 else closest_term_hops
        else:
            closest_term_name = None
            closest_term_dist = None
            terminal_buses = None

        # Find closest accessible hub geographically
        hubs_with_dist = []
        for tid, hops in multimodal_acc.get(sid, {}).items():
            if tid in nodes:
                dist_m = stop_geom_m.distance(nodes[tid]["geom_m"])
                hubs_with_dist.append((tid, nodes[tid]["name"], dist_m, hops))

        closest_hub_hops = float('inf')
        if hubs_with_dist:
            hubs_with_dist.sort(key=lambda x: x[2])
            closest_hub_id = hubs_with_dist[0][0]
            closest_hub_name = hubs_with_dist[0][1]
            closest_hub_dist = round(hubs_with_dist[0][2] / 1000.0, 2)
            closest_hub_hops = hubs_with_dist[0][3]
            multimodal_routes = 1 if closest_hub_hops <= 1 else closest_hub_hops
        else:
            closest_hub_id = None
            closest_hub_name = None
            closest_hub_dist = None
            multimodal_routes = None

        # Calculate PTAL index and grade
        ptal_index, ptal_grade = calculate_ptal(sid, nodes, stop_routes, tree, all_node_list, gtfs_data, metro_to_gtfs)
        
        # Calculate PTAL index and grade (GPS-Empirical)
        ptal_gps_index, ptal_gps_grade = calculate_ptal(sid, nodes, stop_routes, tree, all_node_list, gtfs_data, metro_to_gtfs, gps_data=gps_data)
        
        # Calculate Network Health Index (NHI) score
        nhi_score = calculate_nhi(
            stop_id=sid,
            nodes=nodes,
            stop_routes=stop_routes,
            footpaths=footpaths,
            route_geoms=route_geoms,
            closest_hub_id=closest_hub_id,
            closest_hub_hops=closest_hub_hops,
            gtfs_data=gtfs_data
        )

        # Calculate Network Health Index (NHI) score (GPS-Empirical)
        nhi_gps_score = calculate_nhi(
            stop_id=sid,
            nodes=nodes,
            stop_routes=stop_routes,
            footpaths=footpaths,
            route_geoms=route_geoms,
            closest_hub_id=closest_hub_id,
            closest_hub_hops=closest_hub_hops,
            gtfs_data=gtfs_data,
            gps_data=gps_data
        )

        # Calculate stop-level headway stats to save in properties
        peak_headways = []
        if gtfs_data:
            bus_headways = gtfs_data.get("mtc_bus_headways", {})
            if sid in bus_headways:
                for r in rs:
                    h = bus_headways[sid].get(r)
                    if h is not None:
                        peak_headways.append(h)
        
        # If no headways are found in GTFS, estimate from heuristic fallbacks
        if not peak_headways:
            # Fallback headway based on n_routes
            if len(rs) > 10:
                fallback_h = 5.0
            elif len(rs) >= 5:
                fallback_h = 10.0
            elif len(rs) >= 2:
                fallback_h = 15.0
            else:
                fallback_h = 30.0
            peak_headways = [fallback_h] * len(rs)
            
        avg_headway = round(sum(peak_headways) / len(peak_headways), 1) if peak_headways else None
        min_headway = min(peak_headways) if peak_headways else None

        props = dict(ft.get("properties", {}))
        qa_note = qa_facility_overrides.get(sid, "")
        props.update(
            {
                "route_count": len(rs),
                "routes_clean": rs,
                "inside_cma": in_cma,
                "accessible_terminals": acc_terms,
                "accessible_hubs": acc_hubs,
                "closest_terminal": closest_term_name,
                "closest_terminal_dist": closest_term_dist,
                "closest_hub": closest_hub_name,
                "closest_hub_dist": closest_hub_dist,
                # Bus-only metrics (Keep keys same to maintain backward compatibility where needed)
                "terminal_min_buses": terminal_buses,
                "terminal_connectivity": bucket_for_buses(terminal_buses),
                "facility_min_buses": terminal_buses,
                "facility_connectivity": bucket_for_buses(terminal_buses),
                # Multimodal metrics
                "multimodal_min_routes": multimodal_routes,
                "multimodal_connectivity": bucket_for_multimodal(multimodal_routes),
                "connectivity_qa_note": qa_note,
                # PTAL and NHI metrics
                "ptal_index": ptal_index,
                "ptal_grade": ptal_grade,
                "nhi_score": nhi_score,
                "ptal_gps_index": ptal_gps_index,
                "ptal_gps_grade": ptal_gps_grade,
                "nhi_gps_score": nhi_gps_score,
                "avg_peak_headway": avg_headway,
                "min_peak_headway": min_headway,
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

    # PTAL and NHI calculations
    cma_stops_with_ptal = [p["ptal_index"] for p in cma_stops if p["ptal_index"] is not None]
    cma_stops_with_nhi = [p["nhi_score"] for p in cma_stops if p["nhi_score"] is not None]
    mean_ptal = round(sum(cma_stops_with_ptal) / len(cma_stops_with_ptal), 2) if cma_stops_with_ptal else 0.0
    mean_nhi = round(sum(cma_stops_with_nhi) / len(cma_stops_with_nhi), 1) if cma_stops_with_nhi else 0.0

    ptal_grade_counts = Counter(p["ptal_grade"] for p in cma_stops)
    
    nhi_bins = {
        "Excellent (90-100)": 0,
        "Good (70-89)": 0,
        "Moderate (50-69)": 0,
        "Weak (30-49)": 0,
        "Critical (0-29)": 0
    }
    for p in cma_stops:
        score = p["nhi_score"]
        if score is not None:
            if score >= 90:
                nhi_bins["Excellent (90-100)"] += 1
            elif score >= 70:
                nhi_bins["Good (70-89)"] += 1
            elif score >= 50:
                nhi_bins["Moderate (50-69)"] += 1
            elif score >= 30:
                nhi_bins["Weak (30-49)"] += 1
            else:
                nhi_bins["Critical (0-29)"] += 1

    # PTAL and NHI calculations (GPS-Empirical)
    cma_stops_with_ptal_gps = [p["ptal_gps_index"] for p in cma_stops if p["ptal_gps_index"] is not None]
    cma_stops_with_nhi_gps = [p["nhi_gps_score"] for p in cma_stops if p["nhi_gps_score"] is not None]
    mean_ptal_gps = round(sum(cma_stops_with_ptal_gps) / len(cma_stops_with_ptal_gps), 2) if cma_stops_with_ptal_gps else 0.0
    mean_nhi_gps = round(sum(cma_stops_with_nhi_gps) / len(cma_stops_with_nhi_gps), 1) if cma_stops_with_nhi_gps else 0.0

    ptal_gps_grade_counts = Counter(p["ptal_gps_grade"] for p in cma_stops)
    
    nhi_gps_bins = {
        "Excellent (90-100)": 0,
        "Good (70-89)": 0,
        "Moderate (50-69)": 0,
        "Weak (30-49)": 0,
        "Critical (0-29)": 0
    }
    for p in cma_stops:
        score = p["nhi_gps_score"]
        if score is not None:
            if score >= 90:
                nhi_gps_bins["Excellent (90-100)"] += 1
            elif score >= 70:
                nhi_gps_bins["Good (70-89)"] += 1
            elif score >= 50:
                nhi_gps_bins["Moderate (50-69)"] += 1
            elif score >= 30:
                nhi_gps_bins["Weak (30-49)"] += 1
            else:
                nhi_gps_bins["Critical (0-29)"] += 1

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
        "ptal_average": mean_ptal,
        "nhi_average": mean_nhi,
        "ptal_grade_counts": dict(ptal_grade_counts),
        "nhi_score_counts": nhi_bins,
        "ptal_gps_average": mean_ptal_gps,
        "nhi_gps_average": mean_nhi_gps,
        "ptal_gps_grade_counts": dict(ptal_gps_grade_counts),
        "nhi_gps_score_counts": nhi_gps_bins,
    }

    # Enrich metro station features with precomputed headway stats
    if metro_to_gtfs:
        for ft in metro_station_features:
            name = ft["properties"].get("Name")
            mid = f"metro_{normalize_name(name)}"
            pid = metro_to_gtfs.get(mid)
            avg_h = None
            min_h = None
            if gtfs_data and pid:
                metro_headways = gtfs_data.get("cmrl_metro_headways", {}).get(pid, {})
                if metro_headways:
                    vals = list(metro_headways.values())
                    avg_h = round(sum(vals) / len(vals), 1)
                    min_h = min(vals)
            ft["properties"]["avg_peak_headway"] = avg_h
            ft["properties"]["min_peak_headway"] = min_h

    print("Writing enriched geospatial outputs to dashboard folder...", flush=True)
    # Period-specific outputs
    write_geojson(f"bus_stops_connectivity_{period}.geojson", [s for s in enriched_stops if s["properties"]["inside_cma"]])
    write_geojson(f"metro_stations_enriched_{period}.geojson", metro_station_features)
    with open(OUT / f"connectivity_summary_{period}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Period-specific outputs written: bus_stops_connectivity_{period}.geojson, metro_stations_enriched_{period}.geojson, connectivity_summary_{period}.json", flush=True)

    # For compatibility/default, save as normal names if it's the morning peak
    if period == "morning":
        write_geojson("bus_stops_connectivity.geojson", [s for s in enriched_stops if s["properties"]["inside_cma"]])
        write_geojson("metro_stations_enriched.geojson", metro_station_features)
        with open(OUT / "connectivity_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print("Default files saved (morning peak).", flush=True)

    write_geojson("bus_routes_enriched.geojson", enriched_routes)
    write_geojson("bus_facilities_enriched.geojson", [f for f in facilities if f["properties"]["inside_cma"]])
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

    print(json.dumps(summary, indent=2))
    print("ETL complete. Outputs written to", OUT)


if __name__ == "__main__":
    main()
