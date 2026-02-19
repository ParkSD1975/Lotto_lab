-- AI Prediction Table for LSTM Model Results
create table if not exists public.ai_predictions (
  id uuid default gen_random_uuid() primary key,
  round integer not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  
  -- Stores the probability (0.0 - 1.0) for each number (1-45)
  -- Structure: { "1": 0.02, "2": 0.15, ... "45": 0.01 }
  probabilities jsonb not null,
  
  -- Metadata about the model used
  model_version text default 'v1.0',
  
  -- Ensure only one prediction per round per model version
  unique(round, model_version)
);

-- Turn off RLS for easier access (since this is a personal project)
alter table public.ai_predictions disable row level security;
