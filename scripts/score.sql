-- defi4refi scoring v3: funding $ + recency + tech-need + regen-fit + institution penalty
CREATE OR REPLACE VIEW defi4refi.v_scored AS
WITH
fe AS (
  SELECT org_id,
         maxIf(event_date, event_date > '1990-01-01') AS last_event,
         countIf(program != 'project-profile' AND program != 'self-reported-raised'
                 AND program != 'token-market-cap' AND program != 'hypercert-sale') AS grant_count,
         sumIf(amount_usd, program != 'token-market-cap') AS funding_usd,
         maxIf(amount_usd, program = 'token-market-cap') AS token_mcap
  FROM defi4refi.funding_events GROUP BY org_id
),
kw AS (
  SELECT m.org_id,
    maxIf(match(concat(r.name,' ',r.notes),
      '(?i)protocol|contract|token|staking|defi|dao|onchain|smart.contract|infra|open.?source|tooling|dapp|governance|indexer|node|bridge'),
      r.source NOT LIKE 'github-topic-%') AS tech_fit,
    maxIf(match(concat(r.name,' ',r.notes),
      '(?i)regen|refi|climat|carbon|forest|reforest|communit|indigen|water|solar|biodiv|ocean|agro|farm|impact|nature|planet|earth|local.currency|ubi|conservation'),
      1) AS regen_fit,
    maxIf(toFloat64(200 - least(toInt32OrZero(extract(r.priority, 'rank-(\\d+)')), 200)) / 200.0,
          r.source = 'artizen-s7' AND extract(r.priority, 'rank-(\\d+)') != '') AS artizen_score,
    maxIf(match(concat(r.name,' ',r.notes),
      '(?i)hackathon|need|hiring|looking for|volunteer|open call|seeking'),
      1) AS hiring_signal
  FROM defi4refi.lead_org_map m JOIN defi4refi.raw_leads r
    ON trim(splitByString('│', r.name)[1]) = m.name AND r.source = m.source
  GROUP BY m.org_id
)
SELECT
  o.org_id AS org_id, o.canonical_name, o.domain, o.twitter, o.github, o.sources, o.source_count,
  fe.last_event, fe.grant_count, fe.funding_usd, fe.token_mcap,
  dateDiff('day', fe.last_event, today()) AS days_since_funded,
  kw.tech_fit, kw.regen_fit, kw.artizen_score, kw.hiring_signal,
  g.public_repos,
  round(
    (if(fe.funding_usd >= 1000000, 30, if(fe.funding_usd >= 250000, 25, if(fe.funding_usd >= 50000, 18,
      if(fe.funding_usd >= 10000, 10, if(fe.funding_usd > 0, 5, 0)))))) +
    (if(fe.token_mcap >= 10000000, 8, if(fe.token_mcap >= 1000000, 5, if(fe.token_mcap > 0, 2, 0)))) +
    (if(days_since_funded <= 90, 20, if(days_since_funded <= 365, 10, if(days_since_funded <= 730, 4, 0)))) +
    (least(fe.grant_count, 5) * 3.0) +
    (kw.tech_fit * 15) +
    (kw.hiring_signal * 5) +
    (kw.regen_fit * 10) +
    (kw.artizen_score * 8) +
    (o.source_count * 3) -
    (if(g.public_repos > 30, 15, 0)) -
    -- institution penalty: mega-orgs self-build, wrong ICP
    (if(match(o.canonical_name, '(?i)university|college|institute of tech|smithsonian|hospital|medical center|national lab|state univ|\buniv\b|\bucsd\b|\bmicrosoft\b|\bintel\b|\bgeneral dynamics\b|\blockheed\b')
        OR fe.funding_usd > 20000000, 22, 0)) -
    -- research-grant-source penalty: NIH/NSF-only funded orgs are research institutes w/ internal staff
    (if(match(o.sources, '(?i)nih-reporter|nsf') AND NOT match(o.sources, '(?i)karma|giveth|artizen|hypercert|coingecko|opencollective'), 14, 0))
  , 2) AS score
FROM defi4refi.orgs o FINAL
LEFT JOIN fe ON fe.org_id = o.org_id
LEFT JOIN kw ON kw.org_id = o.org_id
LEFT JOIN defi4refi.org_github g ON g.org_id = o.org_id
