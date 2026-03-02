---
name: child-development
description: |
  Child education and development planning skill. Use when: (1) Creating age-appropriate
  activity plans, (2) Tracking developmental milestones, (3) Balancing activity types across
  cognitive/physical/creative/social domains, (4) Adapting plans based on progress and
  interests, (5) Writing journal entries for development tracking. Tools: family-edu-mcp
  for activity management, plans, milestones, and journaling.
---

# Child Education and Development Planning

## Tool Mapping

| Task | Tool | Notes |
|------|------|-------|
| List available activities | `get_activities` | Filter by age, domain, environment |
| Get activity details | `get_activity` | Full description, materials, duration, instructions |
| Create weekly plan | `create_weekly_plan` | Assign activities to days and time slots |
| View plan | `get_weekly_plan` | Retrieve plan for a given week |
| Track milestones | `get_milestones`, `update_milestone` | CDC-aligned developmental milestones |
| Log journal entry | `create_journal_entry` | Observations, progress notes, photos |
| Get child profile | `get_child_profile` | Age, preferences, current milestone status |

## Age-Appropriate Activity Selection

### Developmental Domains

Every weekly plan must include activities from all four domains:

| Domain | Examples | Goal |
|--------|----------|------|
| **Cognitive** | Puzzles, counting, sorting, pattern recognition, reading, memory games | Problem-solving, language, numeracy |
| **Physical** | Running, climbing, ball games, balance exercises, fine motor crafts | Gross and fine motor skills |
| **Creative** | Drawing, painting, music, pretend play, building, storytelling | Expression, imagination, innovation |
| **Social-Emotional** | Sharing games, role play, emotion identification, turn-taking | Empathy, cooperation, self-regulation |

### Age-Based Guidelines (CDC Milestones)

**6-12 months:**
- Sensory exploration (textures, sounds, safe objects)
- Tummy time, supported sitting, crawling encouragement
- Peek-a-boo, simple cause-and-effect toys
- Reading board books with high-contrast images

**1-2 years:**
- Stacking, nesting, simple shape sorters
- Walking practice, push/pull toys, climbing soft structures
- Scribbling with crayons, water play, sand play
- Parallel play with other children, simple instructions

**2-3 years:**
- Simple puzzles (4-8 pieces), color/shape naming, counting to 5
- Running, jumping, kicking balls, tricycle
- Finger painting, play-dough, simple cutting with safety scissors
- Pretend play (kitchen, doctor), taking turns, sharing

**3-4 years:**
- Letter recognition, rhyming, sorting by multiple attributes
- Hopping, balancing on one foot, catching a ball
- Drawing shapes, collage, building with blocks/Lego
- Cooperative games, storytelling, identifying emotions

**4-5 years:**
- Writing name, counting to 20, simple addition concepts
- Skipping, swimming basics, fine motor (buttoning, zipping)
- Cutting complex shapes, creating stories, musical instruments
- Group games with rules, conflict resolution practice

### Selection Procedure

1. Check the child's age and current milestone status via `get_child_profile` and `get_milestones`
2. Identify domains that need more focus (milestones not yet met or approaching)
3. Search activities filtered by age range and target domain
4. Prefer activities that cross multiple domains (e.g., "obstacle course" = physical + cognitive)
5. Include at least one activity the child has shown strong interest in (engagement anchor)

## Weekly Activity Plan Creation

### Structure

Plan 2-3 structured activities per day (15-45 min each depending on age). The rest of the day is unstructured play, rest, and routine.

### Daily Template

| Time Slot | Type | Duration | Notes |
|-----------|------|----------|-------|
| Morning (after breakfast) | Cognitive or Creative | 20-30 min | Highest focus time |
| Midday (after nap/rest) | Physical | 20-45 min | Energy release |
| Evening (before dinner) | Social-Emotional or Creative | 15-20 min | Wind-down compatible |

### Weekly Balance Rules

- Minimum 3 physical activities per week (ideally daily)
- Minimum 2 cognitive activities per week
- Minimum 2 creative activities per week
- Minimum 1 social-emotional focused activity per week
- At least 3 outdoor activities per week (weather permitting)
- No more than 2 screen-based activities per week (if any)
- Include 1 completely new activity per week for novelty

### Plan Presentation Format

| Day | Morning | Midday | Evening |
|-----|---------|--------|---------|
| Mon | Shape sorting game (Cognitive, 20 min) | Park — climbing and running (Physical, 30 min) | Story time with emotion discussion (Social, 15 min) |
| Tue | Finger painting (Creative, 25 min) | Ball kicking practice (Physical, 20 min) | Puzzle time (Cognitive, 15 min) |
| ... | ... | ... | ... |

