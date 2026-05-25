# Senior GIS Methodology Report: CMA Bus Terminal Connectivity

## Purpose

This analysis evaluates how bus stops inside the Chennai Metropolitan Area connect to bus terminals/facilities using the available MTC route, bus stop, bus terminus, and CMA boundary datasets.

The current scope is **bus-only**. Metro and suburban rail are not included in this version.

## Final Facility Definition

For this phase, **Depot and Terminal are treated as the same operational category**:

```text
Depot + Terminal = Bus Terminal / Facility
```

This means any route endpoint or mapped facility that functions as a depot, terminus, bus stand, or major bus facility is grouped into one target class called **Terminal**.

## Input Layers

- `CMA.geojson` - Chennai Metropolitan Area boundary.
- `all_mtc_routes.geojson` - MTC route geometries with route name, source, and destination.
- `mtc_bus_stops_all.geojson` - bus stop points with stop name and route list.
- `bus_terminus.geojson` - mapped bus terminus/facility points.

## Output Layers

- `bus_stops_connectivity.geojson` - bus stops with terminal connectivity fields.
- `bus_routes_enriched.geojson` - routes with terminal endpoint flags.
- `bus_facilities_enriched.geojson` - terminal/facility points.
- `connectivity_summary.json` - dashboard statistics.
- `not_connected_bus_stops.csv` - remaining stops without route-network connection to a terminal/facility.

## Network Logic

The analysis is based on a **route-transfer graph**.

Each bus route is treated as a network node. Two routes are connected when they share at least one bus stop.

Example:

```text
Stop A: Route 10, Route 20
Stop B: Route 20, Route 30
```

Because Route 10 and Route 20 share Stop A, a passenger can transfer between those routes at that stop. Because Route 20 and Route 30 share Stop B, those routes are also connected.

The model then searches from every bus stop's available routes to the nearest route that reaches a terminal/facility.

## Connectivity Classification

The classification is based on the minimum number of bus routes required to reach a terminal/facility.

```text
Direct              = one of the stop's routes directly reaches a terminal/facility
2 buses             = one route transfer is required
3 buses             = two route transfers are required
4+ buses            = three or more route transfers are required
No route connection = no path found in the provided route-stop data
```

Formula:

```text
Minimum buses needed = shortest route-transfer distance + 1
```

So:

```text
0 transfers + 1 = Direct
1 transfer  + 1 = 2 buses
2 transfers + 1 = 3 buses
3+ transfers     = 4+ buses
```

## Terminal / Facility Identification

Terminal/facility points come from two sources:

1. **Mapped terminals**

   These come directly from `bus_terminus.geojson`.

2. **Inferred terminal/facility points**

   Some MTC route source/destination names contain `Depot`, for example:

   ```text
   Thiruvanmiyur Depot
   Ennore Bus Depot
   CMBT Koyembedu Bus Depot
   ```

   Since depot and terminal are now treated as one class, these are grouped into the same **Terminal** category. Their approximate locations are inferred from route geometry endpoints.

## Current Results Inside CMA

Current CMA bus stop count:

```text
4,145 bus stops
```

Terminal connectivity result:

```text
Direct:              4,039 stops
2 buses:               106 stops
3 buses:                 0 stops
4+ buses:                0 stops
No route connection:     0 stops
```

The dashboard now displays all categories, including zero-count categories.

## Why 3 Buses and 4+ Buses Are Zero

The logic supports `3 buses` and `4+ buses`.

They are zero in the current output because, after grouping depot and terminal together, almost every CMA stop either:

- has a direct route to a terminal/facility, or
- can reach such a route with one transfer.

This indicates a strongly connected route network under the available route-stop data.

It does **not** mean the categories were ignored. It means no stop currently falls into those categories.

## QA Correction

Manual map validation showed that two initially unconnected records are actual bus facility locations:

- Kundrathur Bus Depot
- Chennai Koyambedu Mofussil Bus Stand

They were corrected to:

```text
Direct
```

Reason: the point itself represents a terminal/facility location, but the source route attributes did not join cleanly to the route network.

An additional parser QA correction was made after reviewing the remaining unconnected record:

```text
Metrological Department Sterling Road
```

Its `route name` field was stored as a malformed text string rather than a clean route list. After cleaning bracket and quote characters during parsing, the stop produced 27 valid route matches and is now classified as:

```text
Direct
```

There are currently no CMA bus stops classified as `No route connection`.

## Accuracy Statement

This analysis is suitable for **GIS network-level connectivity assessment**.

It measures:

```text
Route availability connectivity
```

It does not measure:

- real-time service availability
- bus frequency
- timetable waiting time
- direction-specific routing
- fare integration
- crowding
- first/last-mile walking inside terminals
- operational disruptions

## Data Limitations

The accuracy depends on the quality of the source datasets.

Known limitations:

- Some bus stop route lists are malformed strings rather than clean route arrays.
- Some route names appear with duplicate or inconsistent formatting.
- Terminal/facility locations inferred from route endpoints are approximate.
- A shared stop is treated as a valid transfer point, but field conditions were not verified for every transfer.
- The route graph is not direction-sensitive.

## Interpretation Guidance

Use this dashboard to answer:

```text
How many bus rides are needed for a CMA bus stop to connect to a bus terminal/facility?
```

Do not interpret it as a full passenger journey planner.

The result should be described as:

```text
Bus route connectivity to terminal/facility network, based on available route-stop GIS data.
```

## Recommended Next QA Steps

- Clean malformed route-list strings in the bus stop layer.
- Standardize route names across route and stop datasets.
- Verify inferred terminal/facility points against official MTC/CMDA sources.
- Add direction-aware route modeling if operational journey planning is required.
- Add service frequency or GTFS data if accessibility by travel time is required.
