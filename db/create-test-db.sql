-- Runs once when the local Postgres container is first created.
-- The integration tests use (and wipe) this separate database.
CREATE DATABASE hff_test OWNER hff;
