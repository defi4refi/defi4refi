-- outreach_queue: scored + contactable + not-contacted + not-suppressed
CREATE TABLE IF NOT EXISTS defi4refi.outreach_log (
  org_id String, channel String, value String, sent_at DateTime, status String DEFAULT 'sent'
) ENGINE = MergeTree ORDER BY sent_at;

CREATE TABLE IF NOT EXISTS defi4refi.suppression (
  org_id String, reason String, added_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY org_id;

CREATE OR REPLACE VIEW defi4refi.outreach_queue AS
WITH agg AS (
  SELECT org_id,
         groupArray(concat(channel,':',value)) AS verified_contacts,
         count() AS total_contacts
  FROM defi4refi.contacts GROUP BY org_id
)
SELECT
  v.`org_id` AS org_id, v.canonical_name, v.domain, v.score, v.funding_usd,
  v.days_since_funded, v.sources,
  agg.verified_contacts, agg.total_contacts
FROM defi4refi.v_scored v
JOIN agg ON agg.org_id = v.`org_id`
WHERE v.score >= 35
  AND v.`org_id` NOT IN (SELECT org_id FROM defi4refi.outreach_log)
  AND v.`org_id` NOT IN (SELECT org_id FROM defi4refi.suppression)
ORDER BY v.score DESC;

-- queue depth check (run by governor): queue must stay >= 3x weekly batch
-- SELECT count() FROM defi4refi.outreach_queue
