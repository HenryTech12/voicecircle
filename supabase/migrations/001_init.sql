-- VoiceCircle schema for Supabase Postgres (generated from app/db.py).
-- The API also creates these tables automatically on startup (init_db).
-- Run in Supabase SQL editor or: psql "$DATABASE_URL" -f 001_init.sql

CREATE TABLE IF NOT EXISTS audit_log (
	id SERIAL NOT NULL, 
	circle_id VARCHAR(36), 
	actor_id VARCHAR(64), 
	action VARCHAR(60) NOT NULL, 
	details JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_audit_log_circle_id ON audit_log (circle_id);

CREATE TABLE IF NOT EXISTS processed_webhook_events (
	event_id VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (event_id)
);


CREATE TABLE IF NOT EXISTS users (
	id VARCHAR(64) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	full_name VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS circles (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	owner_id VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id)
);


CREATE TABLE IF NOT EXISTS alerts (
	id VARCHAR(36) NOT NULL, 
	circle_id VARCHAR(36) NOT NULL, 
	type VARCHAR(30) NOT NULL, 
	severity VARCHAR(10) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	message TEXT NOT NULL, 
	source_id VARCHAR(36), 
	acknowledged_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(circle_id) REFERENCES circles (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_alerts_circle_id ON alerts (circle_id);

CREATE TABLE IF NOT EXISTS circle_members (
	id VARCHAR(36) NOT NULL, 
	circle_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(64), 
	role VARCHAR(20) NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	relationship VARCHAR(60), 
	phone_e164 VARCHAR(20), 
	timezone VARCHAR(64) NOT NULL, 
	companion_call_time VARCHAR(5), 
	companion_enabled BOOLEAN NOT NULL, 
	personal_facts JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(circle_id) REFERENCES circles (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_circle_members_user_id ON circle_members (user_id);
CREATE INDEX IF NOT EXISTS ix_circle_members_circle_id ON circle_members (circle_id);

CREATE TABLE IF NOT EXISTS companion_calls (
	id VARCHAR(36) NOT NULL, 
	circle_id VARCHAR(36) NOT NULL, 
	senior_member_id VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	telnyx_call_control_id VARCHAR(200), 
	recall_question TEXT, 
	transcript JSON NOT NULL, 
	summary TEXT, 
	metrics JSON, 
	flags JSON NOT NULL, 
	turns INTEGER NOT NULL, 
	engine_state JSON NOT NULL, 
	duration_seconds INTEGER, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(circle_id) REFERENCES circles (id) ON DELETE CASCADE, 
	FOREIGN KEY(senior_member_id) REFERENCES circle_members (id)
);

CREATE INDEX IF NOT EXISTS ix_companion_calls_circle_id ON companion_calls (circle_id);
CREATE INDEX IF NOT EXISTS ix_companion_calls_telnyx_call_control_id ON companion_calls (telnyx_call_control_id);
CREATE INDEX IF NOT EXISTS ix_companion_calls_senior_member_id ON companion_calls (senior_member_id);

CREATE TABLE IF NOT EXISTS detection_checks (
	id VARCHAR(36) NOT NULL, 
	circle_id VARCHAR(36) NOT NULL, 
	claimed_member_id VARCHAR(36) NOT NULL, 
	audio_path VARCHAR(500), 
	original_filename VARCHAR(300), 
	status VARCHAR(20) NOT NULL, 
	synthetic_score FLOAT, 
	speaker_match_score FLOAT, 
	verdict VARCHAR(20), 
	explanation TEXT, 
	error TEXT, 
	created_by VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(circle_id) REFERENCES circles (id) ON DELETE CASCADE, 
	FOREIGN KEY(claimed_member_id) REFERENCES circle_members (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_detection_checks_circle_id ON detection_checks (circle_id);

CREATE TABLE IF NOT EXISTS practice_calls (
	id VARCHAR(36) NOT NULL, 
	circle_id VARCHAR(36) NOT NULL, 
	senior_member_id VARCHAR(36) NOT NULL, 
	voice_member_id VARCHAR(36) NOT NULL, 
	scenario VARCHAR(60) NOT NULL, 
	difficulty VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	telnyx_call_control_id VARCHAR(200), 
	outcome VARCHAR(30), 
	score INTEGER, 
	feedback JSON, 
	transcript JSON NOT NULL, 
	turns INTEGER NOT NULL, 
	safety_stop BOOLEAN NOT NULL, 
	engine_state JSON NOT NULL, 
	duration_seconds INTEGER, 
	scheduled_for TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	created_by VARCHAR(64), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(circle_id) REFERENCES circles (id) ON DELETE CASCADE, 
	FOREIGN KEY(senior_member_id) REFERENCES circle_members (id), 
	FOREIGN KEY(voice_member_id) REFERENCES circle_members (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS ix_practice_calls_telnyx_call_control_id ON practice_calls (telnyx_call_control_id);
CREATE INDEX IF NOT EXISTS ix_practice_calls_circle_id ON practice_calls (circle_id);

CREATE TABLE IF NOT EXISTS voice_profiles (
	id VARCHAR(36) NOT NULL, 
	member_id VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	sample_path VARCHAR(500), 
	resemble_voice_uuid VARCHAR(100), 
	resemble_identity_id VARCHAR(100), 
	consent_text_version VARCHAR(20) NOT NULL, 
	consent_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (member_id), 
	FOREIGN KEY(member_id) REFERENCES circle_members (id) ON DELETE CASCADE
);


-- Row Level Security: the FastAPI backend connects with the service role and enforces
-- circle membership itself (see app/deps.py). Enable RLS so the anon key can't read tables directly.

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE circles ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE circle_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE companion_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE detection_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_profiles ENABLE ROW LEVEL SECURITY;

-- Private storage buckets for voice samples, uploaded recordings and generated audio
INSERT INTO storage.buckets (id, name, public) VALUES
  ('voice-samples', 'voice-samples', false),
  ('call-audio', 'call-audio', false),
  ('detection-uploads', 'detection-uploads', false)
ON CONFLICT (id) DO NOTHING;
