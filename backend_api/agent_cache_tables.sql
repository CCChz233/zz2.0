-- Daily agent report cache (one row per date)
create table if not exists agent_daily_report_cache (
  cache_date date primary key,
  generated_at timestamptz not null,
  source text,
  sections jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_agent_daily_report_cache_updated_at
  on agent_daily_report_cache (updated_at desc);

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
