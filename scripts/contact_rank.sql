-- contact_rank: per-contact score -> per-org primary contact
CREATE OR REPLACE VIEW defi4refi.contact_rank AS
SELECT org_id, channel, value, verified, source,
       person_name, person_title,
       round(
         -- deliverable beats guessed
         verified * 30 +
         -- named person beats org channel; seniority titles rank highest
         (if(person_name != '',
            if(match(person_title, '(?i)founder|director|ceo|cto|coo|president|executive|head|chief|principal|pi|program|board'), 25, 15), 0)) +
         -- channel tier: agent-autonomous + verified-email first
         (if(channel = 'email' AND verified = 1, 20,
             if(channel IN ('bluesky','mastodon','farcaster','nostr','matrix'), 15,
             if(channel = 'github', 12,
             if(channel = 'email', 10,
             if(channel IN ('telegram','discord'), 8,
             if(channel IN ('form','biolink','substack'), 5, 3))))))) +
         -- person channel itself carries a reachable name even without direct handle
         (if(channel = 'person', 8, 0)) -
         -- generic inbox penalty
         is_role_addr * 5 -
         -- bounce/catchall demote
         bounce_flag * 20 - is_catchall * 10
       , 2) AS contact_score,
       captured_at
FROM defi4refi.contacts;

-- primary contact per org = argMax(contact_score)
CREATE OR REPLACE VIEW defi4refi.org_primary_contact AS
SELECT org_id,
       argMax(value, contact_score) AS best_value,
       argMax(channel, contact_score) AS best_channel,
       argMax(person_name, contact_score) AS best_person,
       max(contact_score) AS best_score,
       count() AS total_contacts
FROM defi4refi.contact_rank
GROUP BY org_id;
