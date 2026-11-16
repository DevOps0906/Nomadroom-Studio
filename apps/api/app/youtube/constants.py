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
