---
name: weekly-health
description: Weekly health review — sleep trends, workout adherence, nutrition averages, and recovery analysis.
user-invocable: true
---

# /weekly-health — Weekly Health Review

Comprehensive 7-day health review aggregating data from all health sources.

## Steps

### 1. Sleep Trends (Oura — 7 days)

- Average sleep score, duration, efficiency
- HRV trend (improving, declining, stable)
- Resting HR trend
- Best and worst nights
- Bedtime consistency (std deviation of bedtime)

### 2. Activity Summary (Apple Health — 7 days)

SQL query for the past 7 days:
- Average daily steps vs target
- Total active energy burned
- Exercise minutes per day
- Days meeting activity goals

### 3. Workout Adherence (wger — 7 days)

- Sessions completed vs planned
- Muscle groups covered
- Any progressive overload achievements (PRs, weight increases)
- Days since last workout

### 4. Nutrition Summary (wger — 7 days)

- Average daily calories
- Average protein intake vs target
- Average macro split (P/C/F)
- Consistency (day-to-day variance)

### 5. Recovery Analysis

- Average readiness score
- Number of low-readiness days (< 70)
- Rest days taken
- Correlation: sleep quality → next-day readiness → workout performance

### 6. Anomaly Detection

Flag any of:
- HRV drop > 15% from 14-day baseline
- Sleep score < 60 for 2+ consecutive nights
- Readiness < 60 for 2+ consecutive days
- Missed workouts 3+ consecutive days
- Protein consistently below target (< 80% for 5+ days)

### 7. Output

```
## Weekly Health Review — [Date Range]

### Sleep
- Avg Score: X/100 | Avg Duration: Xh Xm
- HRV Trend: [↑/↓/→] (avg: X ms)
- Best: [date] (score X) | Worst: [date] (score X)

### Activity
- Avg Steps: X/day (target: Y)
- Exercise Days: X/7
- Total Active Energy: X kcal

### Workouts
- Sessions: X completed (Y planned)
- Highlights: [PRs, milestones]

### Nutrition
- Avg Calories: X | Protein: Xg (target: Yg)
- Macro Split: P% / C% / F%

### Recovery
- Avg Readiness: X/100
- Low Days: X | Rest Days: X

### Alerts
- [Any anomalies flagged]

### Recommendations
1. [Specific, data-driven recommendation]
2. [...]
```
