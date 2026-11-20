-- Table / 席間 V1 社群資料庫（Supabase / Postgres）
-- 用法：Supabase 後台 → SQL Editor → 貼上整份 → Run。可以重複執行。
-- 登入方式：匿名登入（Authentication 要開啟 Allow anonymous sign-ins），不需要信箱。
--
-- 設計原則
--   1. 每一筆社群資料都帶 circle_id；V1 只有「台大」一個圈子，所有人都在裡面。
--   2. App 只透過下面的函式（RPC）讀寫，資料表本身不開放直接存取。
--   3. 函式一律用 auth.uid() 認人，前端送來的使用者 id 一概不信。

create extension if not exists pgcrypto;

-- ============ 資料表 ============
create table if not exists circles (
  id            serial primary key,
  slug          text unique not null,
  name          text not null,
  email_domains text[] not null default '{}'
);
insert into circles (slug, name, email_domains)
values ('ntu', '台大', array['ntu.edu.tw', 'g.ntu.edu.tw'])
on conflict (slug) do nothing;

-- 例外名單：組員用非台大信箱測試時加在這裡
create table if not exists allowed_emails (
  email     text primary key,
  circle_id int not null references circles(id)
);

create table if not exists profiles (
  id           uuid primary key,                 -- = auth.users.id
  circle_id    int  not null references circles(id),
  display_name text not null check (char_length(display_name) between 1 and 20),
  dept         text not null default '' check (char_length(dept) <= 20),
  title        text not null default '' check (char_length(title) <= 30),
  tribe        text not null default '',
  created_at   timestamptz not null default now()
);

create table if not exists boosts (
  id              bigserial primary key,
  circle_id       int  not null references circles(id),
  user_id         uuid not null references profiles(id) on delete cascade,
  restaurant_id   text not null,
  restaurant_name text not null,
  area            text not null default '',
  day             date not null default (now() at time zone 'Asia/Taipei')::date,
  weight          int  not null default 1,
  created_at      timestamptz not null default now(),
  unique (user_id, restaurant_id, day)           -- 同一人同一店一天一次
);

create table if not exists posts (
  id              bigserial primary key,
  circle_id       int  not null references circles(id),
  user_id         uuid not null references profiles(id) on delete cascade,
  restaurant_id   text not null default '',
  restaurant_name text not null check (char_length(restaurant_name) between 1 and 40),
  area            text not null default '',
  note            text not null default '' check (char_length(note) <= 300),
  tags            text[] not null default '{}',
  photo_path      text not null default '',
  created_at      timestamptz not null default now()
);

create table if not exists reactions (
  post_id    bigint not null references posts(id) on delete cascade,
  user_id    uuid   not null references profiles(id) on delete cascade,
  kind       text   not null default 'cheer' check (kind in ('cheer')),
  created_at timestamptz not null default now(),
  primary key (post_id, user_id, kind)
);

create table if not exists meetups (
  id              bigserial primary key,
  circle_id       int  not null references circles(id),
  host_id         uuid not null references profiles(id) on delete cascade,
  kind            text not null check (kind in ('meal', 'radar')),
  restaurant_id   text not null default '',
  restaurant_name text not null check (char_length(restaurant_name) between 1 and 40),
  area            text not null default '',
  starts_at       timestamptz not null,
  expires_at      timestamptz not null,
  capacity        int  not null check (capacity between 2 and 6),
  theme           text not null default '' check (char_length(theme) <= 40),
  status          text not null default 'open' check (status in ('open', 'cancelled')),
  created_at      timestamptz not null default now()
);

create table if not exists meetup_members (
  meetup_id bigint not null references meetups(id) on delete cascade,
  user_id   uuid   not null references profiles(id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (meetup_id, user_id)
);

create table if not exists activities (
  id              bigserial primary key,
  circle_id       int  not null references circles(id),
  actor_id        uuid not null references profiles(id) on delete cascade,
  verb            text not null check (verb in ('boost', 'post', 'meetup', 'radar', 'title')),
  restaurant_id   text not null default '',
  restaurant_name text not null default '',
  area            text not null default '',
  ref_id          bigint,
  extra           text not null default '',
  created_at      timestamptz not null default now()
);
create index if not exists activities_feed on activities (circle_id, id desc);

create table if not exists reports (
  id          bigserial primary key,
  reporter_id uuid not null references profiles(id) on delete cascade,
  target_type text not null check (target_type in ('user', 'post', 'meetup')),
  target_id   text not null,
  reason      text not null default '' check (char_length(reason) <= 300),
  created_at  timestamptz not null default now()
);

create table if not exists blocks (
  blocker_id uuid not null references profiles(id) on delete cascade,
  blocked_id uuid not null references profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_id, blocked_id)
);

