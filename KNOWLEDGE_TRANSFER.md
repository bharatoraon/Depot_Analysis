# Knowledge Transfer: Chennai Multimodal Transit Connectivity and Performance Gap Dashboard

This document provides a highly detailed, engineering-grade explanation of the system architecture, mathematical formulations, algorithmic logic, and source code implementations deployed in the Chennai Multimodal Transit Connectivity and Performance Gap project.

---

## 1. System Architecture & Data Flow

The system uses a decoupled structure: a Python-based ETL pipeline executes precomputations and modeling, outputting static GeoJSON and JSON files. The web client (HTML/JS/Leaflet) loads these pre-computed files dynamically, avoiding database queries and server-side runtime overhead.

```
+-----------------------------------------------------------------------------------+
|                              1. RAW INPUT DATASETS                                |
|  - MTC Bus GTFS: routes.txt, trips.txt, stop_times.txt, frequencies.txt           |
|  - CMRL Metro GTFS: routes.txt, trips.txt, stop_times.txt, parent_stations        |
|  - Amnex GPS Telemetry: Raw coordinates, timestamps, vehicle IDs (~5.5 GB CSVs)   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        2. PERIOD-SPECIFIC PRECOMPUTATIONS                         |
|  [precompute_gtfs_metrics.py]                 [precompute_gps_metrics.py]         |
|  - Filter by active period (Local IST)        - Filter by active period (UTC)     |
|  - MEDIAN Metro headways                      - Grid spatial index (O(1) lookups) |
|  - Route cumulative distances                 - Speed & Arrival visits resolver   |
+-----------------------------------------------------------------------------------+
                  |                                      |
                  v (gtfs_precomputed_{period}.json)     v (gps_precomputed_{period}.json)
+-----------------------------------------------------------------------------------+
|                          3. CONNECTIVITY MODELING ENGINE                          |
|  [build_connectivity.py]                                                          |
|  - Ingest precomputed sched/emp metrics & static layers                           |
|  - Multimodal transfer graph generation (walking links < 200m)                    |
|  - Multimodal RAPTOR routing (hops to nearest terminals)                           |
|  - Mathematically calculate PTAL & NHI scorecard (Scheduled vs. GPS-Empirical)     |
|  - Apply spatial clipping against CMA boundary polygon                            |
+-----------------------------------------------------------------------------------+
                  |
                  +----------------------------------+-----------------------------+
                  |                                  |                             |
                  v (stops connectivity GeoJSON)     v (metro enriched GeoJSON)    v (summary JSON)
+---------------------------------------------------+  +-------------------------------------------+
|       4. CORE MAP DASHBOARD (index.html)          |  |   5. PERFORMANCE TRACKER (compare.html)   |
| - Switch Period Dropdown toggles JS loads         |  | - Switch Period Dropdown recalculates deltas|
| - Render Leaflet layers (stops, routes, rail)     |  | - Colors stops on Red-Gray-Green scale    |
| - Render KPI counters and sidebar bar charts      |  | - Sidebar Top 5 Service Bottlenecks list  |
+---------------------------------------------------+  +-------------------------------------------+
```

---

## 2. Time Period Partitioning (IST to UTC)

The telemetry datasets contain timestamps in UTC, whereas GTFS schedules use Chennai local time (IST = UTC + 5:30). The pipeline filters and partitions the data into three periods:

1. **Morning Peak**:
   * Local Time IST: **08:00 - 10:00 AM**
   * Telemetry UTC: **02:30:00 - 04:30:00**
   * Input GPS files: `amnex_direct_data_2026-05-20_06-09.csv` & `amnex_direct_data_2026-05-20_09-12.csv`
2. **Midday Off-Peak**:
   * Local Time IST: **12:00 - 02:00 PM**
   * Telemetry UTC: **06:30:00 - 08:30:00**
   * Input GPS files: `amnex_direct_data_2026-05-20_12-15.csv`
3. **Evening Peak**:
   * Local Time IST: **05:00 - 07:00 PM**
   * Telemetry UTC: **11:30:00 - 13:30:00**
   * Input GPS files: `amnex_direct_data_2026-05-20_15-18.csv` & `amnex_direct_data_2026-05-20_18-21.csv`

---

## 3. Mathematical Formulations

### 3.1 Public Transport Accessibility Level (PTAL)

#### Step 3.1.1: Walking Access Time ($WalkTime$)
Walk time is calculated from a stop to all neighboring nodes within walking buffers ($640\text{m}$ for bus/terminals, $960\text{m}$ for rail) at a constant walk speed of 80 meters/minute:
$$WalkTime_{j} = \frac{D_{j} \text{ (meters)}}{80 \text{ m/min}}$$

