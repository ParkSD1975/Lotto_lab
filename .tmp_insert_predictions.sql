
INSERT INTO weekly_predictions (target_round, top_5, exclude_10, model_weights, meta_active, meta_alpha, pipeline_version, created_at, updated_at,
  catboost_active, tabnet_active, tft_active, mhn_active, bayesian_nn_active, nbeats_active)
VALUES (
  1224,
  ARRAY[12, 40, 37, 19, 35]::int[],
  ARRAY[43, 36, 11, 22, 2, 3, 25, 14, 5, 9]::int[],
  '{"xgboost": 0.2315, "catboost": 0.084, "tabnet": 0.056, "cnn": 0.0926, "gnn": 0.1389, "markov": 0.0993, "autoencoder": 0.0286, "tft": 0.1992, "mhn": 0.035, "bayesian_nn": 0.035, "lstm": 0.0, "transformer": 0.0}'::jsonb,
  true, 0.3, 'v2', NOW(), NOW(),
  true, true, true, true, true, false
)
ON CONFLICT (target_round) DO UPDATE SET
  top_5 = EXCLUDED.top_5,
  exclude_10 = EXCLUDED.exclude_10,
  model_weights = EXCLUDED.model_weights,
  updated_at = NOW();


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 1, ARRAY[13, 19, 23, 29, 31, 40]::int[], 155, 5, 4, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 2, ARRAY[6, 12, 16, 29, 30, 44]::int[], 137, 1, 3, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 3, ARRAY[4, 13, 15, 32, 37, 45]::int[], 146, 4, 3, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 4, ARRAY[1, 7, 13, 27, 33, 41]::int[], 122, 6, 3, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 5, ARRAY[6, 7, 12, 37, 40, 42]::int[], 144, 2, 3, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 6, ARRAY[7, 19, 23, 28, 35, 42]::int[], 154, 4, 4, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 7, ARRAY[1, 19, 27, 29, 33, 37]::int[], 146, 6, 4, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 8, ARRAY[7, 10, 21, 27, 33, 34]::int[], 132, 4, 3, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 9, ARRAY[13, 16, 23, 29, 32, 33]::int[], 146, 4, 4, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;


INSERT INTO weekly_combinations (target_round, combo_rank, numbers, total_sum, odd_count, high_count, created_at)
VALUES (1224, 10, ARRAY[4, 17, 19, 21, 28, 37]::int[], 126, 4, 2, NOW())
ON CONFLICT (target_round, combo_rank) DO UPDATE SET
  numbers = EXCLUDED.numbers, total_sum = EXCLUDED.total_sum,
  odd_count = EXCLUDED.odd_count, high_count = EXCLUDED.high_count;
