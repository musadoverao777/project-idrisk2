-- IDRISK2 — Fechar as ligações "quem submeteu / originou" -> users
-- A base do Supabase JÁ existe com dados, por isso adicionamos as foreign keys
-- via ALTER. Correr UMA vez em: Supabase -> SQL Editor -> New query -> Run.
--
-- Passo 1: garantir que cada valor já gravado em submitted_by / user_id existe
--          como users.id (utilizadores de sistema/legados).
-- Passo 2: adicionar as foreign keys.

-- 1a) Dar um id estável ao utilizador 'web_inspector' (usado pelas classificações novas)
update users set id = 'web_inspector'
 where username = 'web_inspector' and id <> 'web_inspector';

-- 1b) Criar utilizadores de sistema/legados para os identificadores existentes
insert into users (id, username, email, role, status, created_at) values
  ('web-inspector', 'web-inspector (legacy)', null, 'inspector', 'inactive', '2026-01-01'),
  ('u001',          'u001 (legacy)',          null, 'inspector', 'inactive', '2026-01-01'),
  ('eval_runner',   'eval_runner (system)',   null, 'inspector', 'active',   '2026-01-01'),
  ('test_probe',    'test_probe (system)',    null, 'inspector', 'inactive', '2026-01-01')
on conflict (id) do nothing;

-- 2) Adicionar as foreign keys em falta
alter table classifications
  add constraint fk_classifications_user
  foreign key (submitted_by) references users(id);

alter table audit_logs
  add constraint fk_audit_user
  foreign key (user_id) references users(id);
