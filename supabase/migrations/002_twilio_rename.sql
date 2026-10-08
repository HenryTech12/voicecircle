-- Only needed if you already ran an older 001_init.sql (Telnyx version).
-- Renames the call id columns to the provider-neutral name used with Twilio. Safe to run more than once.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'practice_calls' AND column_name = 'telnyx_call_control_id') THEN
    ALTER TABLE practice_calls RENAME COLUMN telnyx_call_control_id TO provider_call_id;
    ALTER INDEX IF EXISTS ix_practice_calls_telnyx_call_control_id RENAME TO ix_practice_calls_provider_call_id;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'companion_calls' AND column_name = 'telnyx_call_control_id') THEN
    ALTER TABLE companion_calls RENAME COLUMN telnyx_call_control_id TO provider_call_id;
    ALTER INDEX IF EXISTS ix_companion_calls_telnyx_call_control_id RENAME TO ix_companion_calls_provider_call_id;
  END IF;
END $$;
