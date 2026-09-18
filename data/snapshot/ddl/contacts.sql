CREATE TABLE defi4refi.contacts
(
    `org_id` String,
    `channel` String,
    `value` String,
    `verified` UInt8 DEFAULT 0,
    `source` String DEFAULT \'\',
    `captured_at` DateTime DEFAULT now(),
    `evidence_url` String,
    `person_name` String,
    `person_title` String,
    `is_role_addr` UInt8,
    `is_catchall` UInt8,
    `bounce_flag` UInt8,
    `affiliation_match` UInt8,
    `seniority_score` UInt8
)
ENGINE = MergeTree
ORDER BY (org_id, channel)
SETTINGS index_granularity = 8192
