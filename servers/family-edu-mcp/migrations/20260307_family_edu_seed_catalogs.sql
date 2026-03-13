BEGIN;

SET search_path TO family_edu, public;

INSERT INTO milestone_definitions (code, category, description, expected_age_months)
VALUES
    ('motor_raises_head_and_chest_when_lying_on_stomac_fa4ffe26', 'motor', 'Raises head and chest when lying on stomach', 2),
    ('motor_pushes_down_on_legs_when_feet_on_flat_surf_50605a19', 'motor', 'Pushes down on legs when feet on flat surface', 3),
    ('motor_rolls_over_in_both_directions_caf79262', 'motor', 'Rolls over in both directions', 6),
    ('motor_sits_without_support_15b13c67', 'motor', 'Sits without support', 7),
    ('motor_crawls_forward_on_belly_47116c78', 'motor', 'Crawls forward on belly', 8),
    ('motor_gets_to_sitting_position_without_help_12a5033f', 'motor', 'Gets to sitting position without help', 9),
    ('motor_pulls_self_up_to_stand_33398d0a', 'motor', 'Pulls self up to stand', 9),
    ('motor_walks_holding_on_to_furniture_cruising_5ad08fa4', 'motor', 'Walks holding on to furniture (cruising)', 10),
    ('motor_takes_a_few_steps_without_holding_on_21fdda44', 'motor', 'Takes a few steps without holding on', 12),
    ('motor_walks_independently_9d0594b1', 'motor', 'Walks independently', 14),
    ('motor_walks_up_steps_with_help_1e7dafbb', 'motor', 'Walks up steps with help', 18),
    ('motor_runs_fcde5c32', 'motor', 'Runs', 24),
    ('motor_kicks_a_ball_forward_e82c25cc', 'motor', 'Kicks a ball forward', 24),
    ('motor_jumps_with_both_feet_off_the_ground_c8cf699f', 'motor', 'Jumps with both feet off the ground', 30),
    ('motor_pedals_a_tricycle_360e3716', 'motor', 'Pedals a tricycle', 36),
    ('motor_hops_on_one_foot_f64d4068', 'motor', 'Hops on one foot', 48),
    ('motor_catches_a_bounced_ball_most_of_the_time_779b5f5b', 'motor', 'Catches a bounced ball most of the time', 48),
    ('motor_skips_8bd65f99', 'motor', 'Skips', 60),
    ('language_coos_and_makes_gurgling_sounds_db389058', 'language', 'Coos and makes gurgling sounds', 2),
    ('language_babbles_with_expression_ba_ba_da_da_f272b1cb', 'language', 'Babbles with expression (ba-ba, da-da)', 6),
    ('language_responds_to_own_name_9802c253', 'language', 'Responds to own name', 7),
    ('language_understands_no_807f6bc6', 'language', 'Understands ''no''', 9),
    ('language_says_mama_and_dada_with_meaning_94ee73d6', 'language', 'Says ''mama'' and ''dada'' with meaning', 12),
    ('language_says_several_single_words_04bae2d7', 'language', 'Says several single words', 15),
    ('language_says_2_4_word_sentences_4b4e72f8', 'language', 'Says 2-4 word sentences', 24),
    ('language_names_familiar_items_fad9037f', 'language', 'Names familiar items', 24),
    ('language_uses_pronouns_i_me_you_7929e651', 'language', 'Uses pronouns (I, me, you)', 30),
    ('language_strangers_can_understand_most_speech_71c15252', 'language', 'Strangers can understand most speech', 36),
    ('language_tells_stories_fe1cff42', 'language', 'Tells stories', 48),
    ('language_says_full_name_and_address_6c0a712c', 'language', 'Says full name and address', 60),
    ('language_uses_future_tense_correctly_ad58803a', 'language', 'Uses future tense correctly', 60),
    ('social_begins_to_smile_at_people_e95e0c4d', 'social', 'Begins to smile at people', 2),
    ('social_enjoys_playing_with_others_especially_par_b3e292ec', 'social', 'Enjoys playing with others, especially parents', 4),
    ('social_may_be_afraid_of_strangers_84bd9fee', 'social', 'May be afraid of strangers', 8),
    ('social_has_favorite_things_and_people_1640160f', 'social', 'Has favorite things and people', 12),
    ('social_shows_affection_to_familiar_people_686adf88', 'social', 'Shows affection to familiar people', 12),
    ('social_plays_alongside_other_children_a49f9d05', 'social', 'Plays alongside other children', 18),
    ('social_shows_defiant_behavior_a8130c7f', 'social', 'Shows defiant behavior', 24),
    ('social_takes_turns_in_games_296d445a', 'social', 'Takes turns in games', 36),
    ('social_increasingly_inventive_in_fantasy_play_cc66006e', 'social', 'Increasingly inventive in fantasy play', 36),
    ('social_can_negotiate_solutions_to_conflicts_3d08f59d', 'social', 'Can negotiate solutions to conflicts', 48),
    ('social_wants_to_please_friends_03b90e84', 'social', 'Wants to please friends', 60),
    ('social_aware_of_gender_88e9cae4', 'social', 'Aware of gender', 60),
    ('social_more_likely_to_agree_with_rules_2ddca29a', 'social', 'More likely to agree with rules', 60),
    ('cognitive_pays_attention_to_faces_1f4612ba', 'cognitive', 'Pays attention to faces', 2),
    ('cognitive_follows_moving_things_with_eyes_4786ce7f', 'cognitive', 'Follows moving things with eyes', 3),
    ('cognitive_explores_things_by_putting_them_in_mou_64264ebb', 'cognitive', 'Explores things by putting them in mouth', 6),
    ('cognitive_finds_hidden_objects_easily_13887a94', 'cognitive', 'Finds hidden objects easily', 12),
    ('cognitive_points_to_get_attention_of_others_666f7589', 'cognitive', 'Points to get attention of others', 14),
    ('cognitive_begins_make_believe_play_b4f55e0d', 'cognitive', 'Begins make-believe play', 18),
    ('cognitive_sorts_shapes_and_colors_7e616239', 'cognitive', 'Sorts shapes and colors', 24),
    ('cognitive_completes_3_4_piece_puzzles_0e026e00', 'cognitive', 'Completes 3-4 piece puzzles', 30),
    ('cognitive_understands_concept_of_counting_15d20fe6', 'cognitive', 'Understands concept of counting', 36),
    ('cognitive_draws_a_person_with_2_4_body_parts_757d2491', 'cognitive', 'Draws a person with 2-4 body parts', 48),
    ('cognitive_can_count_10_or_more_objects_6dbfae6a', 'cognitive', 'Can count 10 or more objects', 48),
    ('cognitive_knows_about_everyday_items_money_food__f31efae8', 'cognitive', 'Knows about everyday items (money, food, appliances)', 48),
    ('cognitive_can_print_some_letters_32a2de5c', 'cognitive', 'Can print some letters', 60),
    ('cognitive_copies_triangle_and_other_shapes_54b70649', 'cognitive', 'Copies triangle and other shapes', 60)
