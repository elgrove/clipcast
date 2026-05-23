# Dev loop: backend on 9907, frontend on 9906.
# Production runs in docker on 8906; this stack is fully isolated.

DEV_DB    := $(CURDIR)/data/dev.sqlite3
DEV_PODS  := $(CURDIR)/_podcasts_dev
BACKEND_PORT  := 9907
FRONTEND_PORT := 9906

.PHONY: dev dev-backend dev-frontend dev-reset

dev:
	@mkdir -p $(dir $(DEV_DB)) $(DEV_PODS)
	@echo ">> backend  http://localhost:$(BACKEND_PORT)  (db: $(DEV_DB))"
	@echo ">> frontend http://localhost:$(FRONTEND_PORT)"
	@trap 'kill 0' INT TERM EXIT; \
	  ( $(MAKE) -s dev-backend  2>&1 | sed -u 's/^/[backend]  /' ) & \
	  ( $(MAKE) -s dev-frontend 2>&1 | sed -u 's/^/[frontend] /' ) & \
	  wait

dev-backend:
	@cd backend && \
	  DATABASE_PATH=$(DEV_DB) \
	  PODCASTS_DIR=$(DEV_PODS) \
	  DEBUG=true \
	  ALLOWED_ORIGINS='["http://localhost:$(FRONTEND_PORT)"]' \
	  uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

dev-frontend:
	@cd frontend && \
	  DEV_BACKEND_URL=http://localhost:$(BACKEND_PORT) \
	  npm run dev -- --port $(FRONTEND_PORT) --strictPort

dev-reset:
	rm -f $(DEV_DB) $(DEV_DB)-shm $(DEV_DB)-wal
	rm -rf $(DEV_PODS)
	@echo "dev db and podcasts dir wiped"
