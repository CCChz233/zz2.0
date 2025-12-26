-- Daily agent report cache (allow multiple rows per date)
create table if not exists agent_daily_report_cache (
  id bigserial primary key,
  cache_date date not null,
  generated_at timestamptz not null,
  source text,
  sections jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_agent_daily_report_cache_cache_date
  on agent_daily_report_cache (cache_date desc);

create index if not exists idx_agent_daily_report_cache_generated_at
  on agent_daily_report_cache (generated_at desc);

create index if not exists idx_agent_daily_report_cache_updated_at
  on agent_daily_report_cache (updated_at desc);

-- If you already have the old schema (cache_date as primary key),
-- run a migration like:
--   alter table agent_daily_report_cache drop constraint agent_daily_report_cache_pkey;
--   alter table agent_daily_report_cache add column if not exists id bigserial;
--   update agent_daily_report_cache set id = nextval('agent_daily_report_cache_id_seq') where id is null;
--   alter table agent_daily_report_cache alter column id set not null;
--   alter table agent_daily_report_cache add primary key (id);

-- Web search cache (query-level, TTL via expires_at)
create table if not exists agent_web_search_cache (
  id bigserial primary key,
  query_hash text not null,
  query text not null,
  results jsonb not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create index if not exists idx_agent_web_search_cache_hash
  on agent_web_search_cache (query_hash);

create index if not exists idx_agent_web_search_cache_expires
  on agent_web_search_cache (expires_at);
