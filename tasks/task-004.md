# task-004 보안 L1 설정 (/secure setup)

| 항목 | 내용 |
|---|---|
| 웨이브 | W1 |
| 선행 | task-001 |
| 위험도 | 높음 |
| 보안 영향 | 의존성 · 키·권한 |
| 담당 | builder (+ reviewer security) |
| 근거 | `docs/01_PRD.md#8`, `AGENTS.md#4`, `~/.claude/skills/security-baseline/SKILL.md` |
| 쓰기 허용 | `.github/**`, `.gitignore`, `.gitleaks*`, `SECURITY.md`, `.claude/settings.json`(deny 규칙만) |

## 할 것
- `/secure setup` L1 실행: 비밀 스캔(pre-commit·CI), 의존성 취약점·라이선스 점검 워크플로, lockfile 커밋 강제.
- `.gitignore`·에이전트 deny에 `.env*`·Chrome 프로필 경로 추가(저장소 밖 원칙 확인).
- 취약점 처리 기한은 기본값(`vuln-priority.md` 3절).

## 하지 않을 것
- L2(배포 파이프라인) 설정, 실제 비밀 값 생성·커밋.

## 완료 조건 (실행 가능한 확인)
- [ ] `~/.claude/nomad/bin/secscan` 전 항목 통과
- [ ] 더미 비밀 문자열을 넣은 커밋이 스캔에서 차단됨(확인 후 제거)
- [ ] `git ls-files | grep -E "\.env($|\.)"` 가 `.env.example`만 출력
