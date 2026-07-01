# Rationale and Standards: Transit Performance Gap Variance Thresholds

This document explains the scientific rationale, operational transit standards, and cartographic design principles behind the classification thresholds used in the Chennai Multimodal Transit Performance Gap Dashboard (`compare.html`):

* **$\ge +10\%$**: Much Better (Significant operational gain)
* **$+3\%$ to $+10\%$**: Better (Minor operational gain)
* **$-3\%$ to $+3\%$**: No Variance / On Schedule (Normal operational noise)
* **$-10\%$ to $-3\%$**: Worse (Minor operational delay/bunching)
* **$\le -10\%$**: Much Worse (Significant bottleneck / severe bunching)

---

## 1. The $\pm 3\%$ "Indifference Zone" (Operational Noise Filter)

In raw GPS tracking and schedule modeling, attempting to map absolute variance down to $0.0\%$ results in cartographic noise. If a bus is scheduled for a 15-minute headway and arrives 25 seconds late, this represents a $2.8\%$ operational delay. Under a strict $0\%$ threshold, this stop would be colored red (Worse), which is misleading.

We established the **$\pm 3\%$ threshold** as an **indifference zone** (represented as **Gray / On Schedule**) based on the following standards:

### 1.1 GPS Ping Latency & Clock Drifts
Raw GPS telemetry has inherent temporal errors (pings sent every 30–60 seconds, satellite signal drifts). A $\pm 3\%$ margin acts as a mathematical filter for telemetry sync errors. For example:
* On a 10-minute headway (600 seconds), a $3\%$ margin represents **18 seconds**.
* On a 20-minute headway (1200 seconds), it represents **36 seconds**.
Any deviation within this window is statistically indistinguishable from tracking noise.

### 1.2 Transit Quality of Service Standards (TCQSM)
According to the **Transit Capacity and Quality of Service Manual (TCQSM, 3rd Edition)** published by the Transportation Research Board (TRB):
* Transit vehicles are generally considered "on-time" if they arrive within a window of **1 minute early to 5 minutes late** relative to the timetable.
* For high-frequency headway-based services, a minor headway variation (Coefficient of Variation $CV \le 0.2$) represents Level of Service (LOS) A.
A $\pm 3\%$ difference in the Network Health Index (NHI) indicates that actual operations remain within this high-performing, stable band.

---

## 2. The $\pm 10\%$ "Significant Deviation" Threshold (Intervention Trigger)

In transit management, a **10% deviation** is the standard benchmark for defining a **significant change in service levels** or triggering agency intervention.

### 2.1 Federal Transit Administration (FTA) Standards
The FTA and major metropolitan transit authorities (such as Transport for London and the MTA) use $10\%$ service level variance as an evaluation benchmark:
* **Running Time Deviation**: If a route's travel time deviates by more than $10\%$ from the scheduled timetable, it triggers a schedule recalibration.
* **On-Time Performance (OTP) Triggers**: Operational penalties or service improvement plans are typically enforced on private operators when OTP drops by $10\%$ or more below targets.

### 2.2 Mathematical Calibration in the NHI Scorecard
In the GPS-Empirical Network Health Index ($NHI_{GPS}$), travel speed ($S_{speed}$) and headway reliability ($S_{reliability}$) sub-scores are weighted at $10\%$ each.
* A complete drop in one of these sub-scores (e.g., speed dropping from free-flow to severe bumper-to-bumper congestion, or headway reliability dropping from perfect intervals to severe bus bunching) reduces the overall NHI by exactly **10 points (10%)**.
* Therefore, a $\Delta NHI \le -10\%$ indicates that the stop has suffered a **catastrophic operational failure** in either speed (congestion) or reliability (bunching), requiring immediate physical intervention (e.g., Bus Priority Lanes).

---

## 3. Cartographic Classifications for Diverging Maps

For variance maps (gap analysis), standard GIS classification methods (like Natural Breaks or Equal Intervals) fail because they are not symmetric around the zero-point. Cartographic best practices dictate:
1. **Symmetric Diverging Classification**: The categories must mirror each other on both sides of the neutral baseline to accurately represent gains vs. losses.
2. **Isolating the Tails**: The extreme ends of the scale ($\ge 10\%$ and $\le -10\%$) are isolated using deep colors (Deep Green and Deep Red) to draw the planner's eye immediately to the most severe bottlenecks and the most significant operational gains.

---

## 4. PTAL Access Index Scaling (Index Deltas)

For the **PTAL Access Index**, which is an absolute score (typically ranging from 0 to 60+), the threshold bins are scaled proportionally to standard London PTAL grading widths:
* **$\Delta AI \ge 5.0$**: Much Better (Corresponds to jumping a full PTAL grade level, e.g., Grade 3 to Grade 4).
* **$1.5 \le \Delta AI < 5.0$**: Better (Minor access improvement, equivalent to a sub-grade change).
* **$-1.5 < \Delta AI < 1.5$**: On Schedule (Stable accessibility, no grade changes).
* **$-5.0 < \Delta AI \le -1.5$**: Worse (Minor delay, risk of dropping a sub-grade).
* **$\Delta AI \le -5.0$**: Much Worse (Severe accessibility loss, drops a full PTAL grade).

These thresholds align the dashboard's visual mapping directly with the operational decisions transit planners make every day.
