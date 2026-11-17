-- Módulo Cosechas vs Cobro: tablas y permisos en el proyecto Supabase de Tiempos DAC (prefijo cvc_).
-- Ejecutar una vez en el SQL Editor. Requiere el schema de Tiempos DAC (dac_perfiles, dac_rol, dac_es_sql y el usuario "sistema").
--
-- Los datos NO van en tablas: el proceso de carga sube un archivo por pestaña al bucket privado "cvc" y Supabase
-- entrega a cada perfil solo los archivos que puede ver:
--   admin     (riesgo)   todas las pestañas, descarga, preguntas y administración de usuarios
--   gerencia             todas las pestañas (solo gráficos), descarga y preguntas
--   cobro                Primeros Pagos y Cartera Activa, descarga y preguntas
--   comercial            Primeros Pagos
-- El resumen para la herramienta de preguntas (ia/) solo lo lee la función cvc-preguntar (clave de servicio).

-- ---------- Perfiles ----------
create table if not exists public.cvc_perfiles (
  id uuid primary key references auth.users(id) on delete cascade,
  usuario text not null unique,          -- "carlos.manuel.alvarez.gutierrez" (correo interno usuario@tiemposdac.local)
  nombre text not null,
  rol text not null check (rol in ('admin','gerencia','cobro','comercial')),
  activo boolean not null default true,
  created_at timestamptz not null default now()
);

create or replace function public.cvc_rol() returns text
language sql stable security definer set search_path = public as $$
  select rol from public.cvc_perfiles where id = auth.uid() and activo
$$;

create or replace function public.cvc_es_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(public.cvc_rol() = 'admin', false)
$$;

-- Qué pestañas ve cada perfil (la app y la función de preguntas usan esta misma regla)
create or replace function public.cvc_pestanas(p_rol text) returns text[]
language sql immutable as $$
  select case p_rol
    when 'admin'     then array['cosecha','cartera_activa','primeros_pagos','cono']
    when 'gerencia'  then array['cosecha','cartera_activa','primeros_pagos','cono']
    when 'cobro'     then array['cartera_activa','primeros_pagos']
    when 'comercial' then array['primeros_pagos']
    else array[]::text[] end
$$;

-- Administrador inicial (tomado de Tiempos DAC: entra con la misma contraseña)
insert into public.cvc_perfiles (id, usuario, nombre, rol)
select id, usuario, nombre, 'admin' from public.dac_perfiles where usuario = 'carlos.manuel.alvarez.gutierrez'
on conflict (id) do nothing;

-- ---------- Botón "Actualizar" y estado de la carga ----------
create table if not exists public.cvc_actualizaciones (
  id bigint generated always as identity primary key,
  solicitado_en timestamptz not null default now(),
  solicitado_nombre text,
  estado text not null default 'pendiente' check (estado in ('pendiente','procesando','ok','error')),
  iniciado_en timestamptz,
  terminado_en timestamptz,
  mensaje text
);

create table if not exists public.cvc_config (
  clave text primary key,
  valor jsonb
);

-- Bitácora de la herramienta de preguntas (la escribe la función cvc-preguntar)
create table if not exists public.cvc_preguntas (
  id bigint generated always as identity primary key,
  usuario uuid not null references auth.users(id) on delete cascade,
  creado timestamptz not null default now(),
  pregunta text not null,
  respuesta text,
  tokens_entrada integer,
  tokens_salida integer
);

alter table public.cvc_perfiles enable row level security;
alter table public.cvc_actualizaciones enable row level security;
alter table public.cvc_config enable row level security;
alter table public.cvc_preguntas enable row level security;

drop policy if exists leer on public.cvc_perfiles;
create policy leer on public.cvc_perfiles for select to authenticated using (id = auth.uid() or public.cvc_es_admin());

drop policy if exists leer on public.cvc_config;
create policy leer on public.cvc_config for select to authenticated using (public.cvc_rol() is not null or public.dac_rol() = 'sistema');

drop policy if exists leer on public.cvc_actualizaciones;
create policy leer on public.cvc_actualizaciones for select to authenticated using (public.cvc_rol() is not null or public.dac_rol() = 'sistema');
drop policy if exists pedir on public.cvc_actualizaciones;
create policy pedir on public.cvc_actualizaciones for insert to authenticated
  with check (public.cvc_rol() is not null and estado = 'pendiente' and iniciado_en is null and terminado_en is null and mensaje is null);
-- El proceso de carga registra sus cargas automáticas para que la app sepa que está ocupado
drop policy if exists registrar on public.cvc_actualizaciones;
create policy registrar on public.cvc_actualizaciones for insert to authenticated
  with check (public.dac_rol() = 'sistema');
drop policy if exists atender on public.cvc_actualizaciones;
create policy atender on public.cvc_actualizaciones for update to authenticated
  using (public.dac_rol() = 'sistema') with check (true);

drop policy if exists leer on public.cvc_preguntas;
create policy leer on public.cvc_preguntas for select to authenticated using (usuario = auth.uid() or public.cvc_es_admin());

revoke all on public.cvc_perfiles, public.cvc_actualizaciones, public.cvc_config, public.cvc_preguntas from anon;
grant select on public.cvc_perfiles, public.cvc_actualizaciones, public.cvc_config, public.cvc_preguntas to authenticated;
grant insert, update on public.cvc_actualizaciones to authenticated;

