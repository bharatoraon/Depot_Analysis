import csv
import json
import math
from pathlib import Path
from collections import defaultdict

# Setup paths dynamically
script_dir = Path(__file__).resolve().parent.parent
if (script_dir / "data").exists():
    BASE = script_dir
else:
    BASE = Path("/Users/bharatoraon/Desktop/Project_1")

DATA = BASE / "data"
GPS_DIR = BASE / "Bus_GPS_Data"
OUT = BASE / "connectivity_dashboard"

# Period definitions mapping IST to UTC
# - Morning Peak: 08:00 - 10:00 IST -> 02:30 - 04:30 UTC
# - Midday Off-Peak: 12:00 - 14:00 IST -> 06:30 - 08:30 UTC
# - Evening Peak: 17:00 - 19:00 IST -> 11:30 - 13:30 UTC
PERIODS = {
    "morning": {
        "start": "02:30:00",
        "end": "04:30:00",
        "files": ["amnex_direct_data_2026-05-20_06-09.csv", "amnex_direct_data_2026-05-20_09-12.csv"]
    },
    "midday": {
        "start": "06:30:00",
        "end": "08:30:00",
        "files": ["amnex_direct_data_2026-05-20_12-15.csv"]
    },
    "evening": {
        "start": "11:30:00",
        "end": "13:30:00",
        "files": ["amnex_direct_data_2026-05-20_15-18.csv", "amnex_direct_data_2026-05-20_18-21.csv"]
    }
}

def parse_time_to_seconds(ts_str):
    try:
        # Expected format: "YYYY-MM-DD HH:MM:SS"
        parts = ts_str.split()
        if len(parts) < 2:
            return None
        time_parts = [int(p) for p in parts[1].split(":")]
        if len(time_parts) == 3:
            return time_parts[0] * 3600 + time_parts[1] * 60 + time_parts[2]
        return None
    except Exception:
        return None

def calc_dist_meters(lon1, lat1, lon2, lat2):
    # Fast Euclidean approximation in meters near Chennai (lat ~13N)
    dy = (lat1 - lat2) * 111100.0
    dx = (lon1 - lon2) * 108200.0
    return math.sqrt(dx*dx + dy*dy)