#### Step 3.1.2: Scheduled Wait Time ($SWT$)
Determines average wait times, factoring in mode-specific reliability margins:
$$SWT_{j,r} = \left(0.5 \times Headway_{j,r}\right) + Margin_{mode}$$
*Reliability Margins ($Margin_{mode}$): Bus = 2.0 min, Metro = 0.75 min, Suburban = 1.50 min.*

* **Headway ($Headway_{j,r}$) values**:
  - **Scheduled**: Extracted from GTFS `frequencies.txt` or `stop_times.txt` for MTC bus and CMRL metro. Falls back to a route-count headway proxy if GTFS data is missing.
  - **GPS-Empirical**: Replaced by observed headways calculated from vehicle pings at that stop for route $r$.

#### Step 3.1.3: Total Access Time ($AT$)
$$AT_{j,r} = WalkTime_{j} + SWT_{j,r}$$

#### Step 3.1.4: Accessibility Index ($AI$)
Sorts all accessible routes at stop $i$ by $AT$. The route with the minimum access time ($AT_{dom}$) is weighted fully ($1.0$), while all other non-dominant routes are weighted at $50\%$ ($0.5$):
$$AI_i = \frac{30}{AT_{dom}} + 0.5 \times \sum_{k=1}^{R-1} \left(\frac{30}{AT_{non-dom,k}}\right)$$

#### Step 3.1.5: PTAL Grade Mapping
The index value ($AI$) maps to standard London PTAL grades:
- $AI = 0 \rightarrow$ **Grade 0** (No access)
- $0 < AI \le 2.5 \rightarrow$ **Grade 1a** (Very Poor)
- $2.5 < AI \le 5.0 \rightarrow$ **Grade 1b**
- $5.0 < AI \le 10.0 \rightarrow$ **Grade 2** (Poor)
- $10.0 < AI \le 15.0 \rightarrow$ **Grade 3** (Moderate)
- $15.0 < AI \le 20.0 \rightarrow$ **Grade 4** (Good)
- $20.0 < AI \le 25.0 \rightarrow$ **Grade 5** (Very Good)
- $25.0 < AI \le 40.0 \rightarrow$ **Grade 6a** (Excellent)
- $AI > 40.0 \rightarrow$ **Grade 6b** (Excellent)

---

### 3.2 Network Health Index (NHI)

NHI measures transit service quality, directness, and efficiency on a scale of 0 to 100.

#### A. Scheduled (Timetabled) NHI Formulation:
$$NHI_{Sch} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.2 \times S_{resilience}$$

#### B. GPS-Empirical NHI Formulation:
$$NHI_{GPS} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.1 \times S_{reliability} + 0.1 \times S_{speed}$$

#### Step 3.2.1: Directness Score ($S_{directness}$ — 30%)
Compares route distance along the bus stop sequence against Euclidean straight-line distance to the closest terminal:
$$\text{Circuity}_i = \frac{\text{RouteDistance}_{i,\text{hub}}}{\text{EuclideanDistance}_{i,\text{hub}}}$$
$$S_{directness} = \max\left(0, 100 \times \left(2.0 - \text{Circuity}_i\right)\right)$$
*If the stop has direct terminal access (0 transfers), $S_{directness} = 100$. If 2 transfers are required, it defaults to 50; if 3 transfers are required, it defaults to 0.*

#### Step 3.2.2: Transfer Friction Score ($S_{transfer}$ — 30%)
Penalizes transfer hops required to connect to the closest terminal:
* **0 transfers (Direct)**: **100 points**
* **1 transfer (2 routes)**: **70 points**
* **2 transfers (3 routes)**: **30 points**
* **3+ transfers / Disconnected**: **0 points**

#### Step 3.2.3: Multimodal Integration ($S_{multimodal}$ — 20%)
Awards **100 points** if the stop is within **200 meters** of a Metro or Suburban Rail station; otherwise **0 points**.

#### Step 3.2.4: Network Resilience ($S_{resilience}$ — 20%, Scheduled Only)
Meures protection against single-line disruptions through route redundancy:
$$S_{resilience} = 100 \times \left(1 - e^{-0.3 \times \left(\text{RoutesCount}_i - 1\right)}\right)$$

#### Step 3.2.5: Headway Reliability ($S_{reliability}$ — 10%, GPS-Empirical Only)
Penalizes headway irregularity based on the Coefficient of Variation ($CV = \sigma / \mu$) of observed arrivals at stop $i$:
$$S_{reliability} = \max\left(0, \min\left(100, 100 \times \left(\frac{1.2 - CV}{1.2 - 0.2}\right)\right)\right)$$
*If $CV \le 0.2$ (highly regular): Score = 100. If $CV \ge 1.2$ (severely bunched/unreliable): Score = 0.*