-- El proceso de carga registra la hora, las fechas de cada fuente y los conteos
create or replace function public.cvc_registrar_carga(p_meta jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if coalesce(public.dac_rol(), '') <> 'sistema' then
    raise exception 'Solo el proceso de carga puede registrar una carga';
  end if;
  insert into public.cvc_config (clave, valor) values ('ultima_carga', p_meta)
    on conflict (clave) do update set valor = excluded.valor;
  delete from public.cvc_actualizaciones where solicitado_en < now() - interval '7 days' and estado <> 'pendiente';
end $$;
revoke execute on function public.cvc_registrar_carga(jsonb) from public, anon;
grant execute on function public.cvc_registrar_carga(jsonb) to authenticated;

-- ---------- Archivos (bucket privado "cvc") ----------
insert into storage.buckets (id, name, public) values ('cvc', 'cvc', false)
on conflict (id) do update set public = false;

drop policy if exists cvc_leer on storage.objects;
create policy cvc_leer on storage.objects for select to authenticated using (
  bucket_id = 'cvc' and (
    public.dac_rol() = 'sistema'
    or (name like 'pestanas/%' and split_part(split_part(name, '/', 2), '.', 1) = any (public.cvc_pestanas(public.cvc_rol())))
    or (name like 'descargas/%' and public.cvc_rol() in ('admin','gerencia','cobro'))
  ));
drop policy if exists cvc_subir on storage.objects;
create policy cvc_subir on storage.objects for insert to authenticated
  with check (bucket_id = 'cvc' and public.dac_rol() = 'sistema');
drop policy if exists cvc_reemplazar on storage.objects;
create policy cvc_reemplazar on storage.objects for update to authenticated
  using (bucket_id = 'cvc' and public.dac_rol() = 'sistema') with check (bucket_id = 'cvc');

-- ---------- Administración de usuarios (solo admin) ----------
-- Si la persona ya tiene usuario (Tiempos DAC, Auditores) solo se le da acceso; si no, se crea con la clave dada.
create or replace function public.cvc_crear_usuario(p_usuario text, p_nombre text, p_rol text, p_password text)
returns uuid language plpgsql security definer set search_path = public, extensions as $$
declare uid uuid; u text := lower(trim(p_usuario)); correo text := lower(trim(p_usuario)) || '@tiemposdac.local';
begin
  if not (public.cvc_es_admin() or public.dac_es_sql()) then raise exception 'Solo el administrador puede crear usuarios'; end if;
  if u !~ '^[a-z0-9._-]+$' then raise exception 'Usuario inválido'; end if;
  if p_rol not in ('admin','gerencia','cobro','comercial') then raise exception 'Perfil inválido'; end if;
  if exists (select 1 from public.cvc_perfiles where usuario = u) then raise exception 'Ese usuario ya existe'; end if;
  select id into uid from auth.users where email = correo;
  if uid is null then
    if length(coalesce(p_password, '')) < 8 then raise exception 'La contraseña debe tener al menos 8 caracteres'; end if;
    uid := gen_random_uuid();
    insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
      raw_app_meta_data, raw_user_meta_data, created_at, updated_at, confirmation_token, email_change, email_change_token_new, recovery_token)
    values ('00000000-0000-0000-0000-000000000000', uid, 'authenticated', 'authenticated', correo,
      extensions.crypt(p_password, extensions.gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}', jsonb_build_object('nombre', p_nombre), now(), now(), '', '', '', '');
    insert into auth.identities (provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
    values (uid::text, uid, jsonb_build_object('sub', uid::text, 'email', correo, 'email_verified', true), 'email', now(), now(), now());
  end if;
  insert into public.cvc_perfiles (id, usuario, nombre, rol) values (uid, u, trim(p_nombre), p_rol);
  return uid;
end $$;

create or replace function public.cvc_editar_usuario(p_id uuid, p_rol text, p_activo boolean)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.cvc_es_admin() then raise exception 'Solo el administrador puede editar usuarios'; end if;
  if p_rol not in ('admin','gerencia','cobro','comercial') then raise exception 'Perfil inválido'; end if;
  if p_id = auth.uid() and (p_rol <> 'admin' or not p_activo) then raise exception 'No puede quitarse a sí mismo el rol de administrador'; end if;
  update public.cvc_perfiles set rol = p_rol, activo = p_activo where id = p_id;
end $$;

-- Solo para usuarios exclusivos de este módulo: la clave de quien usa Tiempos DAC o Auditores se administra allá
create or replace function public.cvc_restablecer_clave(p_id uuid, p_password text)
returns void language plpgsql security definer set search_path = public, extensions as $$
begin
  if not public.cvc_es_admin() then raise exception 'Solo el administrador puede restablecer contraseñas'; end if;
  if length(coalesce(p_password, '')) < 8 then raise exception 'La contraseña debe tener al menos 8 caracteres'; end if;
  if exists (select 1 from public.dac_perfiles where id = p_id) or exists (select 1 from public.aud_perfiles where id = p_id) then
    raise exception 'Este usuario también entra a Tiempos DAC o Auditores: su contraseña se restablece allá';
  end if;
  update auth.users set encrypted_password = extensions.crypt(p_password, extensions.gen_salt('bf')), updated_at = now()
  where id = p_id and id in (select id from public.cvc_perfiles);
end $$;

revoke execute on function public.cvc_crear_usuario(text, text, text, text), public.cvc_editar_usuario(uuid, text, boolean),
  public.cvc_restablecer_clave(uuid, text) from public, anon;
grant execute on function public.cvc_crear_usuario(text, text, text, text), public.cvc_editar_usuario(uuid, text, boolean),
  public.cvc_restablecer_clave(uuid, text) to authenticated;

-- Debe mostrar 1 fila: el administrador
select usuario, nombre, rol from public.cvc_perfiles order by rol, nombre;
