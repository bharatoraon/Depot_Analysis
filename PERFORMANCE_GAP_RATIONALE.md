# Detailed Rationale: PTAL Index Variance & Network Health Delta

This document explains the conceptual genesis, mathematical derivations, and planning logic behind the **PTAL Index Variance** ($\Delta PTAL$) and **Network Health Delta** ($\Delta NHI$) metrics used in the Chennai Multimodal Transit Performance Gap Dashboard (`compare.html`).

---

## 1. The Core Problem: The Plan vs. The Reality

Traditional transit GIS modeling relies on static schedules (GTFS) or spatial route layout maps. While these datasets are invaluable for modeling the *structural* capacity of a city's network, they describe a "perfect world" planned by transit authorities. In reality, actual commuter experiences are governed by:
* Traffic congestion and bottlenecks.
* Operational irregularities (e.g., bus bunching).
* Vehicle breakdowns, driver shortages, and schedule deviations.

If a planner evaluates a city's transit network using schedule data alone, they may conclude that an area has excellent accessibility (e.g., high PTAL grade) because many routes are scheduled to stop there. However, if the buses serving those routes are constantly delayed or bunched together, the actual accessibility experienced by the commuter is far worse.

To expose this gap, we developed the **Performance Gap Analysis** framework. Instead of looking at GTFS schedules or GPS telemetry in isolation, we calculate the mathematical difference (delta/variance) between them at the individual bus stop level:
$$\text{Performance Gap} = \text{Observed Operations (GPS)} - \text{Timetabled Schedule (GTFS)}$$

---

## 2. PTAL Index Variance ($\Delta PTAL$)

### 2.1 The Derivation
Public Transport Accessibility Level (PTAL) measures door-to-door transit accessibility at a stop by calculating the total Access Time ($AT$) to all reachable routes:
$$AT_{j,r} = WalkTime_{j} + SWT_{j,r}$$

Where:
* $WalkTime_{j}$ is the static walking time from the origin stop to the entry point of route $r$.
* $SWT_{j,r}$ is the Scheduled Wait Time for route $r$.

The key differentiator between the Scheduled PTAL and the GPS-Empirical PTAL lies in how the wait time is calculated:

#### A. Scheduled wait time ($SWT_{Sch}$):
Uses timetabled headways ($Headway_{Sch}$) from GTFS frequencies:
$$SWT_{Sch} = \left(0.5 \times Headway_{Sch}\right) + ReliabilityMargin_{mode}$$

#### B. GPS-Empirical wait time ($SWT_{GPS}$):
Uses observed headways ($Headway_{GPS}$) reconstructed from actual vehicle arrivals in the raw GPS logs:
$$SWT_{GPS} = \left(0.5 \times Headway_{GPS}\right) + ReliabilityMargin_{mode}$$

### 2.2 Mathematical Propagation of the Gap
When the average observed headway ($Headway_{GPS}$) is greater than the scheduled headway ($Headway_{Sch}$), it indicates service delays or missing trips:
$$Headway_{GPS} > Headway_{Sch} \implies SWT_{GPS} > SWT_{Sch}$$
$$SWT_{GPS} > SWT_{Sch} \implies AT_{GPS} > AT_{Sch}$$

Because accessibility is inversely proportional to access time, the Accessibility Index ($AI$) decreases as access time increases:
$$AI = \frac{30}{AT_{dom}} + 0.5 \times \sum \left(\frac{30}{AT_{non-dom}}\right)$$
$$AT_{GPS} > AT_{Sch} \implies AI_{GPS} < AI_{Sch}$$

The **PTAL Index Variance** ($\Delta PTAL$) is defined as:
$$\Delta PTAL = AI_{GPS} - AI_{Sch}$$

### 2.3 Planning Interpretation
* $\Delta PTAL < -0.5$ (🔴 **Red / Negative Variance**):
  Commuters are experiencing an "Accessibility Deficit". Observed headways are longer than scheduled, meaning buses are delayed, trips are cancelled, or services are irregular.
* $-0.5 \le \Delta PTAL \le 0.5$ (⚪ **Gray / On Schedule**):
  Actual operations align closely with the schedule.
* $\Delta PTAL > 0.5$ (🟢 **Green / Positive Variance**):
  The observed accessibility is higher than scheduled. This occurs when headway regularity is high, or when extra unscheduled buses are running, decreasing wait times.

