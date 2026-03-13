"""Seed learner-records catalogs (milestones + age activities).

Usage:
    DATABASE_URL=postgresql://family_edu:...@localhost:5434/family_edu \
    python seed_data.py [learner_id]
"""

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://family_edu:changeme@localhost:5434/family_edu"
)
SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

MILESTONES = [
    ("motor", "Raises head and chest when lying on stomach", 2),
    ("motor", "Pushes down on legs when feet on flat surface", 3),
    ("motor", "Rolls over in both directions", 6),
    ("motor", "Sits without support", 7),
    ("motor", "Crawls forward on belly", 8),
    ("motor", "Gets to sitting position without help", 9),
    ("motor", "Pulls self up to stand", 9),
    ("motor", "Walks holding on to furniture (cruising)", 10),
    ("motor", "Takes a few steps without holding on", 12),
    ("motor", "Walks independently", 14),
    ("motor", "Walks up steps with help", 18),
    ("motor", "Runs", 24),
    ("motor", "Kicks a ball forward", 24),
    ("motor", "Jumps with both feet off the ground", 30),
    ("motor", "Pedals a tricycle", 36),
    ("motor", "Hops on one foot", 48),
    ("motor", "Catches a bounced ball most of the time", 48),
    ("motor", "Skips", 60),
    ("language", "Coos and makes gurgling sounds", 2),
    ("language", "Babbles with expression (ba-ba, da-da)", 6),
    ("language", "Responds to own name", 7),
    ("language", "Understands 'no'", 9),
    ("language", "Says 'mama' and 'dada' with meaning", 12),
    ("language", "Says several single words", 15),
    ("language", "Says 2-4 word sentences", 24),
    ("language", "Names familiar items", 24),
    ("language", "Uses pronouns (I, me, you)", 30),
    ("language", "Strangers can understand most speech", 36),
    ("language", "Tells stories", 48),
    ("language", "Says full name and address", 60),
    ("language", "Uses future tense correctly", 60),
    ("social", "Begins to smile at people", 2),
    ("social", "Enjoys playing with others, especially parents", 4),
    ("social", "May be afraid of strangers", 8),
    ("social", "Has favorite things and people", 12),
    ("social", "Shows affection to familiar people", 12),
    ("social", "Plays alongside other children", 18),
    ("social", "Shows defiant behavior", 24),
    ("social", "Takes turns in games", 36),
    ("social", "Increasingly inventive in fantasy play", 36),
    ("social", "Can negotiate solutions to conflicts", 48),
    ("social", "Wants to please friends", 60),
    ("social", "Aware of gender", 60),
    ("social", "More likely to agree with rules", 60),
    ("cognitive", "Pays attention to faces", 2),
    ("cognitive", "Follows moving things with eyes", 3),
    ("cognitive", "Explores things by putting them in mouth", 6),
    ("cognitive", "Finds hidden objects easily", 12),
    ("cognitive", "Points to get attention of others", 14),
    ("cognitive", "Begins make-believe play", 18),
    ("cognitive", "Sorts shapes and colors", 24),
    ("cognitive", "Completes 3-4 piece puzzles", 30),
    ("cognitive", "Understands concept of counting", 36),
    ("cognitive", "Draws a person with 2-4 body parts", 48),
    ("cognitive", "Can count 10 or more objects", 48),
    ("cognitive", "Knows about everyday items (money, food, appliances)", 48),
    ("cognitive", "Can print some letters", 60),
    ("cognitive", "Copies triangle and other shapes", 60),
]

