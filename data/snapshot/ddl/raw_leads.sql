CREATE TABLE defi4refi.raw_leads
(
    `source` String,
    `name` String,
    `category` String DEFAULT \'\',
    `raised_usd` Float64 DEFAULT 0,
    `website` String DEFAULT \'\',
    `chain` String DEFAULT \'\',
    `notes` String DEFAULT \'\',
    `priority` String DEFAULT \'\',
    `fetched_at` DateTime DEFAULT now(),
    `org_id` String DEFAULT \'\'
)
ENGINE = MergeTree
ORDER BY (source, name)
SETTINGS index_granularity = 8192