-- 資料表只能透過函式存取
do $$
declare t text;
begin
  foreach t in array array['circles','allowed_emails','profiles','boosts','posts','reactions',
                           'meetups','meetup_members','activities','reports','blocks'] loop
    execute format('alter table %I enable row level security', t);
    execute format('revoke all on %I from anon, authenticated', t);
  end loop;
end $$;

-- ============ 小工具 ============
create or replace function circle_for_email(p_email text) returns int
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select circle_id from allowed_emails where email = lower(p_email)),
    (select id from circles c where lower(split_part(p_email, '@', 2)) = any (c.email_domains) limit 1)
  );
$$;

-- 舊版的「只限台大信箱」檢查已取消（改用匿名登入）；重複執行時順便移除
drop trigger if exists table_email_check on auth.users;
drop function if exists block_outside_emails();

create or replace function my_circle() returns int
language plpgsql stable security definer set search_path = public as $$
declare c int;
begin
  select circle_id into c from profiles where id = auth.uid();
  if c is null then raise exception 'NO_PROFILE'; end if;
  return c;
end $$;

create or replace function is_blocked_between(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from blocks
                 where (blocker_id = a and blocked_id = b) or (blocker_id = b and blocked_id = a));
$$;

-- ============ 帳號 ============
create or replace function me() returns json
language sql stable security definer set search_path = public as $$
  select json_build_object('id', p.id, 'display_name', p.display_name, 'dept', p.dept,
                           'title', p.title, 'tribe', p.tribe, 'circle', c.name)
  from profiles p join circles c on c.id = p.circle_id where p.id = auth.uid();
$$;

create or replace function setup_profile(p_name text, p_dept text default '') returns json
language plpgsql security definer set search_path = public as $$
declare v_email text; v_circle int;
begin
  if auth.uid() is null then raise exception 'NOT_LOGGED_IN'; end if;
  if char_length(trim(coalesce(p_name, ''))) = 0 then raise exception 'NAME_REQUIRED'; end if;
  -- V1：所有人都加入「台大」圈子（有信箱且符合其他圈子時才分過去，留給未來擴張）
  select email into v_email from auth.users where id = auth.uid();
  v_circle := coalesce(circle_for_email(coalesce(v_email, '')), (select id from circles where slug = 'ntu'));
  insert into profiles (id, circle_id, display_name, dept)
  values (auth.uid(), v_circle, trim(p_name), trim(coalesce(p_dept, '')))
  on conflict (id) do update set display_name = excluded.display_name, dept = excluded.dept;
  return me();
end $$;

create or replace function set_title(p_title text, p_tribe text) returns json
language plpgsql security definer set search_path = public as $$
declare c int := my_circle();
begin
  update profiles set title = p_title, tribe = p_tribe where id = auth.uid();
  insert into activities (circle_id, actor_id, verb, extra) values (c, auth.uid(), 'title', p_title);
  return me();
end $$;

-- 刪除自己的所有社群資料（個資最少化：使用者隨時可以走）
create or replace function delete_my_data() returns void
language sql security definer set search_path = public as $$
  delete from profiles where id = auth.uid();
$$;

-- ============ 助力與排行榜 ============
create or replace function boost(p_restaurant_id text, p_name text, p_area text default '') returns json
language plpgsql security definer set search_path = public as $$
declare c int := my_circle(); new_id bigint;
begin
  insert into boosts (circle_id, user_id, restaurant_id, restaurant_name, area)
  values (c, auth.uid(), p_restaurant_id, p_name, coalesce(p_area, ''))
  on conflict (user_id, restaurant_id, day) do nothing
  returning id into new_id;
  if new_id is not null then
    insert into activities (circle_id, actor_id, verb, restaurant_id, restaurant_name, area)
    values (c, auth.uid(), 'boost', p_restaurant_id, p_name, coalesce(p_area, ''));
  end if;
  return json_build_object('new', new_id is not null);