ACTIVITIES = [
    ("Tummy Time", "Place baby on stomach on a firm surface to strengthen neck and shoulder muscles", 0, 6, "motor", 10, "indoor"),
    ("High-Contrast Cards", "Show black and white high-contrast cards to stimulate visual development", 0, 4, "sensory", 10, "indoor"),
    ("Rattle Play", "Shake a rattle near baby's ear to encourage tracking and reaching", 2, 6, "sensory", 10, "indoor"),
    ("Peek-a-Boo", "Classic game that teaches object permanence and social bonding", 4, 12, "social", 10, "both"),
    ("Mirror Play", "Let baby see their reflection to build self-awareness", 3, 12, "cognitive", 10, "indoor"),
    ("Stacking Cups", "Demonstrate stacking and nesting cups for fine motor development", 6, 18, "motor", 15, "indoor"),
    ("Board Book Reading", "Read simple board books with bright pictures, name objects together", 3, 18, "language", 15, "indoor"),
    ("Music and Movement", "Play music and gently move baby's arms and legs to the beat", 2, 12, "music", 15, "indoor"),
    ("Sensory Bin - Rice", "Fill a shallow container with rice and safe objects to explore textures", 6, 18, "sensory", 20, "indoor"),
    ("Ball Rolling", "Roll a ball back and forth to practice tracking and reaching", 6, 18, "motor", 15, "both"),
    ("Shape Sorter", "Match shapes through correct holes for cognitive and fine motor development", 12, 30, "cognitive", 15, "indoor"),
    ("Finger Painting", "Use non-toxic finger paints on large paper for creative expression", 12, 48, "art", 30, "indoor"),
    ("Sandbox Play", "Dig, pour, and build in sand for sensory and fine motor skills", 12, 60, "sensory", 30, "outdoor"),
    ("Simple Puzzles", "Work on 2-6 piece puzzles to develop spatial reasoning", 18, 36, "cognitive", 20, "indoor"),
    ("Bubble Chasing", "Blow bubbles for toddler to chase and pop for gross motor skills", 12, 36, "motor", 15, "outdoor"),
    ("Play-Doh Sculpting", "Squeeze, roll, and shape play-doh for fine motor strength", 18, 60, "art", 30, "indoor"),
    ("Nursery Rhymes", "Sing songs with actions like Itsy Bitsy Spider for language and motor", 12, 36, "music", 15, "both"),
    ("Nature Walk Collection", "Walk outdoors collecting leaves, sticks, and rocks to explore nature", 18, 60, "science", 30, "outdoor"),
    ("Color Sorting", "Sort objects by color using bowls and small items", 18, 36, "cognitive", 20, "indoor"),
    ("Water Table Play", "Pour, splash, and experiment with water and cups", 12, 48, "sensory", 30, "outdoor"),
    ("Building with Blocks", "Stack and build towers with wooden or foam blocks", 12, 48, "motor", 20, "indoor"),
    ("Animal Sound Game", "Show animal pictures and practice making their sounds", 12, 30, "language", 15, "both"),
    ("Dancing to Music", "Put on music and dance freely for gross motor and rhythm", 12, 60, "music", 20, "both"),
    ("Pouring Practice", "Practice pouring water or rice between containers", 18, 36, "motor", 15, "indoor"),
    ("Letter Tracing", "Trace letters on worksheets or in sand/salt trays", 36, 72, "language", 20, "indoor"),
    ("Counting Games", "Count objects, fingers, toes, or steps during daily activities", 30, 60, "cognitive", 15, "both"),
    ("Obstacle Course", "Set up pillows, chairs, and tunnels for a physical challenge course", 30, 72, "motor", 30, "both"),
    ("Story Retelling", "Read a story then ask the child to retell it in their own words", 36, 72, "language", 20, "indoor"),
    ("Science Experiment - Volcano", "Baking soda and vinegar volcano to learn about reactions", 36, 72, "science", 30, "both"),
    ("Cooking Together", "Simple no-bake recipes to practice measuring, mixing, and following steps", 36, 72, "cognitive", 45, "indoor"),
    ("Pattern Making", "Create patterns with beads, blocks, or stickers (AB, ABC patterns)", 36, 60, "cognitive", 20, "indoor"),
    ("Freeze Dance", "Dance when music plays, freeze when it stops for self-regulation", 30, 72, "music", 15, "both"),
    ("Cutting Practice", "Use safety scissors to cut along lines for fine motor control", 36, 60, "motor", 20, "indoor"),
    ("Garden Planting", "Plant seeds and care for them to learn about growth and responsibility", 36, 72, "science", 30, "outdoor"),
    ("Memory Card Game", "Match pairs of cards to build working memory", 36, 72, "cognitive", 20, "indoor"),
    ("Dress-Up Play", "Imaginative play with costumes for social-emotional development", 30, 72, "social", 30, "indoor"),
    ("Scavenger Hunt", "Find items on a list around the house or yard", 36, 72, "cognitive", 30, "both"),
    ("Watercolor Painting", "Paint with watercolors and brushes for fine motor and creativity", 36, 72, "art", 30, "indoor"),
    ("Jump Rope", "Practice jumping over a rope for coordination and gross motor", 48, 72, "motor", 15, "outdoor"),
    ("Rhyming Games", "Come up with words that rhyme for phonological awareness", 36, 72, "language", 15, "both"),
]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "item"