ON CONFLICT (code) DO NOTHING;

INSERT INTO activity_catalog (
    builtin_key,
    title,
    description,
    min_age_months,
    max_age_months,
    category,
    duration_minutes,
    indoor_outdoor
)
VALUES
    ('tummy_time_68505f1b', 'Tummy Time', 'Place baby on stomach on a firm surface to strengthen neck and shoulder muscles', 0, 6, 'motor', 10, 'indoor'),
    ('high_contrast_cards_f1aeda1c', 'High-Contrast Cards', 'Show black and white high-contrast cards to stimulate visual development', 0, 4, 'sensory', 10, 'indoor'),
    ('rattle_play_9b8bb49d', 'Rattle Play', 'Shake a rattle near baby''s ear to encourage tracking and reaching', 2, 6, 'sensory', 10, 'indoor'),
    ('peek_a_boo_fcef07e1', 'Peek-a-Boo', 'Classic game that teaches object permanence and social bonding', 4, 12, 'social', 10, 'both'),
    ('mirror_play_77aacb4f', 'Mirror Play', 'Let baby see their reflection to build self-awareness', 3, 12, 'cognitive', 10, 'indoor'),
    ('stacking_cups_f3a916d2', 'Stacking Cups', 'Demonstrate stacking and nesting cups for fine motor development', 6, 18, 'motor', 15, 'indoor'),
    ('board_book_reading_f08eb779', 'Board Book Reading', 'Read simple board books with bright pictures, name objects together', 3, 18, 'language', 15, 'indoor'),
    ('music_and_movement_2dba2569', 'Music and Movement', 'Play music and gently move baby''s arms and legs to the beat', 2, 12, 'music', 15, 'indoor'),
    ('sensory_bin_rice_b8bb0056', 'Sensory Bin - Rice', 'Fill a shallow container with rice and safe objects to explore textures', 6, 18, 'sensory', 20, 'indoor'),
    ('ball_rolling_9e5c7b53', 'Ball Rolling', 'Roll a ball back and forth to practice tracking and reaching', 6, 18, 'motor', 15, 'both'),
    ('shape_sorter_0e4bf0df', 'Shape Sorter', 'Match shapes through correct holes for cognitive and fine motor development', 12, 30, 'cognitive', 15, 'indoor'),
    ('finger_painting_a4703191', 'Finger Painting', 'Use non-toxic finger paints on large paper for creative expression', 12, 48, 'art', 30, 'indoor'),
    ('sandbox_play_eb6a3a5e', 'Sandbox Play', 'Dig, pour, and build in sand for sensory and fine motor skills', 12, 60, 'sensory', 30, 'outdoor'),
    ('simple_puzzles_14c35ec5', 'Simple Puzzles', 'Work on 2-6 piece puzzles to develop spatial reasoning', 18, 36, 'cognitive', 20, 'indoor'),
    ('bubble_chasing_2c3821c6', 'Bubble Chasing', 'Blow bubbles for toddler to chase and pop for gross motor skills', 12, 36, 'motor', 15, 'outdoor'),
    ('play_doh_sculpting_828d6939', 'Play-Doh Sculpting', 'Squeeze, roll, and shape play-doh for fine motor strength', 18, 60, 'art', 30, 'indoor'),
    ('nursery_rhymes_d64c7199', 'Nursery Rhymes', 'Sing songs with actions like Itsy Bitsy Spider for language and motor', 12, 36, 'music', 15, 'both'),
    ('nature_walk_collection_bc691cc0', 'Nature Walk Collection', 'Walk outdoors collecting leaves, sticks, and rocks to explore nature', 18, 60, 'science', 30, 'outdoor'),
    ('color_sorting_0db06b6f', 'Color Sorting', 'Sort objects by color using bowls and small items', 18, 36, 'cognitive', 20, 'indoor'),
    ('water_table_play_f7b26e5a', 'Water Table Play', 'Pour, splash, and experiment with water and cups', 12, 48, 'sensory', 30, 'outdoor'),
    ('building_with_blocks_de74587b', 'Building with Blocks', 'Stack and build towers with wooden or foam blocks', 12, 48, 'motor', 20, 'indoor'),
    ('animal_sound_game_17c1620a', 'Animal Sound Game', 'Show animal pictures and practice making their sounds', 12, 30, 'language', 15, 'both'),
    ('dancing_to_music_62222552', 'Dancing to Music', 'Put on music and dance freely for gross motor and rhythm', 12, 60, 'music', 20, 'both'),
    ('pouring_practice_62db1cef', 'Pouring Practice', 'Practice pouring water or rice between containers', 18, 36, 'motor', 15, 'indoor'),
    ('letter_tracing_196449fa', 'Letter Tracing', 'Trace letters on worksheets or in sand/salt trays', 36, 72, 'language', 20, 'indoor'),
    ('counting_games_c24b9ff6', 'Counting Games', 'Count objects, fingers, toes, or steps during daily activities', 30, 60, 'cognitive', 15, 'both'),
    ('obstacle_course_55ac0c29', 'Obstacle Course', 'Set up pillows, chairs, and tunnels for a physical challenge course', 30, 72, 'motor', 30, 'both'),
    ('story_retelling_d041141b', 'Story Retelling', 'Read a story then ask the child to retell it in their own words', 36, 72, 'language', 20, 'indoor'),
    ('science_experiment_volcano_ab3aa2b1', 'Science Experiment - Volcano', 'Baking soda and vinegar volcano to learn about reactions', 36, 72, 'science', 30, 'both'),
    ('cooking_together_21bfd99f', 'Cooking Together', 'Simple no-bake recipes to practice measuring, mixing, and following steps', 36, 72, 'cognitive', 45, 'indoor'),
    ('pattern_making_1ae3eab3', 'Pattern Making', 'Create patterns with beads, blocks, or stickers (AB, ABC patterns)', 36, 60, 'cognitive', 20, 'indoor'),
    ('freeze_dance_bc5ff89e', 'Freeze Dance', 'Dance when music plays, freeze when it stops for self-regulation', 30, 72, 'music', 15, 'both'),
    ('cutting_practice_94780a63', 'Cutting Practice', 'Use safety scissors to cut along lines for fine motor control', 36, 60, 'motor', 20, 'indoor'),
    ('garden_planting_642f03e3', 'Garden Planting', 'Plant seeds and care for them to learn about growth and responsibility', 36, 72, 'science', 30, 'outdoor'),
    ('memory_card_game_70a4c07c', 'Memory Card Game', 'Match pairs of cards to build working memory', 36, 72, 'cognitive', 20, 'indoor'),
    ('dress_up_play_cde69a9c', 'Dress-Up Play', 'Imaginative play with costumes for social-emotional development', 30, 72, 'social', 30, 'indoor'),
    ('scavenger_hunt_9eeadacb', 'Scavenger Hunt', 'Find items on a list around the house or yard', 36, 72, 'cognitive', 30, 'both'),
    ('watercolor_painting_f1fcb558', 'Watercolor Painting', 'Paint with watercolors and brushes for fine motor and creativity', 36, 72, 'art', 30, 'indoor'),
    ('jump_rope_b3d9b26a', 'Jump Rope', 'Practice jumping over a rope for coordination and gross motor', 48, 72, 'motor', 15, 'outdoor'),
    ('rhyming_games_88ba2091', 'Rhyming Games', 'Come up with words that rhyme for phonological awareness', 36, 72, 'language', 15, 'both')
ON CONFLICT (builtin_key) DO NOTHING;

INSERT INTO learner_milestone_status (learner_id, milestone_definition_id, status)
SELECT l.id, md.id, 'pending'
FROM learners l
CROSS JOIN milestone_definitions md
ON CONFLICT (learner_id, milestone_definition_id) DO NOTHING;

CREATE OR REPLACE FUNCTION ensure_new_learner_milestone_statuses()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO learner_milestone_status (learner_id, milestone_definition_id, status)
    SELECT NEW.id, md.id, 'pending'
    FROM milestone_definitions md
    ON CONFLICT (learner_id, milestone_definition_id) DO NOTHING;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_ensure_new_learner_milestone_statuses ON learners;

CREATE TRIGGER trg_ensure_new_learner_milestone_statuses
AFTER INSERT ON learners
FOR EACH ROW
EXECUTE FUNCTION ensure_new_learner_milestone_statuses();

COMMIT;
