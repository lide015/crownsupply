-- Investment Finance Knowledge Universe MVP
-- 來源：Google Drive「LIDE」資料夾內 investment-knowledge-universe-schema.sql，原樣保留於此存檔。
-- 已實際部署到 Supabase 專案 investment-knowledge-universe（見同層 README.md）。

create extension if not exists "pgcrypto";

create type knowledge_category as enum (
  'technical',
  'fundamental',
  'chips',
  'sentiment',
  'macro'
);

create type learning_status as enum (
  'locked',
  'available',
  'learning',
  'completed'
);

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default 'Alpha Learner',
  level integer not null default 1 check (level > 0),
  xp integer not null default 0 check (xp >= 0),
  next_level_xp integer not null default 1000 check (next_level_xp > 0),
  rank text not null default 'Neural Investor',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.knowledge_nodes (
  id text primary key,
  title text not null,
  category knowledge_category not null,
  category_label text not null,
  level_requirement integer not null default 1 check (level_requirement > 0),
  unlock_status learning_status not null default 'locked',
  xp_reward integer not null default 0 check (xp_reward >= 0),
  description text not null,
  principle text not null,
  case_study text not null,
  common_mistakes text[] not null default '{}',
  position_x numeric not null default 0,
  position_y numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.knowledge_edges (
  id text primary key,
  source_node_id text not null references public.knowledge_nodes(id) on delete cascade,
  target_node_id text not null references public.knowledge_nodes(id) on delete cascade,
  relationship_label text,
  created_at timestamptz not null default now(),
  constraint no_self_edge check (source_node_id <> target_node_id)
);

create table if not exists public.user_node_progress (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  node_id text not null references public.knowledge_nodes(id) on delete cascade,
  status learning_status not null default 'available',
  earned_xp integer not null default 0 check (earned_xp >= 0),
  completed_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, node_id)
);

create table if not exists public.missions (
  id text primary key,
  title text not null,
  description text not null,
  node_id text references public.knowledge_nodes(id) on delete set null,
  category knowledge_category not null,
  reward_xp integer not null default 0 check (reward_xp >= 0),
  difficulty text not null default 'normal',
  created_at timestamptz not null default now()
);

create table if not exists public.user_mission_progress (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  mission_id text not null references public.missions(id) on delete cascade,
  is_completed boolean not null default false,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, mission_id)
);

create table if not exists public.ai_coach_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade,
  selected_node_id text references public.knowledge_nodes(id) on delete set null,
  user_question text not null,
  ai_answer text not null,
  weakness_analysis text,
  next_mission_id text references public.missions(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.trading_journal_entries (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade,
  product_name text not null,
  entry_reason text not null,
  exit_reason text,
  stop_loss text,
  take_profit text,
  result text,
  ai_feedback text,
  related_node_ids text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists knowledge_nodes_category_idx on public.knowledge_nodes(category);
create index if not exists knowledge_edges_source_idx on public.knowledge_edges(source_node_id);
create index if not exists knowledge_edges_target_idx on public.knowledge_edges(target_node_id);
create index if not exists missions_category_idx on public.missions(category);
create index if not exists trading_journal_user_idx on public.trading_journal_entries(user_id);

alter table public.profiles enable row level security;
alter table public.user_node_progress enable row level security;
alter table public.user_mission_progress enable row level security;
alter table public.ai_coach_sessions enable row level security;
alter table public.trading_journal_entries enable row level security;

create policy "profiles are self readable"
on public.profiles for select
using (auth.uid() = id);

create policy "profiles are self editable"
on public.profiles for update
using (auth.uid() = id);

create policy "node progress belongs to user"
on public.user_node_progress for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "mission progress belongs to user"
on public.user_mission_progress for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "coach sessions belong to user"
on public.ai_coach_sessions for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "trading journal belongs to user"
on public.trading_journal_entries for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

-- Knowledge graph and missions can be public read-only content in the MVP.
alter table public.knowledge_nodes enable row level security;
alter table public.knowledge_edges enable row level security;
alter table public.missions enable row level security;

create policy "knowledge nodes are public readable"
on public.knowledge_nodes for select
using (true);

create policy "knowledge edges are public readable"
on public.knowledge_edges for select
using (true);

create policy "missions are public readable"
on public.missions for select
using (true);
