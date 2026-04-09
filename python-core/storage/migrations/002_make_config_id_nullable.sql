-- Make config_id nullable in sessions table
-- This allows sessions to be created without a valid interview_configs reference
-- Fixes FK constraint error when session_id is used as fallback config_id

ALTER TABLE sessions 
ALTER COLUMN config_id DROP NOT NULL;
