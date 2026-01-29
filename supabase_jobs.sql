create table if not exists public.extraction_jobs (
  id uuid primary key,
  created_at timestamptz default now(),
  started_at timestamptz,
  completed_at timestamptz,
  status text not null,
  file_paths jsonb not null,
  output_path text,
  error text
);

create index if not exists extraction_jobs_status_created_at_idx
  on public.extraction_jobs (status, created_at);
