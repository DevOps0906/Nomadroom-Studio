"""YouTube 관측·할당량 상수. 근거: docs/adr/0002-observation-quota.md, tasks/task-006.md#구현 결정.

단가·한도는 공식 문서 기준 가정이다(`미확인`, Google Cloud 콘솔에서 재확인 필요).
"""

from datetime import timedelta

VIDEOS_LIST_UNITS = 1  # videos.list 1회 단가(unit)
DAILY_UNIT_LIMIT = 8_000  # 방어선: 기본 일 한도 10,000의 80%
BATCH_SIZE = 50  # videos.list id 묶음 상한
MAX_CANDIDATES = 200  # 실행당 후보 상한(01_PRD.md#7 Q3)
STALE_JOB_AFTER = timedelta(minutes=10)  # 이보다 오래된 queued·running verify job은 정리
RATE_LIMIT_WINDOW = timedelta(seconds=60)  # 직전 verify job 생성 후 새 키 POST 금지 구간

# 후보 검색(task-019, ADR 0002 2026-11-17 결정). 단가·상한은 `미확인`(콘솔 재확인 필요).
SEARCH_UNITS = 100  # 검색 1회 단가(unit)
SEARCH_DAILY_UNIT_LIMIT = 2_000  # 검색 전용 일 상한(서버 공용, 전체 방어선 8,000 안)
SEARCH_MAX_RESULTS = 50  # 프로필당 검색 결과 상한(maxResults)
SHORTS_MAX_SECONDS = 180  # 실측 길이가 이 값 이하면 short
# 처리 시간 상한(웹은 60초로 기다림): 검색 job 실행 전체 마감 40초 + 앞뒤 DB 호출(정상 수백 ms)로
# 50초 안. YouTube 호출 1회는 총 6초 안(프로필 3개 × 검색·videos.list 2회 = 최악 36초 < 40초).
YOUTUBE_CALL_TIMEOUT_SECONDS = 6.0
SEARCH_RUN_DEADLINE_SECONDS = 40.0
SEARCH_STALE_AFTER = timedelta(
    minutes=5
)  # 이보다 오래 running인 검색 job은 서버 중단으로 보고 실패