def milestone_code(category: str, description: str) -> str:
    base = _slug(f"{category}_{description}")
    digest = hashlib.sha1(description.encode("utf-8")).hexdigest()[:8]
    return f"{base[:48]}_{digest}"


def activity_key(title: str) -> str:
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(title)[:48]}_{digest}"


def _rows_affected(status: str) -> int:
    try:
        return int(status.split()[-1])
    except Exception:
        return 0


async def seed_milestone_definitions(conn: asyncpg.Connection) -> int:
    inserted = 0
    for category, description, expected_months in MILESTONES:
        status = await conn.execute(
            "INSERT INTO milestone_definitions (code, category, description, expected_age_months) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (code) DO NOTHING",
            milestone_code(category, description),
            category,
            description,
            expected_months,
        )
        inserted += _rows_affected(status)
    return inserted


async def seed_activity_catalog(conn: asyncpg.Connection) -> int:
    inserted = 0
    for title, desc, min_age, max_age, category, duration, indoor_outdoor in ACTIVITIES:
        status = await conn.execute(
            "INSERT INTO activity_catalog (builtin_key, title, description, min_age_months, max_age_months, "
            "category, duration_minutes, indoor_outdoor) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT (builtin_key) DO NOTHING",
            activity_key(title),
            title,
            desc,
            min_age,
            max_age,
            category,
            duration,
            indoor_outdoor,
        )
        inserted += _rows_affected(status)
    return inserted


async def seed_learner_milestone_statuses(
    conn: asyncpg.Connection, learner_id: int | None = None
) -> int:
    if learner_id is not None:
        status = await conn.execute(
            "INSERT INTO learner_milestone_status (learner_id, milestone_definition_id, status) "
            "SELECT $1, md.id, 'pending' FROM milestone_definitions md "
            "ON CONFLICT (learner_id, milestone_definition_id) DO NOTHING",
            learner_id,
        )
        return _rows_affected(status)

    status = await conn.execute(
        "INSERT INTO learner_milestone_status (learner_id, milestone_definition_id, status) "
        "SELECT l.id, md.id, 'pending' "
        "FROM learners l CROSS JOIN milestone_definitions md "
        "ON CONFLICT (learner_id, milestone_definition_id) DO NOTHING"
    )
    return _rows_affected(status)


async def _main() -> None:
    learner_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=2,
        server_settings={"search_path": "family_edu,public"},
    )
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(SCHEMA_SQL)
                m = await seed_milestone_definitions(conn)
                a = await seed_activity_catalog(conn)
                s = await seed_learner_milestone_statuses(conn, learner_id)
                print(f"Seeded milestone_definitions: {m}")
                print(f"Seeded activity_catalog: {a}")
                print(f"Seeded learner_milestone_status: {s}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
