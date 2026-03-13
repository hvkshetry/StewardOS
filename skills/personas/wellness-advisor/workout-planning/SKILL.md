---
name: workout-planning
description: |
  Exercise and routine planning using wger. Use when: (1) Creating workout plans,
  (2) Logging workout sessions, (3) Tracking progressive overload, (4) Planning
  recovery, (5) Reviewing workout history and adherence.
---

# Workout Planning

Use `wger` for planned routines and explicitly logged sessions, direct Fitbod export data for recent strength detail when `wger` is empty or lagging, and direct Peloton data as the cardio source of truth.

## Tool Mapping (wger-mcp)

| Task | Key Tools |
|------|-----------|
| List workouts | View workout plans and templates |
| Log session | Record exercises with sets, reps, weight |
| View history | Past workout sessions and performance |
| Body measurements | Weight, body fat, measurements over time |
| Exercise database | Browse/search exercises by muscle group |

## Source Order

For workout-history and adherence questions:
- Pull `wger` first: `get_workout_sessions`, `get_workout_log`, `get_routines`
- If `wger` is empty or incomplete, use direct Fitbod export detail for weight training only:
  - `fitbod_parse_csv` for exercise rows, sets/reps/load, session timestamps, and last-lifting recency
  - `fitbod_preview_mapping` only when you need exercise-category confidence for muscle-group or progression claims
  - `fitbod_import_csv` with `dry_run=true` is allowed when you need a bounded date-range slice, coverage verification, or an unresolved-exercise queue without persisting anything
  - Treat Fitbod muscle-group rollups as reliable only when trailing-365d weighted mapping coverage is at least 90%
  - If coverage is below 90%, stay at exercise level and explicitly label category rollups as partial
  - Exclude Fitbod cardio rows when a matching Peloton workout exists with the same local start time and duration; treat them as synced duplicates
  - Prefer strength summaries with exercise-level detail such as `Pull Up 3 x 11` or `Kettlebell Swing American 3 x 5 @ 24.95 kg`
- Pull direct Peloton cardio/class detail with `peloton_get_workouts`
  - Use `peloton_get_workout_detail` for notable sessions, class metadata, instructor, estimated difficulty, and tracked metrics
  - Use `peloton_get_performance_graph` when interval structure or pacing distribution is material to the recommendation
  - Treat Peloton as the cardio source of truth for run/cardio volume and class detail
- Use Apple Health workout summaries only as fallback coverage for session count/minutes when direct workout sources are unavailable
- Do not persist a Fitbod import during normal planning/review flows unless the user explicitly wants an import or sync action

## Workout Planning Principles

### Progressive Overload

Track and ensure progression over time:
- **Weight progression**: Increase load when target reps are consistently met
- **Volume progression**: Add sets or reps before adding weight
- **Frequency progression**: Add training days when recovery allows

### Split Options

Common splits to recommend based on availability:
- **3 days/week**: Full body (Mon/Wed/Fri)
- **4 days/week**: Upper/Lower (Mon/Tue/Thu/Fri)
- **5 days/week**: Push/Pull/Legs + Upper/Lower
- **6 days/week**: PPL x2

### Recovery Awareness

Integrate with Oura readiness data:
- Readiness > 80: Full intensity workout
- Readiness 60-80: Moderate intensity, reduce volume by ~20%
- Readiness < 60: Light activity only (walk, yoga, mobility)
- 2+ consecutive days readiness < 70: recommend rest day

## Session Logging

When logging a workout:
1. Record each exercise: name, sets, reps, weight
2. Note any PRs (personal records)
3. Note RPE (rate of perceived exertion) if user provides
4. Track rest periods for time-sensitive programs

## Adherence Tracking

Weekly:
- Planned vs actual sessions (target adherence > 80%)
- Muscle groups trained vs planned, but only when Fitbod mapping coverage clears the 90% trailing-365d threshold or `wger` has direct categorization
- Any missed sessions — suggest catch-up or skip

Monthly:
- Volume progression (total sets per muscle group)
- Strength progression (weight on key lifts), preferring exercise-level trends over inferred category rollups when Fitbod mapping coverage is below threshold
- Body measurement changes (if tracked)
- Workout consistency rate
