import csv
import json
import math
from pathlib import Path
from pyproj import Transformer

# Paths
script_dir = Path(__file__).resolve().parent.parent
if (script_dir / "data").exists():
    # Workspace environment
    BASE = script_dir
    GTFS_BASE = Path("/Users/bharatoraon/Desktop/Project_1")
    GTFS_MTC = GTFS_BASE / "CUMTA_GTFS" / "MTC"
    GTFS_CMRL = GTFS_BASE / "CUMTA_GTFS" / "CMRL"
    OUT = BASE / "connectivity_dashboard"
else:
    BASE = Path("/Users/bharatoraon/Desktop/Project_1")
    GTFS_MTC = BASE / "CUMTA_GTFS" / "MTC"
    GTFS_CMRL = BASE / "CUMTA_GTFS" / "CMRL"
    OUT = BASE / "connectivity_dashboard"

CRS_WGS84 = "EPSG:4326"
CRS_METERS = "EPSG:32644"
TRANSFORMER = Transformer.from_crs(CRS_WGS84, CRS_METERS, always_xy=True).transform

def to_meters(lon, lat):
    try:
        return TRANSFORMER(float(lon), float(lat))
    except Exception:
        return 0.0, 0.0

def parse_time_to_seconds(t_str):
    try:
        parts = [int(p.strip()) for p in t_str.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return None
    except Exception:
        return None

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Precompute GTFS metrics for Chennai.")
    parser.add_argument("--period", type=str, default="morning", choices=["morning", "midday", "evening"], help="Time period to process")
    args = parser.parse_args()
    
    period = args.period
    
    # Define local time bounds (seconds from midnight)
    if period == "morning":
        peak_start = 8 * 3600   # 08:00 AM
        peak_end = 10 * 3600    # 10:00 AM
    elif period == "midday":
        peak_start = 12 * 3600  # 12:00 PM
        peak_end = 14 * 3600   # 02:00 PM
    elif period == "evening":
        peak_start = 17 * 3600  # 05:00 PM
        peak_end = 19 * 3600   # 07:00 PM
        
    print(f"Starting pre-computation of GTFS metrics for period: {period} ({peak_start//3600:02d}:00 to {peak_end//3600:02d}:00 IST)...", flush=True)

    # 1. Load MTC stops coordinates
    print("Loading MTC stops...", flush=True)
    mtc_stop_coords = {}
    with open(GTFS_MTC / "stops.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            sid = row["stop_id"].strip()
            lon = row["stop_lon"].strip()
            lat = row["stop_lat"].strip()
            if sid and lon and lat:
                mtc_stop_coords[sid] = (float(lon), float(lat))
    print(f"Loaded {len(mtc_stop_coords)} MTC stop coordinates.", flush=True)

    # 2. Load MTC routes & trips
    print("Loading MTC routes and trips...", flush=True)
    mtc_route_id_to_short = {}
    with open(GTFS_MTC / "routes.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            rid = row["route_id"].strip()
            short = row["route_short_name"].strip()
            if rid and short:
                mtc_route_id_to_short[rid] = short

    mtc_trip_id_to_route_id = {}
    with open(GTFS_MTC / "trips.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            tid = row["trip_id"].strip()
            rid = row["route_id"].strip()
            if tid and rid:
                mtc_trip_id_to_route_id[tid] = rid

    # 3. Load MTC frequencies and filter for peak hours
    print("Loading MTC frequencies...", flush=True)
    mtc_trip_peak_headways = {}
    with open(GTFS_MTC / "frequencies.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            tid = row["trip_id"].strip()
            start_s = parse_time_to_seconds(row["start_time"])
            end_s = parse_time_to_seconds(row["end_time"])
            headway = row["headway_secs"].strip()
            
            if start_s is not None and end_s is not None and headway:
                # Trip is active during peak if it overlaps with 08:00 - 10:00
                if start_s <= peak_end and end_s >= peak_start:
                    headway_val = float(headway) / 60.0  # convert to minutes
                    if tid not in mtc_trip_peak_headways or headway_val < mtc_trip_peak_headways[tid]:
                        mtc_trip_peak_headways[tid] = headway_val
    print(f"Loaded {len(mtc_trip_peak_headways)} peak MTC trip headways.", flush=True)

    # 4. Load MTC stop times (stream to save memory)
    # Calculate stop headways and reconstruct route sequences
    print("Processing MTC stop times (this may take a moment)...", flush=True)
    mtc_stop_route_headways = {}
    mtc_trip_sequences = {} # trip_id -> list of (stop_sequence, stop_id)
    
    with open(GTFS_MTC / "stop_times.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            tid = row["trip_id"].strip()
            sid = row["stop_id"].strip()
            seq = int(row["stop_sequence"].strip())
            
            # Record sequence for route sequence reconstruction
            if tid not in mtc_trip_sequences:
                mtc_trip_sequences[tid] = []
            mtc_trip_sequences[tid].append((seq, sid))
            
            # Aggregate headway if this trip is active during peak
            if tid in mtc_trip_peak_headways:
                rid = mtc_trip_id_to_route_id.get(tid)
                if rid:
                    r_name = mtc_route_id_to_short.get(rid)
                    if r_name:
                        headway_val = mtc_trip_peak_headways[tid]
                        if sid not in mtc_stop_route_headways:
                            mtc_stop_route_headways[sid] = {}
                        if r_name not in mtc_stop_route_headways[sid] or headway_val < mtc_stop_route_headways[sid][r_name]:
                            mtc_stop_route_headways[sid][r_name] = headway_val

    # Reconstruct the representative stop sequences for each route
    # For each route_id, choose the trip with the most stop sequences as representative
    print("Reconstructing MTC route stop sequences...", flush=True)
    mtc_route_trips = {} # route_id -> trip_id with max stops
    for tid, seqs in mtc_trip_sequences.items():
        rid = mtc_trip_id_to_route_id.get(tid)
        if rid:
            if rid not in mtc_route_trips or len(seqs) > len(mtc_trip_sequences[mtc_route_trips[rid]]):
                mtc_route_trips[rid] = tid

    # Reconstruct cumulative distances along route stop sequences
    mtc_route_stop_distances = {} # route_short_name -> list of {stop_id: cumulative_dist_m}
    # To handle multiple directions/variants of the same route_short_name:
    # We group by route_short_name and collect sequences
    mtc_name_to_sequences = {} # route_short_name -> list of lists of stop_ids
    for rid, tid in mtc_route_trips.items():
        r_name = mtc_route_id_to_short.get(rid)
        if not r_name:
            continue
        seqs = sorted(mtc_trip_sequences[tid], key=lambda x: x[0])
        stop_ids = [s[1] for s in seqs]
        if r_name not in mtc_name_to_sequences:
            mtc_name_to_sequences[r_name] = []
        mtc_name_to_sequences[r_name].append(stop_ids)

    # Compute distances
    print("Computing route cumulative distances...", flush=True)
    for r_name, seq_variants in mtc_name_to_sequences.items():
        mtc_route_stop_distances[r_name] = []
        for stop_ids in seq_variants:
            dist_map = {}
            cum_dist = 0.0
            prev_xy = None
            for i, sid in enumerate(stop_ids):
                coords = mtc_stop_coords.get(sid)
                if coords:
                    xy = to_meters(coords[0], coords[1])
                    if prev_xy is not None:
                        d = math.sqrt((xy[0] - prev_xy[0])**2 + (xy[1] - prev_xy[1])**2)
                        cum_dist += d
                    prev_xy = xy
                dist_map[sid] = round(cum_dist, 1)
            mtc_route_stop_distances[r_name].append(dist_map)

    # 5. Process CMRL Metro headways
    print("Processing CMRL Metro stop times...", flush=True)
    cmrl_route_id_to_short = {}
    with open(GTFS_CMRL / "routes.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            rid = row["route_id"].strip()
            short = row["route_short_name"].strip()
            if rid and short:
                cmrl_route_id_to_short[rid] = short

    cmrl_trip_id_to_route_id = {}
    with open(GTFS_CMRL / "trips.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            tid = row["trip_id"].strip()
            rid = row["route_id"].strip()
            if tid and rid:
                cmrl_trip_id_to_route_id[tid] = rid

    # Load stop info (to map platform stop -> parent station)
    cmrl_stop_to_parent = {}
    cmrl_parent_stops = {} # stop_id -> stop_name
    with open(GTFS_CMRL / "stops.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            sid = row["stop_id"].strip()
            loc_type = row["location_type"].strip()
            parent = row["parent_station"].strip()
            name = row["stop_name"].strip()
            
            if loc_type == "1":
                cmrl_parent_stops[sid] = name
            else:
                if parent:
                    cmrl_stop_to_parent[sid] = parent

    # Track arrival times per stop and route name
    cmrl_stop_route_times = {} # stop_id -> {route_short_name: list of arrival_seconds}
    with open(GTFS_CMRL / "stop_times.txt", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            tid = row["trip_id"].strip()
            sid = row["stop_id"].strip()
            arr_time = row["arrival_time"].strip()
            arr_s = parse_time_to_seconds(arr_time)
            
            if arr_s is not None:
                # Check if trip is in peak window
                if peak_start <= arr_s <= peak_end:
                    rid = cmrl_trip_id_to_route_id.get(tid)
                    if rid:
                        r_name = cmrl_route_id_to_short.get(rid)
                        if r_name:
                            # Map to parent station if possible
                            parent = cmrl_stop_to_parent.get(sid, sid)
                            if parent not in cmrl_stop_route_times:
                                cmrl_stop_route_times[parent] = {}
                            if r_name not in cmrl_stop_route_times[parent]:
                                cmrl_stop_route_times[parent][r_name] = []
                            cmrl_stop_route_times[parent][r_name].append(arr_s)

    # Calculate CMRL headways
    cmrl_station_headways = {} # parent_stop_id -> {route_short_name: headway_mins}
    for parent, routes in cmrl_stop_route_times.items():
        cmrl_station_headways[parent] = {}
        for r_name, times in routes.items():
            times.sort()
            diffs = []
            for i in range(1, len(times)):
                diffs.append((times[i] - times[i-1]) / 60.0)
            
            if diffs:
                # Find median headway
                diffs.sort()
                median_headway = diffs[len(diffs) // 2]
                cmrl_station_headways[parent][r_name] = round(median_headway, 1)
            else:
                # Single arrival in peak hour, default to 10.0 min
                cmrl_station_headways[parent][r_name] = 10.0
    
    print(f"Processed CMRL peak headways for {len(cmrl_station_headways)} metro stations.", flush=True)

    # 6. Save precomputed dataset
    precomputed = {
        "mtc_bus_headways": mtc_stop_route_headways,
        "mtc_route_stop_distances": mtc_route_stop_distances,
        "cmrl_metro_headways": cmrl_station_headways,
        "cmrl_parent_stops": cmrl_parent_stops
    }
 
    # Save period-specific file
    out_path_period = OUT / f"gtfs_precomputed_{period}.json"
    with open(out_path_period, "w", encoding="utf-8") as f:
        json.dump(precomputed, f, indent=2, ensure_ascii=False)
    print(f"Period-specific JSON saved to {out_path_period}", flush=True)
    
    # Keep default for morning compatibility
    if period == "morning":
        out_path_default = OUT / "gtfs_precomputed.json"
        with open(out_path_default, "w", encoding="utf-8") as f:
            json.dump(precomputed, f, indent=2, ensure_ascii=False)
        print(f"Default morning JSON saved to {out_path_default}", flush=True)
        
    print("Pre-computation complete!", flush=True)

if __name__ == "__main__":
    main()
