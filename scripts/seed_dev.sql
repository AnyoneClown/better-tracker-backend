-- Better Tracker local-development data.
--
-- This fixture is intentionally anchored to July 2026 so local screenshots and
-- dashboard checks remain deterministic. It can be run repeatedly: seed-owned
-- rows use stable UUIDs and are updated rather than duplicated. Existing rows
-- with other UUIDs are not deleted.

BEGIN;

-- Demo login: demo@example.com / DemoPassword1!
INSERT INTO users (id, email, hashed_password, is_active)
VALUES (
    '90000000-0000-4000-8000-000000000001',
    'demo@example.com',
    '$argon2id$v=19$m=65536,t=3,p=4$HAuTZ2VuZhnBzYIJ7C6VGA$q6/NspzPVwIBHdPTDtEKhcHPtHONOvEfvUEuzBtTa1k',
    true
)
ON CONFLICT (email) DO UPDATE SET
    hashed_password = excluded.hashed_password,
    is_active = true,
    updated_at = now();

-- Monthly budgets -----------------------------------------------------------

INSERT INTO monthly_budgets
    (id, user_id, year, month, category, currency, limit_amount)
VALUES
    ('20000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'housing',   'USD', 1800.00),
    ('20000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'food',      'USD',  700.00),
    ('20000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'transport', 'USD',  400.00),
    ('20000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'fun',       'USD',  350.00),
    ('20000000-0000-4000-8000-000000000005', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'health',    'USD',  200.00),
    ('20000000-0000-4000-8000-000000000006', (SELECT id FROM users WHERE email = 'demo@example.com'), 2026, 7, 'utilities', 'USD',  300.00)
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    year = excluded.year,
    month = excluded.month,
    category = excluded.category,
    currency = excluded.currency,
    limit_amount = excluded.limit_amount,
    updated_at = now();

-- Income and expenses -------------------------------------------------------

INSERT INTO financial_transactions
    (id, user_id, kind, amount, category, occurred_on, currency, description)
VALUES
    ('10000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), 'income',  6200.00, 'salary',    '2026-07-01', 'USD', 'Monthly salary'),
    ('10000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), 'income',   850.00, 'freelance', '2026-07-15', 'USD', 'Product design project'),
    ('10000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense', 1800.00, 'housing',   '2026-07-01', 'USD', 'Apartment rent'),
    ('10000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',  142.35, 'food',      '2026-07-03', 'USD', 'Weekly groceries'),
    ('10000000-0000-4000-8000-000000000005', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',  168.42, 'utilities', '2026-07-05', 'USD', 'Electricity and internet'),
    ('10000000-0000-4000-8000-000000000006', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   65.00, 'transport', '2026-07-07', 'USD', 'Monthly transit pass'),
    ('10000000-0000-4000-8000-000000000007', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   86.70, 'food',      '2026-07-10', 'USD', 'Dinner with friends'),
    ('10000000-0000-4000-8000-000000000008', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   55.00, 'health',    '2026-07-12', 'USD', 'Gym membership'),
    ('10000000-0000-4000-8000-000000000009', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   74.20, 'transport', '2026-07-18', 'USD', 'Fuel'),
    ('10000000-0000-4000-8000-000000000010', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',  120.00, 'fun',       '2026-07-20', 'USD', 'Concert tickets'),
    ('10000000-0000-4000-8000-000000000011', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   96.15, 'food',      '2026-07-22', 'USD', 'Weekly groceries'),
    ('10000000-0000-4000-8000-000000000012', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',    8.50, 'food',      '2026-07-24', 'USD', 'Morning coffee'),
    ('10000000-0000-4000-8000-000000000013', (SELECT id FROM users WHERE email = 'demo@example.com'), 'expense',   18.75, 'food',      '2026-07-25', 'USD', 'Breakfast')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    kind = excluded.kind,
    amount = excluded.amount,
    category = excluded.category,
    occurred_on = excluded.occurred_on,
    currency = excluded.currency,
    description = excluded.description,
    updated_at = now();

-- Workouts and exercise sets ------------------------------------------------

INSERT INTO workouts
    (id, user_id, name, performed_at, duration_minutes, notes)
VALUES
    ('30000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Full-body strength', '2026-07-18 09:00:00+00', 50, 'Steady session, moderate load.'),
    ('30000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Upper body',         '2026-07-22 17:30:00+00', 55, 'Added weight to the final bench set.'),
    ('30000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Run intervals',      '2026-07-23 06:45:00+00', 42, 'Five easy-to-fast intervals.'),
    ('30000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Lower body',         '2026-07-24 17:45:00+00', 60, 'Good depth and controlled tempo.')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    name = excluded.name,
    performed_at = excluded.performed_at,
    duration_minutes = excluded.duration_minutes,
    notes = excluded.notes,
    updated_at = now();

INSERT INTO workout_sets
    (id, workout_id, exercise, set_number, reps, weight_kg, distance_km, duration_seconds, notes)
VALUES
    ('31000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', 'goblet squat',       1, 12, 24.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000001', 'goblet squat',       2, 12, 24.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000001', 'shoulder press',     1, 10, 18.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000004', '30000000-0000-4000-8000-000000000001', 'shoulder press',     2, 10, 18.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000005', '30000000-0000-4000-8000-000000000002', 'bench press',        1,  8, 60.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000006', '30000000-0000-4000-8000-000000000002', 'bench press',        2,  8, 62.500, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000007', '30000000-0000-4000-8000-000000000002', 'bench press',        3,  7, 65.000, NULL,  NULL, 'One rep short of target.'),
    ('31000000-0000-4000-8000-000000000008', '30000000-0000-4000-8000-000000000002', 'lat pulldown',       1, 10, 55.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000009', '30000000-0000-4000-8000-000000000002', 'lat pulldown',       2, 10, 55.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000010', '30000000-0000-4000-8000-000000000003', 'running',          1, NULL,   NULL, 5.200, 2520, 'Interval workout total.'),
    ('31000000-0000-4000-8000-000000000011', '30000000-0000-4000-8000-000000000004', 'back squat',         1,  8, 80.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000012', '30000000-0000-4000-8000-000000000004', 'back squat',         2,  8, 80.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000013', '30000000-0000-4000-8000-000000000004', 'back squat',         3,  8, 82.500, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000014', '30000000-0000-4000-8000-000000000004', 'romanian deadlift',  1, 10, 70.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000015', '30000000-0000-4000-8000-000000000004', 'romanian deadlift',  2, 10, 70.000, NULL,  NULL, NULL),
    ('31000000-0000-4000-8000-000000000016', '30000000-0000-4000-8000-000000000004', 'romanian deadlift',  3,  9, 70.000, NULL,  NULL, NULL)
ON CONFLICT (id) DO UPDATE SET
    workout_id = excluded.workout_id,
    exercise = excluded.exercise,
    set_number = excluded.set_number,
    reps = excluded.reps,
    weight_kg = excluded.weight_kg,
    distance_km = excluded.distance_km,
    duration_seconds = excluded.duration_seconds,
    notes = excluded.notes,
    updated_at = now();

-- Body weight and nutrition -------------------------------------------------

INSERT INTO weight_entries
    (id, user_id, recorded_on, weight_kg, body_fat_percent, notes)
VALUES
    ('40000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-01', 78.40, 18.60, 'Start-of-month check-in'),
    ('40000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-08', 78.00, 18.40, 'Morning weigh-in'),
    ('40000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-15', 77.60, 18.20, 'Morning weigh-in'),
    ('40000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-22', 77.20, 18.00, 'Morning weigh-in'),
    ('40000000-0000-4000-8000-000000000005', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-25', 77.00, 17.90, 'Weekly check-in')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    recorded_on = excluded.recorded_on,
    weight_kg = excluded.weight_kg,
    body_fat_percent = excluded.body_fat_percent,
    notes = excluded.notes,
    updated_at = now();

INSERT INTO nutrition_logs
    (id, user_id, recorded_on, calories, calorie_target, protein_grams, carbs_grams, fat_grams, notes)
VALUES
    ('50000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-20', 2180, 2300, 148.00, 235.00, 72.00, 'Balanced day'),
    ('50000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-21', 2240, 2300, 152.00, 246.00, 70.00, 'Meal prep day'),
    ('50000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-22', 2095, 2300, 158.00, 210.00, 69.00, 'High-protein day'),
    ('50000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-23', 2325, 2300, 145.00, 270.00, 73.00, 'Post-run refuel'),
    ('50000000-0000-4000-8000-000000000005', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-24', 2150, 2300, 160.00, 220.00, 68.00, 'Training day meals'),
    ('50000000-0000-4000-8000-000000000006', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-25', 2050, 2300, 155.00, 205.00, 67.00, 'On target today')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    recorded_on = excluded.recorded_on,
    calories = excluded.calories,
    calorie_target = excluded.calorie_target,
    protein_grams = excluded.protein_grams,
    carbs_grams = excluded.carbs_grams,
    fat_grams = excluded.fat_grams,
    notes = excluded.notes,
    updated_at = now();

-- Accounts, savings goals, and history -------------------------------------

INSERT INTO financial_accounts
    (id, user_id, name, account_type, category, balance, currency, include_in_net_worth, is_savings)
VALUES
    ('60000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Everyday checking', 'asset',     'cash',       4820.00, 'USD', true,  false),
    ('60000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), 'High-yield savings','asset',     'cash',      12400.00, 'USD', true,  true),
    ('60000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Brokerage',          'asset',     'investment',31380.00, 'USD', true,  false),
    ('60000000-0000-4000-8000-000000000004', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Credit card',        'liability', 'credit',     1650.00, 'USD', true,  false),
    ('60000000-0000-4000-8000-000000000005', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Student loan',       'liability', 'loan',       2700.00, 'USD', true,  false)
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    name = excluded.name,
    account_type = excluded.account_type,
    category = excluded.category,
    balance = excluded.balance,
    currency = excluded.currency,
    include_in_net_worth = excluded.include_in_net_worth,
    is_savings = excluded.is_savings,
    updated_at = now();

INSERT INTO savings_goals
    (id, user_id, name, target_amount, current_amount, currency, target_date, notes)
VALUES
    ('70000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Emergency fund', 12000.00, 7850.00, 'USD', '2027-06-30', 'Six months of essential expenses.'),
    ('70000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), 'Japan trip',      4000.00, 1800.00, 'USD', '2026-12-31', 'Flights, hotels, and local travel.')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    name = excluded.name,
    target_amount = excluded.target_amount,
    current_amount = excluded.current_amount,
    currency = excluded.currency,
    target_date = excluded.target_date,
    notes = excluded.notes,
    updated_at = now();

INSERT INTO savings_contributions
    (id, goal_id, kind, amount, occurred_on, notes)
VALUES
    ('71000000-0000-4000-8000-000000000001', '70000000-0000-4000-8000-000000000001', 'contribution', 6500.00, '2026-05-01', 'Opening balance'),
    ('71000000-0000-4000-8000-000000000002', '70000000-0000-4000-8000-000000000001', 'contribution',  750.00, '2026-06-15', 'Monthly transfer'),
    ('71000000-0000-4000-8000-000000000003', '70000000-0000-4000-8000-000000000001', 'contribution',  600.00, '2026-07-05', 'Monthly transfer'),
    ('71000000-0000-4000-8000-000000000004', '70000000-0000-4000-8000-000000000002', 'contribution', 1500.00, '2026-06-01', 'Opening balance'),
    ('71000000-0000-4000-8000-000000000005', '70000000-0000-4000-8000-000000000002', 'contribution',  300.00, '2026-07-12', 'Travel fund transfer')
ON CONFLICT (id) DO UPDATE SET
    goal_id = excluded.goal_id,
    kind = excluded.kind,
    amount = excluded.amount,
    occurred_on = excluded.occurred_on,
    notes = excluded.notes,
    updated_at = now();

INSERT INTO net_worth_snapshots
    (id, user_id, recorded_at, assets, liabilities, currency, notes)
VALUES
    ('80000000-0000-4000-8000-000000000001', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-05-31 20:00:00+00', 43800.00, 5100.00, 'USD', 'End-of-May snapshot'),
    ('80000000-0000-4000-8000-000000000002', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-06-30 20:00:00+00', 46200.00, 4750.00, 'USD', 'End-of-June snapshot'),
    ('80000000-0000-4000-8000-000000000003', (SELECT id FROM users WHERE email = 'demo@example.com'), '2026-07-24 20:00:00+00', 48600.00, 4350.00, 'USD', 'Current demo balances')
ON CONFLICT (id) DO UPDATE SET
    user_id = excluded.user_id,
    recorded_at = excluded.recorded_at,
    assets = excluded.assets,
    liabilities = excluded.liabilities,
    currency = excluded.currency,
    notes = excluded.notes,
    updated_at = now();

COMMIT;
