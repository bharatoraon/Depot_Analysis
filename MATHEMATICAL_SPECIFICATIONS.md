# Mathematical Specifications: Chennai Transit Connectivity & Performance Analysis

This document provides a formal, comprehensive mathematical specification of all calculations, metrics, scores, and algorithms used in the Chennai Multimodal Transit Connectivity and Performance Gap Analysis.

---

## 1. Spatial & Geodetic Calculations

### 1.1 Fast Euclidean Geodetic Approximation (Meters)
Used in the GPS pre-computation pipeline for high-speed spatial distance checks near Chennai (latitude $\approx 13^\circ\text{N}$):

$$D = \sqrt{\Delta y^2 + \Delta x^2}$$

Where:
$$\Delta y = (\text{lat}_1 - \text{lat}_2) \times 111,100.0$$
$$\Delta x = (\text{lon}_1 - \text{lon}_2) \times 108,200.0$$
* $111,100.0$ is the approximate length of one degree of latitude in meters.
* $108,200.0$ is the approximate length of one degree of longitude in meters at $13^\circ\text{N}$ latitude ($111,320 \times \cos(13^\circ) \approx 108,460\text{ m}$; calibrated here to $108,200\text{ m}$ for the study area).

### 1.2 Rigorous Coordinate Projection (PyProj)
Used in the GTFS schedule processor and main routing ETL for cumulative distance calculations:
$$(\text{lon}, \text{lat}) \xrightarrow{\text{Transformer}} (X, Y) \text{ in meters}$$
* **Source CRS**: `EPSG:4326` (WGS84 ellipsoidal coordinates)
* **Target CRS**: `EPSG:32644` (WGS84 / UTM Zone 44N projection for Chennai)
* **Euclidean Projected Distance**:
  $$D_{proj} = \sqrt{(X_1 - X_2)^2 + (Y_1 - Y_2)^2}$$

---

## 2. GPS Telemetry Speeds & Headways

### 2.1 Reconstructed Segment Travel Speed
For consecutive pings $p_{t-1}$ and $p_{t}$ from the same vehicle $v$ along a route:

$$V_{seg} = \left(\frac{D(p_{t-1}, p_{t})}{\Delta t}\right) \times 3.6$$

Where:
* $D(p_{t-1}, p_{t})$ is the geodetic distance in meters (using equation 1.1).
* $\Delta t = t_{\text{sec}} - (t-1)_{\text{sec}}$ is the elapsed time in seconds.
* $3.6$ is the conversion factor from m/s to km/h.
* **Filter Conditions**:
  $$V_{\text{reconstructed}} = \begin{cases} 
      V_{seg} & \text{if } 0 < \Delta t < 600\text{ sec and } 0 \le V_{seg} \le 80.0\text{ km/h} \\
      15.0\text{ km/h} & \text{otherwise (fallback default)}
  \end{cases}$$

### 2.2 Observed Headway Metrics
For sorted arrival timestamps $T = \{t_1, t_2, \dots, t_K\}$ of a route at a stop during the active time period:

1. **Individual observed headways ($h_i$)**:
   $$h_i = \frac{t_{i} - t_{i-1}}{60.0} \text{ (minutes), } \forall i \in \{2, \dots, K\}$$
   *Filter constraint: $1.0 \le h_i \le 120.0$ minutes. Arrivals outside this range are excluded.*

2. **Mean Observed Headway ($\mu$)**:
   $$\mu = \frac{1}{N_{filtered}} \sum_{i=1}^{N_{filtered}} h_i$$

3. **Standard Deviation of Headways ($\sigma$)**:
   $$\sigma = \sqrt{\frac{1}{N_{filtered}} \sum_{i=1}^{N_{filtered}} (h_i - \mu)^2}$$

4. **Coefficient of Variation ($CV$)**:
   $$CV = \begin{cases} 
      \frac{\sigma}{\mu} & \text{if } \mu > 0 \\
      0.0 & \text{otherwise}
   \end{cases}$$

---

## 3. Public Transport Accessibility Level (PTAL)

Calculated at each stop $i$ by exploring walk-accessible transit nodes $j$ within the service mode walk buffer ($B_{\text{mode}}$):
* Bus/Terminal walk buffer: $B_{\text{bus}} = 640\text{ meters}$
* Rail/Metro walk buffer: $B_{\text{rail}} = 960\text{ meters}$

### 3.1 Walking Access Time ($WalkTime$)
For stop $i$ to transit access point $j$:
$$WalkTime_{i,j} = \frac{D_{proj}(i, j)}{80.0} \text{ (minutes)}$$
* $80.0$ meters/minute is the standard pedestrian walking speed ($4.8\text{ km/h}$).

### 3.2 Scheduled Wait Time ($SWT$)
For route $r$ at transit node $j$:
$$SWT_{j,r} = \left(0.5 \times Headway_{j,r}\right) + Margin_{mode}$$
* **Mode Margins ($Margin_{mode}$)**:
  - Bus: **2.0 minutes**
  - Metro: **0.75 minutes**
  - Suburban Rail: **1.50 minutes**
* **Headway ($Headway_{j,r}$)**:
  - Scheduled: Pulled from GTFS schedules. If GTFS schedule data is missing, the headway defaults to a route-count proxy:
    $$Headway_{fallback} = \begin{cases} 
        5.0\text{ min} & \text{if } \text{RouteCount} \ge 10 \\
        10.0\text{ min} & \text{if } 5 \le \text{RouteCount} < 10 \\
        15.0\text{ min} & \text{if } 2 \le \text{RouteCount} < 5 \\
        30.0\text{ min} & \text{if } \text{RouteCount} = 1 \\
        20.0\text{ min} & \text{for all Suburban nodes (timetables not public)}
    \end{cases}$$
  - GPS-Empirical: Replaced by the observed mean headway $\mu$ calculated from vehicle pings (from Section 2.2).

