-- task-002: 브라우저 역할(anon·authenticated)의 쓰기 권한 제거
-- 쓰기는 API(service_role)만. anon은 조회도 없음. workers는 authenticated 조회도 없음(permission denied).

revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
revoke select on all tables in schema public from anon;
revoke select on public.workers from authenticated;
