CREATE TABLE defi4refi.funding_events
(
    `org_id` String,
    `source` String,
    `program` String DEFAULT \'\',
    `amount_usd` Float64 DEFAULT 0,
    `event_date` Date DEFAULT \'1970-01-01\',
    `evidence` String DEFAULT \'\'
)
ENGINE = MergeTree
ORDER BY (org_id, event_date)
SETTINGS index_granularity = 8192