end $$;

create or replace function my_boosts_today() returns text[]
language sql stable security definer set search_path = public as $$
  select coalesce(array_agg(restaurant_id), '{}') from boosts
  where user_id = auth.uid() and day = (now() at time zone 'Asia/Taipei')::date;
$$;

-- p_days = 0 → 全部期間
create or replace function leaderboard(p_days int default 7, p_limit int default 20)
returns table (restaurant_id text, restaurant_name text, area text, score bigint, boosters bigint)
language sql stable security definer set search_path = public as $$
  select b.restaurant_id, max(b.restaurant_name), max(b.area), sum(b.weight), count(distinct b.user_id)
  from boosts b
  where b.circle_id = my_circle()
    and (p_days = 0 or b.day > (now() at time zone 'Asia/Taipei')::date - p_days)
  group by b.restaurant_id
  order by sum(b.weight) desc, count(distinct b.user_id) desc, max(b.created_at) desc
  limit least(greatest(p_limit, 1), 100);
$$;

-- ============ 食記分享與同感 ============
create or replace function share_post(p_restaurant_id text, p_name text, p_area text, p_note text,
                                      p_tags text[] default '{}', p_photo text default '') returns bigint
language plpgsql security definer set search_path = public as $$
declare c int := my_circle(); pid bigint;
begin
  if p_photo <> '' and split_part(p_photo, '/', 1) <> auth.uid()::text then
    raise exception 'BAD_PHOTO_PATH';
  end if;
  insert into posts (circle_id, user_id, restaurant_id, restaurant_name, area, note, tags, photo_path)
  values (c, auth.uid(), coalesce(p_restaurant_id, ''), p_name, coalesce(p_area, ''),
          coalesce(p_note, ''), coalesce(p_tags[1:4], '{}'), coalesce(p_photo, ''))
  returning id into pid;
  insert into activities (circle_id, actor_id, verb, restaurant_id, restaurant_name, area, ref_id)
  values (c, auth.uid(), 'post', coalesce(p_restaurant_id, ''), p_name, coalesce(p_area, ''), pid);
  return pid;
end $$;

create or replace function toggle_cheer(p_post bigint) returns boolean
language plpgsql security definer set search_path = public as $$
declare c int := my_circle();
begin
  if not exists (select 1 from posts where id = p_post and circle_id = c) then
    raise exception 'NOT_FOUND';
  end if;
  delete from reactions where post_id = p_post and user_id = auth.uid() and kind = 'cheer';
  if found then return false; end if;
  insert into reactions (post_id, user_id) values (p_post, auth.uid());
  return true;
end $$;

-- ============ 動態流 ============
create or replace function feed(p_limit int default 40, p_before bigint default null)
returns table (id bigint, verb text, created_at timestamptz, actor_id uuid, actor_name text,
               actor_dept text, actor_title text, restaurant_id text, restaurant_name text,
               area text, extra text, ref_id bigint, note text, tags text[], photo_path text,
               cheered boolean, cheer_names text[], meetup json, mine boolean)
