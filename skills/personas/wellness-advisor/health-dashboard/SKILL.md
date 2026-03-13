---
name: health-dashboard
description: |
  Aggregate health data from Oura (sleep/readiness), Apple Health (activity/vitals),
  wger/Fitbod (strength and nutrition), and Peloton (class/performance detail)
  into a unified health dashboard. Use for daily check-ins, weekly health reviews,
  or trend analysis across health domains.
---

# Health Dashboard

## Data Sources

| Domain | Server | Key Data |
|--------|--------|----------|
| Sleep & Recovery | oura | Sleep score, stages, HRV, readiness, temperature |
| Activity & Vitals | apple-health | Steps, active energy, heart rate, weight, blood pressure |
| Workouts | wger + Fitbod CSV + peloton | Exercise logs, sets/reps/weight, workout frequency, class metadata, interval structure |
| Nutrition | wger | Calorie intake, macros (protein, carbs, fat) |
| Genome & Clinical | health-graph | PGx recommendations, curated assertions, labs, coverage context |
| Drug Reference | medical | FDA drug info, PubMed literature, clinical guidelines, WHO stats |
| Document Provenance | paperless | Retrieval and verification of source documents only |

## Daily Health Check

### Step 1: Sleep (Oura)

Pull last night's data:
- Sleep score and contributors (total sleep, efficiency, latency, timing)
- Sleep stages: deep, REM, light, awake — duration and percentages
- HRV: overnight average, trend vs 14-day baseline
- Resting heart rate: value and trend
- Body temperature deviation

### Step 2: Readiness (Oura)

- Readiness score and contributors
- Recovery index
- Activity balance (not too much, not too little)
- Flag if readiness < 70 — recommend lighter activity day

### Step 3: Activity (Apple Health)

Query via SQL (DuckDB):
- Steps: today vs 7-day average
- Active energy burned
- Exercise minutes
- Stand hours (if tracked)
- Resting heart rate (if tracked by Apple Watch)

### Step 4: Workout Status (wger + Fitbod + Peloton)

- Pull `wger` first:
  - `get_workout_sessions`
  - `get_workout_log`
  - `get_routines`
- If `wger` is empty or stale, parse the latest Fitbod export for weight training only:
  - `fitbod_parse_csv` for last lifting date, exercise list, sets/reps/load, and recent strength volume
  - `fitbod_preview_mapping` or `fitbod_list_exercise_aliases` only when you need confidence for exercise mapping or muscle-group rollups
  - `fitbod_import_csv` with `dry_run=true` is allowed when you need a date-bounded workout slice, coverage verification, or an unresolved-exercise queue without writing to `wger`
  - Only treat muscle-group rollups as reliable when trailing-365d weighted mapping coverage is at least 90%
  - Never persist a Fitbod import during normal dashboard/check-in runs unless the user explicitly wants an import or repair workflow
  - Exclude Fitbod cardio rows from reporting when a matching Peloton workout exists with the same local start time and duration; treat those rows as synced duplicates
  - Prefer session-level lifting detail like `Pull Up 3 x 11` or `Dumbbell Bicep Curl 3 x 8 @ 13.6 kg`
- If recent Peloton workouts exist:
  - `peloton_get_workouts`
  - `peloton_get_workout_detail` for the latest or most notable session to capture class title, instructor, duration, difficulty, tracked metrics, and muscle emphasis
  - `peloton_get_performance_graph` when interval structure, pace targets, or compliance adds signal
  - Treat Peloton as the cardio source of truth
- Use Apple Health workout summaries as fallback coverage when direct sources are unavailable
- Report:
  - Last workout: date, type, duration
  - Days since last workout — flag if > 3 days
  - This week's workout count vs target
  - Notable direct-source workout detail when it changes the interpretation

### Step 5: Nutrition (wger)

- Yesterday's intake: total calories, protein, carbs, fat
- Protein target check: aim for 1g per lb bodyweight (or user's target)

## Weekly Health Review

Aggregate 7 days of data:

```
## Weekly Health Review — [Date Range]

### Sleep
- Avg score: X/100 | Avg duration: Xh Xm
- Avg HRV: X ms (trend: ↑/↓/→)
- Best night: [date] | Worst: [date]
- Consistency: bedtime variation ± X min

### Activity
- Avg daily steps: X (target: Y)
- Total active energy: X kcal
- Exercise days: X/7

### Workouts
- Sessions completed: X
- Muscle groups covered: [list]
- Progressive overload: [any PRs or weight increases]
- Peloton highlights: [class mix, instructor, difficulty, interval structure]

### Nutrition
- Avg daily calories: X
- Avg protein: Xg (target: Yg)
- Avg macro split: P%/C%/F%

### Recovery
- Avg readiness: X/100
- Rest days taken: X
- HRV trend: [improving/declining/stable]

### Recommendations
1. [Specific, actionable recommendation based on data]
2. ...
```

## Trend Analysis

For longer-term analysis (30d, 90d):
- Sleep quality trend (are scores improving?)
- HRV baseline trend (proxy for fitness/recovery)
- Weight trend (if tracked)
- Workout frequency and volume progression
- Correlation: sleep quality vs next-day readiness vs workout performance

## Guidelines

- All metrics from MCP tool calls — never estimate or fabricate
- Prefer direct Fitbod CSV for strength detail and Peloton MCP for cardio detail; use Apple Health workout summaries as fallback coverage
- If Fitbod mapping coverage is below 90% weighted coverage on the trailing 365-day window, report exercise-level detail and explicitly mark muscle-group rollups as partial
- Avoid persisting `fitbod_import_csv` during standard dashboard/review flows unless the task is explicitly an import or sync workflow
- `health-graph` is authoritative for genome/clinical availability and recommendation context
- If genome-informed guidance is included in a dashboard or weekly summary, make it answer "so what?" directly:
  - Lead with the plain-English takeaway for the subject
  - State whether anything needs to happen now; if not, say that explicitly
  - State what future decision this could affect, if any
  - Avoid unexplained jargon such as metabolizer labels, star alleles, or rsids unless translated immediately
  - For Tier 3 and Tier 4 items, state clearly that they are watchlist or research context and should not drive treatment or behavior changes on their own
- `paperless` is document-only in this workflow; do not use it as a proxy for genomic data availability
- Flag anomalies: HRV drop > 15% from baseline, sleep score < 60, readiness < 60
- Recovery-first: recommend rest when readiness is low
- When reviewing medications or supplements, use `medical.search_drugs` for drug interaction context and `medical.get_drug_details` for dosing reference
- Not medical advice: flag concerning trends but recommend doctor consultation