def normalize_name(value):
    import re
    value = (value or "").lower()
    value = re.sub(r"\b(bus|mtc|terminus|terminal|stand|depot|jn|junction)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def route_list(value):
    import re
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

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Precompute GPS metrics for Chennai bus stops.")
    parser.add_argument("--period", type=str, default="morning", choices=["morning", "midday", "evening"], help="Time period to process")
    args = parser.parse_args()
    
    period = args.period
    config = PERIODS[period]
    
    PEAK_DATE = "2026-05-20"
    PEAK_START = config["start"]
    PEAK_END = config["end"]
    
    print(f"Starting pre-computation of GPS metrics for period: {period} ({PEAK_START} to {PEAK_END} UTC)...", flush=True)
    
    # 1. Load MTC valid route names to filter stops
    print("Loading MTC route names...", flush=True)
    route_names = set()
    try:
        with open(DATA / "all_mtc_routes.geojson", "r", encoding="utf-8") as f:
            routes_raw = json.load(f)
            for ft in routes_raw["features"]:
                props = ft.get("properties", {})
                route = str(props.get("route_name", "")).strip()
                if route:
                    route_names.add(route)
        print(f"Loaded {len(route_names)} valid route names.", flush=True)
    except Exception as e:
        print(f"Warning: Failed to load all_mtc_routes.geojson: {e}", flush=True)
        return

    # 2. Load static bus stops and build spatial grid index
    print("Loading MTC bus stops...", flush=True)
    stops = []
    grid = defaultdict(list)
    grid_size = 0.002 # ~220m grid cells for fast spatial query
    
    try:
        with open(DATA / "mtc_bus_stops_all.geojson", "r", encoding="utf-8") as f:
            stops_raw = json.load(f)
            for i, ft in enumerate(stops_raw["features"]):
                props = ft.get("properties", {})
                sid = str(props.get("Stop Id") or f"stop_{i}")
                name = props.get("Stop Name") or props.get("Name") or sid
                rs = sorted(set(r for r in route_list(props.get("route name")) if r in route_names))
                geom = ft.get("geometry", {})
                if geom and geom.get("type") == "Point":
                    lon, lat = geom["coordinates"]
                    stop_node = {
                        "id": sid,
                        "name": name,
                        "lon": lon,
                        "lat": lat,
                        "routes": set(rs)
                    }
                    stops.append(stop_node)
                    # Spatial grid cell key
                    cell = (int(lon / grid_size), int(lat / grid_size))
                    grid[cell].append(stop_node)
        print(f"Loaded {len(stops)} bus stops and built spatial grid.", flush=True)
    except Exception as e:
        print(f"Warning: Failed to load mtc_bus_stops_all.geojson: {e}", flush=True)
        return

    # 3. Read raw GPS files for the peak window and group by vehicle
    print("Reading GPS files and filtering peak window...", flush=True)
    gps_files = [GPS_DIR / name for name in config["files"]]
    
    # vehicleNumber -> list of pings: (timestamp, seconds, lon, lat, route_name)
    vehicle_pings = defaultdict(list)
    total_raw_rows = 0
    peak_rows = 0
    
    for file_path in gps_files:
        if not file_path.exists():
            print(f"File {file_path.name} not found, skipping...", flush=True)
            continue
            
        print(f"Reading {file_path.name}...", flush=True)
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_raw_rows += 1
                ts = row.get("timestamp")
                if not ts:
                    continue
                
                parts = ts.split()
                if len(parts) < 2:
                    continue
                date_part, time_part = parts[0], parts[1]
                
                # Check if in peak window
                if date_part == PEAK_DATE and PEAK_START <= time_part <= PEAK_END:
                    peak_rows += 1
                    vehicle = row.get("vehicleNumber") or row.get("deviceId")
                    route = row.get("routeNumber") or row.get("route_id")
                    lon = row.get("long")
                    lat = row.get("lat")
                    
                    if vehicle and route and lon and lat:
                        try:
                            lon_f = float(lon)
                            lat_f = float(lat)
                            seconds = parse_time_to_seconds(ts)
                            if seconds is not None:
                                vehicle_pings[vehicle].append({
                                    "ts": ts,
                                    "sec": seconds,
                                    "lon": lon_f,
                                    "lat": lat_f,
                                    "route": route.strip()
                                })
                        except ValueError:
                            continue
                            
                if total_raw_rows % 2000000 == 0:
                    print(f"  Processed {total_raw_rows} raw rows, current peak: {peak_rows}", flush=True)
                    
    print(f"Completed loading GPS data. Peak pings: {peak_rows} across {len(vehicle_pings)} vehicles.", flush=True)

    # 4. Calculate speeds between consecutive pings of each vehicle
    print("Calculating vehicle speeds and mapping pings to stops...", flush=True)
    # stop_id -> route -> list of visits: (sec, speed, vehicle)
    stop_route_visits = defaultdict(lambda: defaultdict(list))
    mapped_count = 0
    
    for vehicle, pings in vehicle_pings.items():
        if len(pings) < 2:
            continue
            
        # Sort vehicle pings chronologically
        pings.sort(key=lambda x: x["sec"])
        
        # Calculate speed for each segment
        for idx in range(len(pings)):
            speed = 15.0 # Default fallback speed in km/h (approx 4.16 m/s)
            
            if idx > 0:
                prev = pings[idx-1]
                curr = pings[idx]
                dt = curr["sec"] - prev["sec"]
                if 0 < dt < 600: # within 10 mins
                    dist = calc_dist_meters(curr["lon"], curr["lat"], prev["lon"], prev["lat"])
                    speed = (dist / dt) * 3.6 # speed in km/h
                    # Cap speed at 80 km/h to filter GPS jumps
                    if speed > 80.0:
                        speed = 15.0
            
            curr_ping = pings[idx]
            lon, lat = curr_ping["lon"], curr_ping["lat"]
            route = curr_ping["route"]
            
            # Map this ping to the closest stop serving this route
            cell_x = int(lon / grid_size)
            cell_y = int(lat / grid_size)
            
            closest_stop = None
            min_dist = float("inf")
            
            # Search cell and its 8 neighbors
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    neighbor_cell = (cell_x + dx, cell_y + dy)
                    for stop in grid[neighbor_cell]:
                        if route in stop["routes"]:
                            dist = calc_dist_meters(lon, lat, stop["lon"], stop["lat"])
                            if dist <= 100.0: # 100 meters threshold
                                if dist < min_dist:
                                    min_dist = dist
                                    closest_stop = stop
                                    
            if closest_stop:
                stop_id = closest_stop["id"]
                stop_route_visits[stop_id][route].append({
                    "sec": curr_ping["sec"],
                    "speed": speed,
                    "vehicle": vehicle
                })
                mapped_count += 1
                
    print(f"Mapped {mapped_count} pings to stops successfully.", flush=True)

    # 5. Process visits per stop and route to calculate headways and speeds
    print("Processing headways and generating metrics per stop...", flush=True)
    stop_route_metrics = {}
    
    for stop_id, routes in stop_route_visits.items():
        stop_route_metrics[stop_id] = {}
        
        for route, visits in routes.items():
            if not visits:
                continue
                
            # Group pings of the same vehicle at this stop that are within 10 minutes into a single "visit"
            visits.sort(key=lambda x: x["sec"])
            
            grouped_visits = []
            vehicle_last_sec = {}
            
            for v in visits:
                veh = v["vehicle"]
                sec = v["sec"]
                # If vehicle visited recently (within 10 mins), group it
                if veh in vehicle_last_sec and (sec - vehicle_last_sec[veh]) < 600:
                    continue
                vehicle_last_sec[veh] = sec
                grouped_visits.append(v)
                
            if len(grouped_visits) < 2:
                continue
                
            # Sort visits chronologically
            grouped_visits.sort(key=lambda x: x["sec"])
            
            # Calculate headways between consecutive arrivals in minutes
            headways = []
            speeds = []
            
            for i in range(1, len(grouped_visits)):
                h = (grouped_visits[i]["sec"] - grouped_visits[i-1]["sec"]) / 60.0 # in minutes
                # Headway must be realistic: between 1 and 120 minutes
                if 1.0 <= h <= 120.0:
                    headways.append(h)
                speeds.append(grouped_visits[i]["speed"])
                
            if headways:
                mean_headway = round(sum(headways) / len(headways), 1)
                # Calculate standard deviation
                variance = sum((x - mean_headway) ** 2 for x in headways) / len(headways)
                std_headway = round(math.sqrt(variance), 1)
                cv_headway = round(std_headway / mean_headway, 2) if mean_headway > 0 else 0.0
                avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else 15.0
                
                stop_route_metrics[stop_id][route] = {
                    "mean_headway": mean_headway,
                    "std_headway": std_headway,
                    "cv_headway": cv_headway,
                    "avg_speed": avg_speed,
                    "visits_count": len(grouped_visits)
                }

    # 6. Save precomputed dataset
    precomputed = {
        "stop_route_metrics": stop_route_metrics
    }
    
    # Save period-specific file
    out_path_period = OUT / f"gps_precomputed_{period}.json"
    with open(out_path_period, "w", encoding="utf-8") as f:
        json.dump(precomputed, f, indent=2, ensure_ascii=False)
    print(f"Period-specific JSON saved to {out_path_period}", flush=True)
    
    # Keep default for morning compatibility
    if period == "morning":
        out_path_default = OUT / "gps_precomputed.json"
        with open(out_path_default, "w", encoding="utf-8") as f:
            json.dump(precomputed, f, indent=2, ensure_ascii=False)
        print(f"Default morning JSON saved to {out_path_default}", flush=True)
        
    print("Pre-computation complete!", flush=True)

if __name__ == "__main__":
    main()
