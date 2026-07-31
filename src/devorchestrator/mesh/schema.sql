-- Supabase schema for DevOrchestrator mesh
-- Run this in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Requires: pgcrypto extension (enabled by default in new Supabase projects).

-- Events: every action the pipeline produces.
create table if not exists public.events (
    id         uuid primary key default gen_random_uuid(),
    -- Scopes every row to one repo. The tables are shared by everything
    -- pointing at this Supabase instance, so without it two projects that both
    -- have a module named 'cli.py' see each other as a conflict.
    project    text not null default '',
    dev        text not null default 'unknown',
    module     text not null,
    event_type text not null,
    payload    jsonb not null default '{}'::jsonb,
    ts         timestamptz not null default now()
);

-- Indexes for the queries SupabaseMesh runs.
create index if not exists idx_events_project_module_ts
    on public.events (project, module, ts desc);

create index if not exists idx_events_project_type_ts
    on public.events (project, event_type, ts desc);

-- Devs: who is on the team (for the dashboard).
create table if not exists public.devs (
    project   text not null default '',
    name      text not null,
    role      text not null default 'dev',
    last_seen timestamptz not null default now(),
    primary key (project, name)
);

-- Sessions: agent session lifecycle state, keyed by dev + branch + kind.
-- Written by the session-emit issue (upsert on conflict) and read by the
-- live dashboard (active_sessions / session_history).
create table if not exists public.sessions (
    project     text not null default '',
    dev         text not null,
    branch      text not null,
    kind        text not null,                       -- research | impl | autofix
    state       text not null default 'running',  -- running|pending|completed|failed|timeout
    last_seen   timestamptz not null default now(),
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    payload     jsonb not null default '{}'::jsonb,
    primary key (project, dev, branch, kind)
);

create index if not exists idx_sessions_project_last_seen
    on public.sessions (project, last_seen desc);

create index if not exists idx_sessions_state_last_seen
    on public.sessions (state, last_seen desc);

-- Enable Row Level Security (optional — disable for single-team projects).
alter table public.events enable row level security;
alter table public.devs enable row level security;
alter table public.sessions enable row level security;

-- Allow service_role (your backend) full access.
-- These policies let the anon key read/write; tighten in production.
create policy "service_role all events"
    on public.events
    for all
    to service_role
    using (true)
    with check (true);

create policy "service_role all devs"
    on public.devs
    for all
    to service_role
    using (true)
    with check (true);

create policy "service_role all sessions"
    on public.sessions
    for all
    to service_role
    using (true)
    with check (true);

-- ---------------------------------------------------------------------------
-- Migrating an instance created before project scoping
-- ---------------------------------------------------------------------------
-- Existing rows have no project and are invisible to a scoped client. Either
-- backfill them with the repo they came from (owner/repo, matching
-- Config.project_key) and adopt the new key, or drop them if they were only
-- ever test data.
--
--   alter table public.events   add column if not exists project text not null default '';
--   alter table public.devs     add column if not exists project text not null default '';
--   alter table public.sessions add column if not exists project text not null default '';
--   update public.events   set project = 'OWNER/REPO' where project = '';
--   update public.devs     set project = 'OWNER/REPO' where project = '';
--   update public.sessions set project = 'OWNER/REPO' where project = '';
--   alter table public.devs drop constraint devs_pkey;
--   alter table public.devs add primary key (project, name);
--   alter table public.sessions drop constraint sessions_pkey;
--   alter table public.sessions add primary key (project, dev, branch, kind);

