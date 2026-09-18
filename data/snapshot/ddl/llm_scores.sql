CREATE TABLE defi4refi.llm_scores
(
    `org_id` String,
    `regen_fit` Float32,
    `dev_need` Float32,
    `disposable_estimate` Float32,
    `reason` String,
    `scored_at` DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY org_id
SETTINGS index_granularity = 8192
