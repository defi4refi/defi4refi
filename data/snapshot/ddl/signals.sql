CREATE TABLE defi4refi.signals
(
    `org_id` String,
    `signal_type` String,
    `detected_at` DateTime DEFAULT now(),
    `detail` String DEFAULT \'\',
    `routed` UInt8 DEFAULT 0
)
ENGINE = MergeTree
ORDER BY detected_at
SETTINGS index_granularity = 8192
