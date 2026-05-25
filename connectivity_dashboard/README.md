# CMA Bus Terminal Connectivity Dashboard

This folder contains a bus-only GIS analysis and interactive dashboard for the Chennai Metropolitan Area.

## Outputs

- `index.html` - Leaflet dashboard for viewing CMA boundary, MTC bus routes, bus stops, and bus terminals/facilities.
- `build_connectivity.py` - analysis script that regenerates the enriched bus-only layers.
- `bus_stops_connectivity.geojson` - bus stops enriched with terminal connectivity fields.
- `bus_routes_enriched.geojson` - MTC routes enriched with stop counts and terminal endpoint flags.
- `bus_facilities_enriched.geojson` - bus terminals from `bus_terminus.geojson` plus inferred terminal/facility points from route endpoints whose names contain `Depot`.
- `connectivity_summary.json` - headline counts used by the dashboard charts.
- `not_connected_bus_stops.csv` - bus stops still classified as not connected after QA correction; currently this has no records inside CMA.

## Method

Depot and terminal are treated as the same category: **Terminal**.

Bus stop to terminal connectivity is modeled as a route-transfer graph:

- Each bus route is connected to other routes when they share at least one bus stop.
- A bus stop is `Direct` when one of its serving routes reaches a terminal/facility.
- `2 buses`, `3 buses`, and `4+ buses` represent the minimum number of bus routes needed through shared-stop transfers.
- `No route connection` means the provided route data could not trace a connection to a terminal/facility.

Bus terminals come from `bus_terminus.geojson`. Route endpoints whose names contain `Depot` are grouped into the same **Terminal** category as inferred terminal/facility points.

Two facility-name stop records were manually QA-corrected after map review:

- Kundrathur Bus Depot
- Chennai Koyambedu Mofussil Bus Stand

They are treated as directly connected terminal/facility locations because the stop itself represents a facility location, even though the source route attributes did not join cleanly.

## Run

From this folder:

```bash
python3 build_connectivity.py
python3 -m http.server 8765
```

Then open:

```text
http://127.0.0.1:8765/index.html
```
