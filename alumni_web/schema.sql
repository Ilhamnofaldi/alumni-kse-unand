PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS alumni (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  gender TEXT,
  date_of_birth TEXT,
  domicile TEXT,
  city TEXT,
  province TEXT,
  lat REAL,
  lng REAL,
  workplace TEXT,
  phone TEXT,
  phone_normalized TEXT,
  email TEXT,
  email_normalized TEXT,
  status_code TEXT,
  status_raw TEXT,
  cohort_year INTEGER,
  graduation_year INTEGER,
  graduation_raw TEXT,
  kse_last_year INTEGER,
  kse_last_raw TEXT,
  faculty_code TEXT,
  faculty_raw TEXT,
  major_normalized TEXT,
  major_raw TEXT,
  testimonial TEXT,
  source TEXT,
  submitted_at TEXT,
  is_duplicate_suspect INTEGER NOT NULL DEFAULT 0,
  is_listed INTEGER NOT NULL DEFAULT 1,
  hide_requested INTEGER NOT NULL DEFAULT 0,
  self_updated_at TEXT,
  data_quality_flags TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alumni_name ON alumni(name_normalized);
CREATE INDEX IF NOT EXISTS idx_alumni_faculty ON alumni(faculty_code);
CREATE INDEX IF NOT EXISTS idx_alumni_cohort ON alumni(cohort_year);
CREATE INDEX IF NOT EXISTS idx_alumni_status ON alumni(status_code);
CREATE INDEX IF NOT EXISTS idx_alumni_city ON alumni(city);
CREATE INDEX IF NOT EXISTS idx_alumni_email ON alumni(email_normalized);
CREATE INDEX IF NOT EXISTS idx_alumni_phone ON alumni(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_alumni_hide ON alumni(hide_requested);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin', 'alumni')),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('pending', 'active', 'disabled')),
  alumni_id INTEGER REFERENCES alumni(id) ON DELETE SET NULL,
  request_ip TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT,
  row_count INTEGER,
  inserted INTEGER,
  updated INTEGER,
  skipped INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT,
  ip TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_users_alumni ON users(alumni_id);

CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alumni_id INTEGER REFERENCES alumni(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL CHECK(purpose IN ('invite', 'password_reset')),
  payload TEXT,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invites_hash ON invites(token_hash);
CREATE INDEX IF NOT EXISTS idx_invites_alumni ON invites(alumni_id);

CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK(kind IN ('email', 'identity', 'hide', 'reset')),
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_change_requests_status ON change_requests(status);

CREATE TABLE IF NOT EXISTS recovery_codes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL UNIQUE,
  used_at TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recovery_user ON recovery_codes(user_id);

-- Satu baris = satu periode kepengurusan. Jabatan menempel ke periode itu.
CREATE TABLE IF NOT EXISTS alumni_kse_roles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alumni_id INTEGER NOT NULL REFERENCES alumni(id) ON DELETE CASCADE,
  office_code TEXT NOT NULL,
  period_start INTEGER,
  period_end INTEGER,
  period_raw TEXT,
  scope TEXT,
  title_raw TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_roles_alumni ON alumni_kse_roles(alumni_id);
CREATE INDEX IF NOT EXISTS idx_roles_office ON alumni_kse_roles(office_code);
CREATE INDEX IF NOT EXISTS idx_roles_period ON alumni_kse_roles(period_start);
CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_uniq
  ON alumni_kse_roles(alumni_id, office_code, IFNULL(period_start, 0), IFNULL(scope, ''));

CREATE TABLE IF NOT EXISTS kse_office_defs (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  short TEXT NOT NULL,
  kind TEXT NOT NULL,
  unit_code TEXT,
  needs_scope INTEGER NOT NULL DEFAULT 0,
  unspecified INTEGER NOT NULL DEFAULT 0,
  aliases TEXT NOT NULL DEFAULT '[]',
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS org_blueprints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('template', 'period')),
  slug TEXT,
  period_start INTEGER,
  title TEXT NOT NULL,
  notes TEXT,
  copied_from_id INTEGER REFERENCES org_blueprints(id) ON DELETE SET NULL,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_blueprint_slug
  ON org_blueprints(slug) WHERE kind = 'template' AND slug IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_blueprint_period
  ON org_blueprints(period_start) WHERE kind = 'period';

CREATE TABLE IF NOT EXISTS org_units (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  blueprint_id INTEGER NOT NULL REFERENCES org_blueprints(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  unit_kind TEXT NOT NULL CHECK(unit_kind IN ('core', 'division', 'wing', 'pj')),
  title TEXT NOT NULL,
  lead_role TEXT,
  tone TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_visible INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_units_code
  ON org_units(blueprint_id, code);

CREATE TABLE IF NOT EXISTS org_seats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unit_id INTEGER NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  office_code TEXT NOT NULL,
  label TEXT NOT NULL,
  short TEXT NOT NULL,
  seat_kind TEXT NOT NULL CHECK(seat_kind IN ('head', 'officer', 'lead', 'coordinator', 'member', 'pj')),
  pair_group INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  parent_seat_id INTEGER REFERENCES org_seats(id) ON DELETE SET NULL
);
