main="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
[ -f backend/.env ] || cp "$main/backend/.env" backend/.env
[ -f .env ] || printf 'COMPOSE_FILE=%s/docker-compose.yml\n' "$main" > .env
if [ -f "$main/.vscode/.dev_seed_ids.json" ] && [ ! -f .vscode/.dev_seed_ids.json ]; then
  mkdir -p .vscode && cp "$main/.vscode/.dev_seed_ids.json" .vscode/
fi
(cd backend && uv sync) && (cd frontend && pnpm install)
