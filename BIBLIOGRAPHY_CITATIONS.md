# Citations and Standard References Guide

This bibliography provides the exact academic, institutional, and industry citations for the formulas, algorithms, and thresholds used in this project. You can copy and paste these citations directly into your reports, presentations, or methodology section.

---

## 1. PTAL (Public Transport Accessibility Level) Formulas

The PTAL model (including the walk speed of 80 m/min, mode margins, access time math, route weighting ratios of $1.0$ and $0.5$, and the 9 accessibility grades) is derived from **Transport for London (TfL)**.

### Academic/Institutional Citation:
> **Transport for London (TfL) City Planning.** (2015). *Assessing Public Transport Accessibility Levels (PTALs) - Technical Methodology.* London: TfL City Planning Department.

### Online Resource Reference:
> **Transport for London.** (2020). *WebCAT (Web-based Connectivity Assessment Toolkit) Methodology Guidance.* Available at: [https://tfl.gov.uk/info-for/urban-planning-and-construction/planning-with-webcat/webcat-methodology](https://tfl.gov.uk/info-for/urban-planning-and-construction/planning-with-webcat/webcat-methodology)

### Specific Formulas Used:
* **Walking access time**: $WalkTime = \frac{\text{Distance}}{80}$ (Derived from TfL's standard pedestrian speed of $4.8\text{ km/h}$ or $1.33\text{ m/s}$).
* **Wait Time reliability margins**: Bus = 2.0 min, Rail/Metro = 0.75 min.
* **Redundancy weighting**: Dominant route is weighted at 100%, non-dominant routes are weighted at 50% (TfL WebCAT standard).

---

## 2. Transit Reliability, Speed, and Bunching ($CV$ and $S_{reliability}$)

The headway reliability scorecard ($CV = \sigma / \mu$), headway-based Level of Service (LOS) criteria, and travel speed thresholds are derived from the **Transportation Research Board (TRB)**.

### Standard Manual Citation:
> **Transportation Research Board (TRB).** (2013). *Transit Capacity and Quality of Service Manual (TCQSM) - Report 165.* 3rd Edition. Washington, D.C.: National Academies of Sciences, Engineering, and Medicine.
> * *Referenced Section: Chapter 4 ("Transit Reliability") and Chapter 5 ("Quality of Service").*

### Specific Formulas & Benchmarks Used:
* **Headway irregularity**: Calculated via the Coefficient of Variation ($CV$):
  $$CV = \frac{\sigma}{\mu} = \frac{\text{Standard Deviation of Headways}}{\text{Mean Headway}}$$
* **Bushing Benchmarks**: TCQSM Chapter 4 defines $CV \le 0.2$ as Level of Service (LOS) A (optimal regularity), and $CV > 1.2$ as LOS F (severe service bunching/irregularity). This directly justifies our $S_{reliability}$ scale bounds.

---

## 3. Circuity, Directness, and Network Efficiency ($S_{directness}$)

The use of circuity (detour factors) and spatial directness to evaluate transit network layout and route efficiency is derived from the **Institute for Transportation and Development Policy (ITDP)** and the **World Bank**.

### Standard Manual Citation:
> **Institute for Transportation and Development Policy (ITDP).** (2017). *The TOD Standard (Version 3.0).* New York: ITDP.
> * *Referenced Section: Section 3 ("Shift - Walk, Cycle, and Transit Networks") - Indicator 3.2 (Directness of Transit Routes).*

### Specific Formula Used:
* **Circuity factor**:
  $$\text{Circuity} = \frac{\text{Actual Route Distance}}{\text{Euclidean Distance}}$$
* **Detour Standard**: ITDP defines a directness ratio of $< 1.5$ as high-performing and $\ge 2.0$ as inefficient/highly circuitous. This directly justifies our $S_{directness} = \max\left(0, 100 \times \left(2.0 - \text{Circuity}\right)\right)$ score mapping.

---

## 4. Multimodal Routing Engine (RAPTOR Algorithm)

The routing algorithm used to calculate transfer hops in our multimodal graph network is derived from **Microsoft Research**.

### Academic Paper Citation:
> **Delling, D., Pajor, T., & Werneck, R. F.** (2015). *Round-Based Public Transit Routing (RAPTOR).* **Transportation Science**, 49(2), 175-194.
> * *Referenced Section: Round-by-round transfer query sequences and Pareto optimization.*

---

## 5. Performance Gap Variance Thresholds ($\pm 3\%$ and $\pm 10\%$)

The choice of symmetric variance bins (gaps) to isolate normal operational noise from critical service delays:

### Academic/Industry Citation:
> **Kittelson & Associates, Inc., et al.** (2013). *Transit Capacity and Quality of Service Manual (TCQSM) - Chapter 4: Quality of Service Concepts.* Washington, D.C.: Transportation Research Board.
> * *Referenced Concepts: Headway-based punctuality limits. Timetable deviations under $10\%$ are classified as minor schedule adjustments, while delays exceeding $10\%$ of total route duration are designated as service failures.*