#### Step 3.2.6: Travel Speed ($S_{speed}$ — 10%, GPS-Empirical Only)
Scores stops based on average observed travel speeds ($V_{avg}$) to incorporate traffic congestion:
$$S_{speed} = \max\left(0, \min\left(100, 100 \times \left(\frac{V_{avg} - 6.0}{25.0 - 6.0}\right)\right)\right)$$
*If Speed $\ge 25\text{ km/h}$: Score = 100. If Speed $\le 6\text{ km/h}$ (severe congestion): Score = 0.*

---

## 4. Key Logics & Routing Algorithms

### 4.1 Spatial Walk-Transfer Network Generation
To link separate transit lines, a spatial transfer network is generated. For every MTC bus stop, the ETL engine searches for neighboring stops of all modes (bus, metro, suburban rail) within a **200-meter walk buffer**. A walk link is added in the transit graph between the stops, enabling multimodal transfer modeling.

### 4.2 Multimodal RAPTOR (Round-Based Public Transit Routing)
The RAPTOR routing algorithm explores transit path options round-by-round to find the minimum transfer hops and travel times:
1. **Initialization**: Clear all marked stops. Set the transfer count for the source stop to 0, and set all other stops to infinity.
2. **Round 1 (Direct Routes)**: Find all routes serving the source stop. Traverse each route downstream and update the transfer count to 1 for all reached stops.
3. **Footpaths**: For each stop reached in Round 1, check the spatial transfer network. If a neighboring stop is within 200 meters, update its transfer count to 1 (walking transfer).
4. **Round 2 (1 Transfer)**: Find all routes serving the stops reached in Round 1. Traverse these routes downstream and update the transfer count to 2 (requiring 2 routes) for all newly reached stops.
5. **Round 3 (2 Transfers)**: Repeat for the next transfer level.
6. **Target Extraction**: Find the minimum transfers required to reach any designated terminal/facility node.

---

## 5. Annotated Source Code Snippets

### 5.1 Spatial Grid Cell Indexing (`precompute_gps_metrics.py`)
This grid index groups stops into spatial cells to map GPS pings in $O(1)$ constant time instead of slow $O(N \times M)$ comparisons.

```python
# Grid size definition (~220m cells near Chennai lat ~13N)
grid_size = 0.002
grid = defaultdict(list)

# Load stops and bin them into spatial cells
for stop in stops_raw["features"]:
    lon, lat = stop["geometry"]["coordinates"]
    stop_node = {
        "id": stop["properties"]["Stop Id"],
        "name": stop["properties"]["Stop Name"],
        "lon": lon, "lat": lat,
        "routes": set(route_list(stop["properties"]["route name"]))
    }
    
    # Calculate cell keys
    cell = (int(lon / grid_size), int(lat / grid_size))
    grid[cell].append(stop_node)

# Spatial Query Logic for a GPS Ping (lon, lat) on route_name
cell_x = int(lon / grid_size)
cell_y = int(lat / grid_size)
closest_stop = None
min_dist = float("inf")

# Search only the active cell and its 8 adjacent neighbor cells
for dx in [-1, 0, 1]:
    for dy in [-1, 0, 1]:
        neighbor_cell = (cell_x + dx, cell_y + dy)
        for stop in grid[neighbor_cell]:
            if route_name in stop["routes"]:
                dist = calc_dist_meters(lon, lat, stop["lon"], stop["lat"])
                if dist <= 100.0 and dist < min_dist: # 100m threshold
                    min_dist = dist
                    closest_stop = stop
```

### 5.2 GPS Headway Visit Solver (`precompute_gps_metrics.py`)
Calculates empirical headways by detecting discrete vehicle arrivals and sorting them chronologically.

```python
# Group consecutive pings of same vehicle within 10 minutes into a single "visit"
visits.sort(key=lambda x: x["sec"])
grouped_visits = []
vehicle_last_sec = {}

for v in visits:
    veh = v["vehicle"]
    sec = v["sec"]
    # If the vehicle visited this stop recently (under 10 mins), group it
    if veh in vehicle_last_sec and (sec - vehicle_last_sec[veh]) < 600:
        continue
    vehicle_last_sec[veh] = sec
    grouped_visits.append(v)

# Sort discrete visits chronologically
grouped_visits.sort(key=lambda x: x["sec"])

# Calculate arrival headway intervals in minutes
headways = []
for i in range(1, len(grouped_visits)):
    h = (grouped_visits[i]["sec"] - grouped_visits[i-1]["sec"]) / 60.0
    if 1.0 <= h <= 120.0:  # Cap at realistic bounds
        headways.append(h)
```

### 5.3 PTAL Accessibility Index (`build_connectivity.py`)
Computes walking access times, scheduled wait times, access times, and sorts them to run the weighted PTAL summation.