language sql stable security definer set search_path = public as $$
  select a.id, a.verb, a.created_at, a.actor_id, p.display_name, p.dept, p.title,
         a.restaurant_id, a.restaurant_name, a.area, a.extra, a.ref_id,
         coalesce(po.note, ''), coalesce(po.tags, '{}'), coalesce(po.photo_path, ''),
         exists (select 1 from reactions r where r.post_id = po.id and r.user_id = auth.uid()),
         coalesce((select array_agg(pp.display_name order by r.created_at)
                   from (select * from reactions r2 where r2.post_id = po.id
                         and r2.user_id <> auth.uid() order by r2.created_at limit 2) r
                   join profiles pp on pp.id = r.user_id), '{}'),
         case when m.id is null then null else json_build_object(
           'id', m.id, 'kind', m.kind, 'starts_at', m.starts_at, 'expires_at', m.expires_at,
           'capacity', m.capacity, 'theme', m.theme, 'status', m.status,
           'count', (select count(*) from meetup_members mm where mm.meetup_id = m.id),
           'joined', exists (select 1 from meetup_members mm where mm.meetup_id = m.id and mm.user_id = auth.uid()))
         end,
         a.actor_id = auth.uid()
  from activities a
  join profiles p on p.id = a.actor_id
  left join posts po on a.verb = 'post' and po.id = a.ref_id
  left join meetups m on a.verb in ('meetup', 'radar') and m.id = a.ref_id
  where a.circle_id = my_circle()
    and (p_before is null or a.id < p_before)
    and not is_blocked_between(auth.uid(), a.actor_id)
    and (a.verb <> 'post' or po.id is not null)
    and (a.verb not in ('meetup', 'radar') or (m.status = 'open' and m.expires_at > now()))
  order by a.id desc
  limit least(greatest(p_limit, 1), 100);
$$;

-- ============ 吃飯組局與雷達 ============
create or replace function create_meetup(p_restaurant_id text, p_name text, p_area text,
                                         p_starts_at timestamptz, p_capacity int, p_theme text,
                                         p_radar boolean default false) returns bigint
language plpgsql security definer set search_path = public as $$
declare c int := my_circle(); mid bigint; s timestamptz; e timestamptz;
begin
  if (select count(*) from meetups where host_id = auth.uid() and status = 'open' and expires_at > now()) >= 3 then
    raise exception 'TOO_MANY_OPEN';
  end if;
  if p_radar then
    s := now(); e := now() + interval '1 hour';
  else
    if p_starts_at < now() - interval '10 minutes' or p_starts_at > now() + interval '14 days' then
      raise exception 'BAD_TIME';
    end if;
    s := p_starts_at; e := p_starts_at + interval '2 hours';
  end if;
  insert into meetups (circle_id, host_id, kind, restaurant_id, restaurant_name, area,
                       starts_at, expires_at, capacity, theme)
  values (c, auth.uid(), case when p_radar then 'radar' else 'meal' end, coalesce(p_restaurant_id, ''),
          p_name, coalesce(p_area, ''), s, e, p_capacity, coalesce(p_theme, ''))
  returning id into mid;
  insert into meetup_members (meetup_id, user_id) values (mid, auth.uid());
  insert into activities (circle_id, actor_id, verb, restaurant_id, restaurant_name, area, ref_id, extra)
  values (c, auth.uid(), case when p_radar then 'radar' else 'meetup' end, coalesce(p_restaurant_id, ''),
          p_name, coalesce(p_area, ''), mid, coalesce(p_theme, ''));
  return mid;
end $$;

create or replace function join_meetup(p_id bigint) returns json
language plpgsql security definer set search_path = public as $$
declare c int := my_circle(); m meetups%rowtype; n int;
begin
  select * into m from meetups where id = p_id and circle_id = c for update;
  if m.id is null then return json_build_object('ok', false, 'reason', '找不到這個飯局'); end if;
  if m.status <> 'open' or m.expires_at <= now() then
    return json_build_object('ok', false, 'reason', '這個飯局已經結束了');
  end if;
  if exists (select 1 from meetup_members mm where mm.meetup_id = p_id and is_blocked_between(auth.uid(), mm.user_id)) then
    return json_build_object('ok', false, 'reason', '無法加入這個飯局');
  end if;
  if exists (select 1 from meetup_members where meetup_id = p_id and user_id = auth.uid()) then
    return json_build_object('ok', true, 'reason', '');
  end if;
  select count(*) into n from meetup_members where meetup_id = p_id;
  if n >= m.capacity then return json_build_object('ok', false, 'reason', '人數已滿'); end if;
  insert into meetup_members (meetup_id, user_id) values (p_id, auth.uid());
  return json_build_object('ok', true, 'reason', '');
end $$;