---

## 3. Network Health Delta ($\Delta NHI$)

### 3.1 The Concept: Structural vs. Operational Health
The Network Health Index (NHI) evaluates the overall quality of transit options at a stop on a 0-100 scale.
* **Timetabled NHI ($NHI_{Sch}$)** measures the *structural potential* of the stop based on network design:
  $$NHI_{Sch} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.2 \times S_{resilience}$$
  Here, $S_{resilience}$ (20%) is a static score based on route counts ($RoutesCount_i$). It assumes that having more routes makes the stop resilient to disruptions.

* **GPS-Empirical NHI ($NHI_{GPS}$)** evaluates the *actual operational health* of the stop. In the real world, route count is a poor indicator of resilience if all those routes are stuck in traffic or bunched together. Therefore, we replaced the static $S_{resilience}$ score with two dynamic operational sub-scores, each weighted at 10%:
  $$NHI_{GPS} = 0.3 \times S_{directness} + 0.3 \times S_{transfer} + 0.2 \times S_{multimodal} + 0.1 \times S_{reliability} + 0.1 \times S_{speed}$$

### 3.2 The Operational Sub-Scores
1. **Headway Reliability ($S_{reliability}$ — 10%)**:
   Measures service regularity using the Coefficient of Variation ($CV = \sigma / \mu$) of stop headways. High $CV$ indicates **bus bunching** (multiple buses of the same route arriving together, followed by a long gap):
   * If $CV \le 0.2$ (perfectly regular): $S_{reliability} = 100$
   * If $CV \ge 1.2$ (highly irregular / bunched): $S_{reliability} = 0$
   * Scale: $S_{reliability} = \max\left(0, \min\left(100, 100 \times \frac{1.2 - CV}{1.0}\right)\right)$

2. **Travel Speed ($S_{speed}$ — 10%)**:
   Scores the stop based on average observed travel speeds ($V_{avg}$ in km/h) of buses near the stop, penalizing congestion:
   * If speed $\ge 25\text{ km/h}$ (free-flowing): $S_{speed} = 100$
   * If speed $\le 6\text{ km/h}$ (bumper-to-bumper congestion): $S_{speed} = 0$
   * Scale: $S_{speed} = \max\left(0, \min\left(100, 100 \times \frac{V_{avg} - 6.0}{19.0}\right)\right)$

### 3.3 The Delta Calculation
The **Network Health Delta** ($\Delta NHI$) is defined as:
$$\Delta NHI = NHI_{GPS} - NHI_{Sch}$$

By substituting the equations:
$$\Delta NHI = 0.1 \times \left(S_{reliability} + S_{speed}\right) - 0.2 \times S_{resilience}$$

### 3.4 Planning Interpretation
This delta represents the **Operational Health Deficit** or **Gain**:
* **Negative Delta ($\Delta NHI < -5\%$)**:
  The stop's operational quality is severely degraded compared to its theoretical potential. This indicates that despite having a high route count (high $S_{resilience}$), the stop suffers from low travel speeds (congestion) and irregular service (bus bunching).
* **Positive Delta ($\Delta NHI > 5\%$)**:
  The stop performs better operationally than its structural layout suggests. This happens at stops with low route counts (where $S_{resilience}$ is low) but where the serving routes run with high speed and high headway reliability.

---

## 4. Policy & Engineering Interventions

The resulting diverging delta maps allow transit planners to target specific interventions based on the type of gap detected:

| Variance Diagnostic | Primary Cause | Recommended Action |
| :--- | :--- | :--- |
| **High $\Delta PTAL$ Deficit (Red)** | Cancelling scheduled trips; long gaps between buses. | • Penalty/incentive adjustments for private transit operators.<br/>• Adjust timetables to match available fleet size. |
| **Low Speeds ($S_{speed}$) + Low NHI Delta** | Street congestion; buses stuck in general traffic. | • Designate dedicated **Bus Priority Lanes**.<br/>• Implement Signal Priority for transit vehicles at intersections. |
| **High $CV$ ($S_{reliability}$ Deficit) + Low NHI Delta** | Bus bunching; lack of route headway control. | • Introduce headway control strategies (e.g., holding buses at terminals/control points).<br/>• Optimize dispatch intervals. |
| **Timetable Alignment (Gray / No Variance)** | Operations match timetable. | • Keep baseline. Timetable is well-calibrated. |
