-- Runs once, when the postgres volume is first created.
-- A separate database for the test suite (TEST_DATABASE_URL), so tests never touch the app's data.
CREATE DATABASE drivenow_test;
