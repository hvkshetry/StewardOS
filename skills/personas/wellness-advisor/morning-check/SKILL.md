---
name: morning-check
description: Morning health check — last night's sleep quality, readiness score, and recovery recommendations.
user-invocable: true
---

# /morning-check — Morning Health Check

Quick morning check-in with sleep and readiness data to set the day's activity level.

## Steps

### 1. Sleep Summary (Oura)

Pull last night's sleep data:
- Sleep score (0-100)
- Total sleep time and time in bed
- Sleep stages: deep, REM, light, awake (duration and %)
- Sleep latency (time to fall asleep)
- Sleep efficiency (time asleep / time in bed)

### 2. Readiness (Oura)

- Readiness score (0-100)
- Key contributors: HRV balance, recovery index, resting HR, temperature
- Comparison to 14-day baseline

### 3. Activity Context (Apple Health)

- Yesterday's steps and active energy
- Yesterday's exercise minutes
- Was yesterday a workout day? (wger)

### 4. Recovery Recommendation

Based on readiness score:
- **Readiness > 80**: Full intensity day — good for challenging workouts
- **Readiness 60-80**: Moderate day — lighter workout, watch energy levels
- **Readiness < 60**: Recovery day — light activity only (walk, stretch, yoga)

### 5. Output

```
## Morning Check — [Date]

### Sleep
- Score: X/100
- Duration: Xh Xm | Efficiency: X%
- Deep: Xh Xm | REM: Xh Xm
- HRV: X ms (baseline: Y ms)

### Readiness
- Score: X/100
- RHR: X bpm (baseline: Y)
- Temperature: +/- X°C

### Yesterday
- Steps: X | Active Energy: X kcal
- Workout: [Yes/No — details]

### Today's Recommendation
[Recovery / Moderate / Full intensity]
[Specific suggestion based on data]
```
