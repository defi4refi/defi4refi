CREATE TABLE defi4refi.orgs
(
    `org_id` String,
    `canonical_name` String,
    `domain` String DEFAULT \'\',
    `github` String DEFAULT \'\',
    `twitter` String DEFAULT \'\',
    `farcaster` String DEFAULT \'\',
    `ens` String DEFAULT \'\',
    `chains` String DEFAULT \'\',
    `source_count` UInt16 DEFAULT 1,
    `sources` String DEFAULT \'\',
    `created_at` DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree
ORDER BY org_id
SETTINGS index_granularity = 8192
