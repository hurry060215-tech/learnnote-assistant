"""Exact current SQLite schema signatures for the stopped-copy migration.

Captured from the app-owned CREATE/ALTER statements, independently exercised by
producer-based tests. Older or unknown signatures require reviewed recovery;
copying never upgrades them. SQL literal case is significant.
"""

EXPECTED_SCHEMAS = {'activation.sqlite3': {'facts': ('table',
                                  'facts',
                                  'CREATE TABLE facts (name TEXT PRIMARY KEY, recorded REAL NOT NULL)'),
                        'preferences': ('table',
                                        'preferences',
                                        'CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), '
                                        'enabled INTEGER NOT NULL)'),
                        'sqlite_autoindex_facts_1': ('index', 'facts', None)},
 'community.sqlite3': {'community_context_items': ('table',
                                                   'community_context_items',
                                                   'CREATE TABLE community_context_items (item_id TEXT '
                                                   'PRIMARY KEY, schema_version INTEGER NOT NULL, task_id '
                                                   'TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, '
                                                   'timestamp_seconds REAL, author_label TEXT NOT NULL, '
                                                   'source_uri TEXT NOT NULL, fingerprint TEXT NOT NULL, '
                                                   'created_at TEXT NOT NULL, UNIQUE(task_id, fingerprint))'),
                       'community_context_task_idx': ('index',
                                                      'community_context_items',
                                                      'CREATE INDEX community_context_task_idx ON '
                                                      'community_context_items(task_id, created_at)'),
                       'community_meta': ('table',
                                          'community_meta',
                                          'CREATE TABLE community_meta (key TEXT PRIMARY KEY, value TEXT NOT '
                                          'NULL)'),
                       'sqlite_autoindex_community_context_items_1': ('index',
                                                                      'community_context_items',
                                                                      None),
                       'sqlite_autoindex_community_context_items_2': ('index',
                                                                      'community_context_items',
                                                                      None),
                       'sqlite_autoindex_community_meta_1': ('index', 'community_meta', None)},
 'course-episodes.sqlite3': {'course_episodes': ('table',
                                                 'course_episodes',
                                                 'CREATE TABLE course_episodes (course_id TEXT NOT NULL, '
                                                 'episode_id TEXT NOT NULL, source_url TEXT NOT NULL, '
                                                 'handoff_id TEXT NOT NULL, task_id TEXT NOT NULL DEFAULT '
                                                 "'', updated_at TEXT NOT NULL, PRIMARY "
                                                 'KEY(course_id,episode_id), UNIQUE(handoff_id))'),
                             'sqlite_autoindex_course_episodes_1': ('index', 'course_episodes', None),
                             'sqlite_autoindex_course_episodes_2': ('index', 'course_episodes', None)},
 'study.sqlite3': {'sqlite_autoindex_study_card_spaces_1': ('index', 'study_card_spaces', None),
                   'sqlite_autoindex_study_cards_1': ('index', 'study_cards', None),
                   'sqlite_autoindex_study_plans_1': ('index', 'study_plans', None),
                   'sqlite_autoindex_study_quiz_attempts_1': ('index', 'study_quiz_attempts', None),
                   'sqlite_sequence': ('table', 'sqlite_sequence', 'CREATE TABLE sqlite_sequence(name,seq)'),
                   'study_activity': ('table',
                                      'study_activity',
                                      'CREATE TABLE study_activity (activity_id INTEGER PRIMARY KEY '
                                      'AUTOINCREMENT, kind TEXT NOT NULL, source_id TEXT NOT NULL, '
                                      "occurred_at TEXT NOT NULL, idempotency_key TEXT NOT NULL DEFAULT '')"),
                   'study_activity_idempotency_idx': ('index',
                                                      'study_activity',
                                                      'CREATE UNIQUE INDEX study_activity_idempotency_idx ON '
                                                      'study_activity(kind,source_id,idempotency_key) WHERE '
                                                      "idempotency_key != ''"),
                   'study_card_spaces': ('table',
                                         'study_card_spaces',
                                         'CREATE TABLE study_card_spaces (card_id TEXT NOT NULL, space_id '
                                         'TEXT NOT NULL, assigned_at TEXT NOT NULL, PRIMARY KEY (card_id, '
                                         'space_id))'),
                   'study_cards': ('table',
                                   'study_cards',
                                   'CREATE TABLE study_cards (card_id TEXT PRIMARY KEY, schema_version '
                                   'INTEGER NOT NULL, front TEXT NOT NULL, back TEXT NOT NULL, '
                                   'source_evidence_ids TEXT NOT NULL, status TEXT NOT NULL, due_at TEXT NOT '
                                   'NULL, stability REAL NOT NULL, difficulty REAL NOT NULL, reps INTEGER '
                                   'NOT NULL, lapses INTEGER NOT NULL, last_reviewed_at TEXT NOT NULL, '
                                   "fsrs_state TEXT NOT NULL DEFAULT 'Learning', step INTEGER NOT NULL "
                                   'DEFAULT 0, position INTEGER NOT NULL DEFAULT 0)'),
                   'study_plans': ('table',
                                   'study_plans',
                                   'CREATE TABLE study_plans (plan_id TEXT PRIMARY KEY, schema_version '
                                   'INTEGER NOT NULL, title TEXT NOT NULL, daily_target INTEGER NOT NULL, '
                                   'paused INTEGER NOT NULL, timezone TEXT NOT NULL, created_at TEXT NOT '
                                   'NULL, updated_at TEXT NOT NULL , timezone_initialized INTEGER NOT NULL '
                                   'DEFAULT 0)'),
                   'study_quiz_attempts': ('table',
                                           'study_quiz_attempts',
                                           'CREATE TABLE study_quiz_attempts (attempt_id INTEGER PRIMARY KEY '
                                           'AUTOINCREMENT, card_id TEXT NOT NULL, question_revision TEXT NOT '
                                           'NULL, question TEXT NOT NULL, expected_answer TEXT NOT NULL, '
                                           'submitted_answer TEXT NOT NULL, correct INTEGER NOT NULL, '
                                           'source_evidence_ids TEXT NOT NULL, attempted_at TEXT NOT NULL, '
                                           'scorer TEXT NOT NULL, idempotency_key TEXT NOT NULL, '
                                           'UNIQUE(card_id, idempotency_key))'),
                   'study_review_idempotency_idx': ('index',
                                                    'study_reviews',
                                                    'CREATE UNIQUE INDEX study_review_idempotency_idx ON '
                                                    'study_reviews(card_id, idempotency_key) WHERE '
                                                    "idempotency_key != ''"),
                   'study_reviews': ('table',
                                     'study_reviews',
                                     'CREATE TABLE study_reviews (review_id INTEGER PRIMARY KEY '
                                     'AUTOINCREMENT, card_id TEXT NOT NULL, rating INTEGER NOT NULL, '
                                     'reviewed_at TEXT NOT NULL, due_at TEXT NOT NULL, stability REAL NOT '
                                     'NULL, difficulty REAL NOT NULL ,idempotency_key TEXT NOT NULL DEFAULT '
                                     "'')")},
 'task-queue.sqlite3': {'jobs': ('table',
                                 'jobs',
                                 'CREATE TABLE jobs (sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id '
                                 'TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, requires_context INTEGER NOT '
                                 'NULL, state TEXT NOT NULL, updated_at REAL NOT NULL, priority INTEGER NOT '
                                 "NULL DEFAULT 0, generation TEXT NOT NULL DEFAULT '', cancel_operation_id "
                                 "TEXT NOT NULL DEFAULT '', callback_finished INTEGER, owner_id TEXT NOT NULL DEFAULT '')"),
                        'queue_settings': ('table',
                                           'queue_settings',
                                           'CREATE TABLE queue_settings (id INTEGER PRIMARY KEY CHECK(id=1), '
                                           'paused INTEGER NOT NULL)'),
                        'sqlite_autoindex_jobs_1': ('index', 'jobs', None),
                        'sqlite_sequence': ('table',
                                            'sqlite_sequence',
                                            'CREATE TABLE sqlite_sequence(name,seq)')},
 'token-usage.sqlite3': {'usage': ('table',
                                   'usage',
                                   'CREATE TABLE usage (at TEXT, model TEXT, host TEXT, purpose TEXT, status '
                                   'TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, '
                                   'elapsed_ms INTEGER)')}}
