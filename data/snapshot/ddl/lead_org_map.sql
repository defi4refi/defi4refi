CREATE TABLE defi4refi.lead_org_map
(
    `name` String,
    `source` String,
    `org_id` String
)
ENGINE = MergeTree
ORDER BY org_id
SETTINGS index_granularity = 8192
