-- task-010 리뷰 반영: max_growth_pct를 소수 둘째 자리까지로 고정한다(API 검증 decimal_places=2와 일치).
-- 기존 check(0~1000)는 그대로 유지된다. 1000.00은 numeric(6,2) 범위(최대 9999.99) 안이다.
alter table public.profiles
  alter column max_growth_pct type numeric(6,2);
