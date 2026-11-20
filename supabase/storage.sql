-- 食記照片的儲存空間（Supabase Storage）
-- 用法：先執行 schema.sql，再到 SQL Editor 貼上這份 → Run。可以重複執行。
-- 照片路徑一律是「使用者 id/檔名.jpg」，每個人只能上傳、刪除自己資料夾裡的照片。

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('meal-photos', 'meal-photos', true, 1048576, array['image/jpeg', 'image/webp'])
on conflict (id) do update set public = true, file_size_limit = 1048576,
  allowed_mime_types = array['image/jpeg', 'image/webp'];

drop policy if exists "meal photos upload own folder" on storage.objects;
create policy "meal photos upload own folder" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'meal-photos' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "meal photos delete own" on storage.objects;
create policy "meal photos delete own" on storage.objects
  for delete to authenticated
  using (bucket_id = 'meal-photos' and (storage.foldername(name))[1] = auth.uid()::text);
