-- Schema for the MariaDB side of the bulk-load benchmark.
-- Column names are kept identical to the FairCom table so both databases load
-- the exact same dataset. Avoids reserved words (no `timestamp`, no `value`).

DROP TABLE IF EXISTS sensor_readings;

CREATE TABLE sensor_readings (
    id          BIGINT       NOT NULL PRIMARY KEY,
    device_id   VARCHAR(32)  NOT NULL,
    metric      VARCHAR(32)  NOT NULL,
    reading     DOUBLE       NOT NULL,
    recorded_at VARCHAR(32)  NOT NULL,
    status      VARCHAR(16)  NOT NULL
);
