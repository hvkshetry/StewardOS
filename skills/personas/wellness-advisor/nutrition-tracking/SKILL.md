---
name: nutrition-tracking
description: |
  Nutrition intake tracking and analysis via wger. Use when: (1) Logging meals and
  macros, (2) Reviewing daily/weekly nutrition, (3) Checking protein targets,
  (4) Correlating nutrition with workout performance and recovery.
---

# Nutrition Tracking

## Tool Mapping (wger-mcp)

| Task | Approach |
|------|----------|
| Log meal/food | Add nutrition diary entries with calories and macros |
| Daily summary | Sum day's intake: calories, protein, carbs, fat |
| Weekly summary | Average daily intake over 7 days |
| Nutrition plans | View/create nutrition plans with targets |

## Daily Targets

Default targets (adjust per user preference):
- **Calories**: Based on TDEE (activity level × BMR)
- **Protein**: 0.8-1g per lb bodyweight (prioritize this)
- **Fat**: 25-35% of calories
- **Carbs**: Remainder after protein and fat

## Logging Workflow

When user reports meals:
1. Estimate or look up macros per food item
2. Log to wger with: food name, quantity, calories, protein, carbs, fat
3. Show running daily total vs targets
4. Flag if protein is tracking below target by end of day

## Analysis

### Daily Review
- Total calories vs target (± 10% is on-track)
- Protein intake vs target (hit this first)
- Macro split pie: protein %, carbs %, fat %
- Meal timing: any long gaps (> 5 hours) between meals

### Weekly Patterns
- Average daily calories and consistency (low variance = good)
- Average protein: consistently hitting target?
- Weekday vs weekend patterns (common to overeat weekends)
- Correlation with workout days (higher intake on training days is expected)

### Nutrition-Performance Correlation
- Compare high-protein days with next-day workout performance
- Compare sleep quality (Oura) with evening meal timing
- Compare calorie deficit days with next-day readiness score

## Guidelines

- Protein is the priority macro — always track and flag if below target
- Don't obsess over daily calories — weekly averages matter more
- Log consistently rather than perfectly — rough estimates beat no data
- Flag sustained calorie deficit + high training volume (overtraining risk)
