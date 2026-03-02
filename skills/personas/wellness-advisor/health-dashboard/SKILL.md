---
name: health-dashboard
description: |
  Aggregate health data from Oura (sleep/readiness), Apple Health (activity/vitals),
  and wger (workouts/nutrition) into a unified health dashboard. Use for daily
  check-ins, weekly health reviews, or trend analysis across health domains.
---

# Health Dashboard

## Data Sources

| Domain | Server | Key Data |
|--------|--------|----------|
| Sleep & Recovery | oura | Sleep score, stages, HRV, readiness, temperature |
| Activity & Vitals | apple-health | Steps, active energy, heart rate, weight, blood pressure |
| Workouts | wger | Exercise logs, sets/reps/weight, workout frequency |
| Nutrition | wger | Calorie intake, macros (protein, carbs, fat) |
| Medical | health-records | Lab results, prescriptions, provider visits |

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

### Step 4: Workout Status (wger)

- Last workout: date, type, duration
- Days since last workout — flag if > 3 days
- This week's workout count vs target

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
- Flag anomalies: HRV drop > 15% from baseline, sleep score < 60, readiness < 60
- Recovery-first: recommend rest when readiness is low
- Not medical advice: flag concerning trends but recommend doctor consultation
