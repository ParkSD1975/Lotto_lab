create table public.user_checkpoints (id uuid default gen_random_uuid() primary key, created_at timestamp with time zone default now() not null, round bigint not null, memo text not null);
