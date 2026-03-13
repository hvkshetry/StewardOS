---
name: weekly-health
description: Weekly health review — sleep trends, workout adherence across wger/Fitbod/Peloton, nutrition averages, and recovery analysis.
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

### 3. Workout Adherence (wger + direct Fitbod/Peloton — 7 days)

- Pull `wger` first:
  - `get_workout_sessions`
  - `get_workout_log`
  - `get_routines`
- If `wger` is empty or incomplete, use direct Fitbod detail from the latest export for weight training only:
  - `fitbod_parse_csv` for strength-session count, last lifting date, exercise list, sets/reps/load, and deduped strength rows
  - `fitbod_preview_mapping` or `fitbod_list_exercise_aliases` only when you need exercise-to-category confidence for muscle-group or progression claims
  - `fitbod_import_csv` with `dry_run=true` is allowed when you need date-bounded weekly rows, coverage verification, or an unresolved-exercise queue without persisting anything
  - Only treat muscle-group rollups as reliable when trailing-365d weighted mapping coverage is at least 90%
  - If coverage is below 90%, report exercise-level detail and explicitly label muscle-group rollups as partial
  - Never persist a Fitbod import during a weekly review unless the user explicitly wants an import or repair workflow
  - Exclude Fitbod cardio rows from reporting when a matching Peloton workout exists with the same local start time and duration; treat those rows as synced duplicates
  - Prefer exercise-level lifting detail in the review, for example `Dumbbell Squat 3 x 4 @ 20.4 kg`, instead of collapsing everything into category rollups
- Pull direct Peloton workouts for the same window:
  - `peloton_get_workouts`
  - `peloton_get_workout_detail` for the most recent or most notable sessions
  - `peloton_get_performance_graph` when interval structure, target pace/compliance, or muscle emphasis adds value
- Treat Peloton as the cardio source of truth for run/cardio class count, duration, instructor, difficulty, and interval structure
- Use Apple Health workout summaries as a coverage check or fallback, not as the authoritative detail source when direct Fitbod/Peloton data is available
- Report:
  - Sessions completed vs planned
  - Muscle groups covered, but only if Fitbod mapping coverage clears the 90% threshold; otherwise call out the top unmapped exercises instead
  - Any progressive overload achievements (PRs, weight increases)
  - Peloton class mix, instructor/class highlights, difficulty, or interval structure when relevant
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

### 7. Genome & Clinical Context (health-graph)

- Pull genome-aware context from `health-graph` tools (not Paperless search):
  - `get_wellness_recommendations`
  - `get_pgx_profile` and/or `list_pgx_recommendations`
  - `get_polygenic_context` (context-only, not deterministic guidance)
  - `query_labs` / `get_lab_trends` for recent objective markers (if available)
- Summarize by evidence tier:
  - Tier 1 actionable-with-guardrails
  - Tier 2 review-required
  - Tier 3 context-only
  - Tier 4 research-only
- For Tier 1 through Tier 4 items, include recommendation-level detail (not counts-only):
  - Gene + drug (or variant + trait)
  - Subject-specific grounding (genotype/phenotype/metadata, if available)
  - Practical implication in plain language
  - Trigger condition ("if this medication/procedure is being considered")
  - Action framing by tier:
    - Tier 1: guardrailed clinical action
    - Tier 2: clinical review required before action
    - Tier 3: context-only, non-deterministic
    - Tier 4: research-only hypothesis
- The narrative must answer "so what?" directly for the subject:
  - Lead with the plain-English takeaway before mechanism, genotype labels, or tier language
  - State whether anything needs to happen now; if not, say that explicitly
  - State what decision this could change later, if any
  - Avoid unexplained jargon such as metabolizer labels, star alleles, or rsids unless immediately translated into plain language
  - For Tier 3 and Tier 4 items, say explicitly that they are watchlist or research context and should not drive treatment or behavior changes on their own
- De-duplicate overlapping PGx records by gene+drug and prefer highest-confidence wording.
- If `health-graph` is unavailable, mark genome context as unavailable due to source outage.
- Never infer genome-data absence from Paperless document search counts.

### 8. Output

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
- Highlights: [PRs, milestones, notable Peloton class/instructor/difficulty]

### Nutrition
- Avg Calories: X | Protein: Xg (target: Yg)
- Macro Split: P% / C% / F%

### Recovery
- Avg Readiness: X/100
- Low Days: X | Rest Days: X

### Genome & Clinical Context (health-graph)
- Tier 1 (actionable-with-guardrails): X items
- Tier 2 (review-required): X items
- Tier 3/4 (context/research): X items
- Recent labs available: [yes/no]
- Key Tier 1/2 Recommendation Details:
  - [Gene] + [Drug]: [plain-language implication]
    - So what for you: [direct answer in plain English]
    - Why this applies: [subject genotype/phenotype or metadata]
    - When it matters: [trigger condition]
    - Do anything now?: [yes/no, with brief reason]
    - Suggested next step: [guardrailed action]
- Key Tier 3/4 Context Details:
  - [Variant/Gene] + [Trait/Domain]: [plain-language implication]
    - So what for you: [watchlist-only or research-only takeaway]
    - Why this applies: [subject metadata]
    - Confidence caveat: [context-only or research-only]
    - Do anything now?: [usually no, unless paired with stronger clinical evidence]
    - Suggested use: [self-experiment context or watchlist; not deterministic guidance]

### Alerts
- [Any anomalies flagged]

### Recommendations
1. [Specific, data-driven recommendation]
2. [...]
```
