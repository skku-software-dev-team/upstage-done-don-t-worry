.PHONY: up down db-dump db-restore db-reset

up:
	docker compose up --build -d

down:
	docker compose down

# 현재 DB 데이터를 파일로 덤프 (파싱 후 팀 공유용)
# 사용: make db-dump → db/fixtures.sql 생성 후 git commit & push
db-dump:
	docker compose exec db pg_dump -U upstage --data-only --no-privileges compliance > db/fixtures.sql
	@echo "Done: db/fixtures.sql — git add db/fixtures.sql && git push"

# 팀원이 최신 데이터 받아오기 (git pull 후 실행)
# 사용: make db-restore
db-restore:
	docker compose exec -T db psql -U upstage -d compliance -c \
		"TRUNCATE documents, laws CASCADE;"
	docker compose exec -T db psql -U upstage -d compliance < db/fixtures.sql
	@echo "Done: DB synced from db/fixtures.sql"

# 볼륨 완전 초기화 (스키마 + 카테고리 시드만 남김)
db-reset:
	docker compose down -v
	docker compose up -d db
	@echo "Done: fresh DB with schema + category seeds"
