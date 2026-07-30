-- Supabase schema for DevOrchestrator mesh
-- Run this in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Requires: pgcrypto extension (enabled by default in new Supabase projects).

-- Events: every action the pipeline produces.
create table if not exists public.events (
    id         uuid primary key default gen_random_uuid(),
    dev        text not null default 'unknown',
    module     text not null,
    event_type text not null,
    payload    jsonb not null default '{}'::jsonb,
    ts         timestamptz not null default now()
);

-- Indexes for the queries SupabaseMesh runs.
create index if not exists idx_events_module_ts
    on public.events (module, ts desc);

create index if not exists idx_events_type_ts
    on public.events (event_type, ts desc);

-- Devs: who is on the team (for the dashboard).
create table if not exists public.devs (
    name      text primary key,
    role      text not null default 'dev',
    last_seen timestamptz not null default now()
);

-- Enable Row Level Security (optional — disable for single-team projects).
alter table public.events enable row level security;
alter table public.devs enable row level security;

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