Below the table, include:
- **Materials needed**: Consolidated list of materials to prepare for the week
- **Prep-ahead tasks**: Anything that needs setup before the activity day
- **Flexibility notes**: Which activities can be swapped if the child is not in the mood

## Progress Tracking and Milestone Monitoring

### Milestone Check-In Cadence

- **Monthly**: Review all milestones for the child's current age band
- **Weekly**: Note any milestone progress observed during activities
- **On achievement**: Update milestone status immediately via `update_milestone`

### Milestone Status Values

| Status | Meaning |
|--------|---------|
| Not Started | Age-appropriate milestone not yet attempted |
| Emerging | Child shows early signs but inconsistent |
| Developing | Child can do it with support/prompting |
| Achieved | Child does it independently and consistently |

### Progress Reporting

When asked about progress, present:
1. Current age band and expected milestones
2. Status of each milestone (table format)
3. Areas of strength (achieved ahead of schedule)
4. Areas to focus on (not started or emerging milestones that are age-expected)
5. Recommended activities targeting focus areas

## Balancing Activity Types

### Indoor vs Outdoor

- Target 50/50 split when weather permits
- Have indoor alternatives for every outdoor activity (rainy day swaps)
- Outdoor activities should leverage the environment (nature walks, sand/water play, garden exploration) not just relocate indoor activities outside

### Structured vs Free Play

- Structured activities (planned, guided): 2-3 per day max
- Free play (child-directed, unstructured): Should make up the majority of the day
- Avoid over-scheduling — leave buffer time between activities
- If a child is deeply engaged in free play, skip the next structured activity

### Energy Management

- High-energy activities followed by calm activities
- Physical activities before meals (appetite) or before rest time (wind-down)
- Cognitive activities when the child is most alert (usually morning)
- Avoid new or challenging activities when the child is tired or hungry

## Adapting Plans Based on Progress and Interests

### Interest Signals

Watch for and record:
- Activities the child asks to repeat
- Topics the child talks about spontaneously
- Materials the child gravitates toward during free play
- Activities where the child shows extended focus (beyond typical attention span)

### Adaptation Rules

1. **Strong interest**: Increase frequency and complexity in that domain
2. **Resistance or disinterest**: Reduce frequency, try different activities in the same domain, or approach through a preferred domain (e.g., if the child resists drawing but loves stories, try story illustration)
3. **Milestone achieved early**: Introduce the next age band's activities in that domain
4. **Milestone delayed**: Increase focused activities without pressure; consult pediatrician if significantly delayed across multiple domains

### Plan Revision Cadence

- Review and adjust the plan every Sunday for the coming week
- Mid-week check: swap out any activity that did not work well
- Monthly: broader review of domain balance and milestone progress

## Journal Entry Best Practices

### What to Record

Each journal entry should capture:
- **Date and activity**: What was done
- **Duration**: How long the child engaged (actual, not planned)
- **Engagement level**: High / Medium / Low
- **Observations**: What the child did, said, or demonstrated
- **Milestone connections**: Any milestone progress observed
- **Next steps**: What to try next based on this observation

### Example Entry Format

```
Date: 2026-02-25
Activity: Shape sorting game (cognitive)
Duration: 18 min (planned 20 min — lost interest near end)
Engagement: Medium-High
Observations: Successfully sorted circles and squares without help.
Struggled with triangles — kept trying to force them into square holes.
Asked "what's this one?" pointing at the hexagon shape for the first time.
Milestone: Shape recognition — Developing (circles and squares achieved, triangles emerging)
Next: Try a simpler 3-shape sorter focusing on triangle recognition. Also try drawing triangles during art time.
```

### Journal Frequency

- Aim for 3-5 entries per week (not every activity needs a detailed entry)
- Always journal when: a new milestone is observed, the child shows unusual interest or resistance, or trying a new activity for the first time

## Common Pitfalls

1. **Over-scheduling** — Children need unstructured time more than structured activities. If in doubt, do less.
2. **Forcing a domain** — If a child resists an activity, try a different approach to the same skill, not more of the same activity
3. **Comparing to other children** — Milestones have wide normal ranges. Track against the child's own trajectory, not peers.
4. **Neglecting free play** — Structured activities are a supplement to, not a replacement for, free play
5. **Screen time creep** — Educational apps count toward screen time limits. Prefer hands-on activities.
6. **Weather excuses** — Dress appropriately and go outside. Only skip outdoor time in genuinely unsafe conditions (extreme heat, storms).