### 3.3 Total Access Time ($AT$)
$$AT_{j,r} = WalkTime_{i,j} + SWT_{j,r}$$

### 3.4 Equivalent Delivery Factor ($EDF$)
Represents the service contribution of route $r$ at stop $i$:
$$EDF_{j,r} = \frac{30.0}{AT_{j,r}}$$

### 3.5 Accessibility Index ($AI$)
For stop $i$, sort all accessible routes in ascending order of access time: $AT_1 \le AT_2 \le \dots \le AT_R$. The dominant route $AT_1$ (represented as $AT_{dom}$) is weighted fully, while all other $R-1$ routes are weighted at $50\%$:
$$AI_i = \left(\frac{30.0}{AT_{dom}}\right) + 0.5 \times \sum_{k=2}^{R} \left(\frac{30.0}{AT_k}\right)$$

---

## 4. Network Health Index (NHI) Scorecard

NHI is scored on a scale of 0 to 100.

### 4.1 Scheduled (Timetabled) NHI
$$NHI_{Sch} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.2 \times S_{resilience}$$

### 4.2 GPS-Empirical NHI
$$NHI_{GPS} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.1 \times S_{reliability} + 0.1 \times S_{speed}$$

### 4.3 Scorecard Component Derivations

#### A. Directness Score ($S_{directness}$)
Measures routing circuity to the closest reachable terminal/hub:
$$\text{Circuity}_i = \frac{\text{Route Distance}}{\text{Euclidean Distance}}$$
* **Route Distance**: Calculated from the precomputed GTFS sequences by subtracting the cumulative distances of the stop and the hub:
  $$\text{Route Distance} = |\text{CumulativeDist}_{\text{stop}} - \text{CumulativeDist}_{\text{hub}}|$$
* **Score Mapping**:
  $$S_{directness} = \max\left(0.0, \min\left(100.0, 100.0 \times (2.0 - \text{Circuity}_i)\right)\right)$$
* **Overriding Hops Constraints**:
  - If minimum transfer hops = 0 (direct route): $S_{directness} = 100.0$
  - If minimum transfer hops = 2 (3 routes): $S_{directness} = 50.0$
  - If minimum transfer hops $\ge 3$: $S_{directness} = 0.0$

#### B. Transfer Friction Score ($S_{transfer}$)
Penalizes routing transfer hops (calculated via a multimodal RAPTOR routing graph to the nearest terminal):
$$S_{transfer} = \begin{cases} 
    100.0 & \text{if } \text{hops} = 0 \text{ (Direct)} \\
    70.0 & \text{if } \text{hops} = 1 \text{ (1 transfer)} \\
    30.0 & \text{if } \text{hops} = 2 \text{ (2 transfers)} \\
    0.0 & \text{if } \text{hops} \ge 3 \text{ or disconnected}
\end{cases}$$

#### C. Multimodal Integration Score ($S_{multimodal}$)
Awards points if the stop is within a 200m walk buffer of a rail station (Metro or Suburban):
$$S_{multimodal} = \begin{cases} 
    100.0 & \text{if } \min\left(D_{proj}(i, \text{rail\_nodes})\right) \le 200.0\text{ meters} \\
    0.0 & \text{otherwise}
\end{cases}$$

#### D. Network Resilience Score ($S_{resilience}$ — Scheduled Only)
Evaluates route counts redundancy at stop $i$:
$$S_{resilience} = \begin{cases} 
    100.0 \times \left(1 - e^{-0.3 \times (\text{RoutesCount}_i - 1)}\right) & \text{if } \text{RoutesCount}_i > 1 \\
    0.0 & \text{if } \text{RoutesCount}_i \le 1
\end{cases}$$

#### E. Headway Reliability Score ($S_{reliability}$ — GPS-Empirical Only)
Derived from the Coefficient of Variation ($CV$) of observed arrivals (from Section 2.2):
$$S_{reliability} = \max\left(0.0, \min\left(100.0, 100.0 \times \frac{1.2 - CV}{1.0}\right)\right)$$
* *If $CV \le 0.2$ (highly regular): $S_{reliability} = 100.0$*
* *If $CV \ge 1.2$ (highly irregular/bunched): $S_{reliability} = 0.0$*

#### F. Travel Speed Score ($S_{speed}$ — GPS-Empirical Only)
Derived from the average observed travel speed ($V_{avg}$ in km/h) of buses near the stop (from Section 2.1):
$$S_{speed} = \max\left(0.0, \min\left(100.0, 100.0 \times \frac{V_{avg} - 6.0}{19.0}\right)\right)$$
* *If $V_{avg} \ge 25.0\text{ km/h}$ (free-flowing): $S_{speed} = 100.0$*
* *If $V_{avg} \le 6.0\text{ km/h}$ (severe congestion): $S_{speed} = 0.0$*

---

## 5. Performance Deltas (Variances)

Calculated at the bus stop level:

### 5.1 PTAL Index Variance ($\Delta PTAL$)
$$\Delta PTAL = AI_{GPS} - AI_{Sch}$$

### 5.2 Network Health Delta ($\Delta NHI$)
$$\Delta NHI = NHI_{GPS} - NHI_{Sch}$$

By substituting equations 4.1 and 4.2:
$$\Delta NHI = 0.1 \times \left(S_{reliability} + S_{speed}\right) - 0.2 \times S_{resilience}$$
