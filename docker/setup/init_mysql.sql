-- docker/setup/init_mysql.sql

-- Create the seedcore database if it doesn't exist
CREATE DATABASE IF NOT EXISTS seedcore CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Use the seedcore database
USE seedcore;

-- Create example table
CREATE TABLE IF NOT EXISTS example_table (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create Flashbulb Memory table
CREATE TABLE IF NOT EXISTS flashbulb_incidents (
    incident_id CHAR(36) PRIMARY KEY,
    salience_score FLOAT NOT NULL,
    event_data JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create an index for faster lookups by time
CREATE INDEX idx_flashbulb_created_at ON flashbulb_incidents(created_at);

-- Ensure the seedcore user has proper permissions
-- This will be done automatically by MySQL Docker image, but we can add additional grants if needed
GRANT ALL PRIVILEGES ON seedcore.* TO 'seedcore'@'%';
FLUSH PRIVILEGES;

-- You can add more SQL statements here as needed.