create or replace function leave_meetup(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
begin
  if exists (select 1 from meetups where id = p_id and host_id = auth.uid()) then
    update meetups set status = 'cancelled' where id = p_id;   -- 主揪離開 = 取消
  else
    delete from meetup_members where meetup_id = p_id and user_id = auth.uid();
  end if;
end $$;

-- 列出圈子裡還沒結束的飯局，含「和我的共同點」
create or replace function open_meetups()
returns table (id bigint, kind text, host_id uuid, host_name text, restaurant_id text,
               restaurant_name text, area text, starts_at timestamptz, expires_at timestamptz,
               capacity int, theme text, member_names text[], joined boolean, mine boolean,
               shared_places text[], same_dept int)
language sql stable security definer set search_path = public as $$
  select m.id, m.kind, m.host_id, h.display_name, m.restaurant_id, m.restaurant_name, m.area,
         m.starts_at, m.expires_at, m.capacity, m.theme,
         (select array_agg(p.display_name order by mm.joined_at) from meetup_members mm
            join profiles p on p.id = mm.user_id where mm.meetup_id = m.id),
         exists (select 1 from meetup_members mm where mm.meetup_id = m.id and mm.user_id = auth.uid()),
         m.host_id = auth.uid(),
         coalesce((select array_agg(distinct x.restaurant_name) from (
             select b.restaurant_name from boosts b
             where b.user_id = auth.uid()
               and b.restaurant_id in (select b2.restaurant_id from boosts b2
                                       join meetup_members mm on mm.user_id = b2.user_id
                                       where mm.meetup_id = m.id and b2.user_id <> auth.uid())
             limit 3) x), '{}'),
         (select count(*)::int from meetup_members mm join profiles p on p.id = mm.user_id
            where mm.meetup_id = m.id and p.id <> auth.uid() and p.dept <> ''
              and p.dept = (select dept from profiles where id = auth.uid()))
  from meetups m join profiles h on h.id = m.host_id
  where m.circle_id = my_circle() and m.status = 'open' and m.expires_at > now()
    and not is_blocked_between(auth.uid(), m.host_id)
  order by m.kind = 'radar' desc, m.starts_at;
$$;

-- 飯局成員（只有成員看得到完整名單，給破冰字卡用）
create or replace function meetup_members_of(p_id bigint)
returns table (user_id uuid, display_name text, dept text, title text, tribe text)
language sql stable security definer set search_path = public as $$
  select p.id, p.display_name, p.dept, p.title, p.tribe
  from meetup_members mm join profiles p on p.id = mm.user_id
  where mm.meetup_id = p_id
    and exists (select 1 from meetup_members me where me.meetup_id = p_id and me.user_id = auth.uid())
  order by mm.joined_at;
$$;

-- ============ 檢舉與封鎖 ============
create or replace function report(p_type text, p_target text, p_reason text) returns void
language sql security definer set search_path = public as $$
  insert into reports (reporter_id, target_type, target_id, reason)
  select auth.uid(), p_type, p_target, coalesce(p_reason, '') where my_circle() is not null;
$$;

create or replace function block_user(p_user uuid) returns void
language sql security definer set search_path = public as $$
  insert into blocks (blocker_id, blocked_id)
  select auth.uid(), p_user where p_user <> auth.uid() and my_circle() is not null
  on conflict do nothing;
$$;

-- ============ 權限：函式只給登入的人用 ============
do $$
declare f text;
begin
  foreach f in array array[
    'me()', 'setup_profile(text, text)', 'set_title(text, text)', 'delete_my_data()',
    'boost(text, text, text)', 'my_boosts_today()', 'leaderboard(int, int)',
    'share_post(text, text, text, text, text[], text)', 'toggle_cheer(bigint)',
    'feed(int, bigint)', 'create_meetup(text, text, text, timestamptz, int, text, boolean)',
    'join_meetup(bigint)', 'leave_meetup(bigint)', 'open_meetups()', 'meetup_members_of(bigint)',
    'report(text, text, text)', 'block_user(uuid)'] loop
    execute format('revoke all on function %s from public, anon', f);
    execute format('grant execute on function %s to authenticated', f);
  end loop;
  foreach f in array array['circle_for_email(text)', 'my_circle()', 'is_blocked_between(uuid, uuid)'] loop
    execute format('revoke all on function %s from public, anon, authenticated', f);
  end loop;
end $$;