```python
def calculate_ptal(stop_id, nodes, stop_routes, tree, all_node_list, gtfs_data, gps_data):
    stop_node = nodes[stop_id]
    stop_geom_m = stop_node["geom_m"]
    route_access_times = {}
    
    # Query spatial index tree for all transit nodes within 960m walk buffer
    candidate_indices = tree.query(stop_geom_m.buffer(960.0))
    
    for idx in candidate_indices:
        node = all_node_list[idx]
        nid = node["id"]
        mode = node["type"]
        dist_m = stop_geom_m.distance(node["geom_m"])
        
        # Enforce mode-specific walk thresholds
        max_walk = 960.0 if mode in ("metro", "suburban") else 640.0
        if dist_m > max_walk:
            continue
            
        walk_time = dist_m / 80.0  # 80 meters/minute
        
        # Extract headways per route serving this node
        for route in node["routes"]:
            headway = get_headway(nid, route, mode, gtfs_data, gps_data)
            swt = (0.5 * headway) + get_reliability_margin(mode)
            access_time = walk_time + swt
            
            # Record the minimum access time for this route
            if route not in route_access_times or access_time < route_access_times[route]:
                route_access_times[route] = access_time
                
    # Sort access times to compute weighted PTAL
    sorted_times = sorted(route_access_times.values())
    if not sorted_times:
        return 0.0, "0"
        
    # Dominant route weighted fully; non-dominant routes weighted at 50%
    dominant_at = sorted_times[0]
    ai = 30.0 / dominant_at
    for at in sorted_times[1:]:
        ai += 0.5 * (30.0 / at)
        
    grade = map_ai_to_ptal_grade(ai)
    return ai, grade
```

### 5.4 GPS-Empirical NHI Scorecard (`build_connectivity.py`)
Evaluates the Network Health Index scorecard incorporating travel speeds and headway reliability.

```python
# 1. Directness Score (30%)
circuity = route_distance / euclidean_distance if euclidean_distance > 0 else 1.0
s_directness = max(0.0, 100.0 * (2.0 - circuity))

# 2. Transfer Friction Score (30%)
transfer_scores = {0: 100.0, 1: 70.0, 2: 30.0}
s_transfer = transfer_scores.get(min_transfers, 0.0)

# 3. Multimodal Integration (20%)
s_multimodal = 100.0 if within_200m_of_rail else 0.0

# 4. GPS-Empirical Reliability Score (10%)
# cv = headway_std / headway_mean
s_reliability = 100.0
if cv is not None:
    # Scale linearly between CV=0.2 (100 pts) and CV=1.2 (0 pts)
    s_reliability = max(0.0, min(100.0, 100.0 * ((1.2 - cv) / 1.0)))

# 5. GPS-Empirical Travel Speed Score (10%)
s_speed = 100.0
if avg_speed is not None:
    # Scale linearly between 6 km/h (0 pts) and 25 km/h (100 pts)
    s_speed = max(0.0, min(100.0, 100.0 * ((avg_speed - 6.0) / 19.0)))

# Final Summation
nhi_gps_score = (0.3 * s_directness) + (0.3 * s_transfer) + (0.2 * s_multimodal) + (0.1 * s_reliability) + (0.1 * s_speed)
```

---

## 6. Frontend JS Controller Details

Both HTML dashboards employ re-triggerable asynchronous loaders. When the period dropdown is changed, it triggers the loading of the corresponding datasets and updates the view.

```javascript
// Switching period dynamically in the dashboard client
function switchPeriod(period) {
  // Show loading indicator
  document.getElementById("statusPill").textContent = "Loading data for selected period...";
  
  // Define period-specific URLs
  const periodFiles = {
    summary: `connectivity_summary_${period}.json`,
    stops: `bus_stops_connectivity_${period}.geojson`,
    metroStations: `metro_stations_enriched_${period}.geojson`
  };
  
  // Fetch files concurrently
  Promise.all(Object.entries(periodFiles).map(([key, path]) => 
    fetch(path).then(res => res.json()).then(json => [key, json])
  ))
  .then(entries => {
    // Overwrite the globally active data object with the new period's files
    entries.forEach(([key, json]) => {
      data[key] = json;
    });
    
    // Update KPIs using the new summary
    document.getElementById("kpiStops").textContent = data.summary.counts.bus_stops_inside_cma;
    
    // Rebuild Leaflet map layers and redraw marker points
    switchMode(analysisMode);
    
    document.getElementById("statusPill").textContent = `${period.toUpperCase()} Peak loaded`;
  })
  .catch(error => {
    document.getElementById("statusPill").textContent = `Error loading data: ${error.message}`;
    console.error(error);
  });
}
```
