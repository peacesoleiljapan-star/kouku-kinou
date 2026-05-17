#!/bin/sh

set -eu

DEPLOY_REPO_DIR="${DEPLOY_REPO_DIR:-/volume1/docker/kouku-kinou}"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REMOTE="${DEPLOY_REMOTE:-origin}"
DEPLOY_SERVICE_NAME="${DEPLOY_SERVICE_NAME:-kouku-kinou}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:8010/api/health}"
DEPLOY_FORCE_REBUILD="${DEPLOY_FORCE_REBUILD:-0}"

find_executable() {
    for candidate in "$@"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

DOCKER_BIN="$(find_executable "$(command -v docker 2>/dev/null || true)" /usr/local/bin/docker /usr/bin/docker /var/packages/ContainerManager/target/usr/bin/docker /var/packages/Docker/target/usr/bin/docker || true)"
DOCKER_COMPOSE_BIN="$(find_executable "$(command -v docker-compose 2>/dev/null || true)" /usr/local/bin/docker-compose /usr/bin/docker-compose /var/packages/ContainerManager/target/usr/bin/docker-compose /var/packages/Docker/target/usr/bin/docker-compose || true)"

docker_cmd() {
    if [ -z "$DOCKER_BIN" ]; then
        echo "docker command not found" >&2
        exit 1
    fi

    if [ "$(id -u)" -eq 0 ]; then
        "$DOCKER_BIN" "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo -n "$DOCKER_BIN" "$@"
        return
    fi

    echo "docker requires root or passwordless sudo" >&2
    exit 1
}

compose() {
    if [ -n "$DOCKER_BIN" ] && docker_cmd compose version >/dev/null 2>&1; then
        docker_cmd compose "$@"
        return
    fi

    if [ -n "$DOCKER_COMPOSE_BIN" ]; then
        if [ "$(id -u)" -eq 0 ]; then
            "$DOCKER_COMPOSE_BIN" "$@"
            return
        fi

        if command -v sudo >/dev/null 2>&1; then
            sudo -n "$DOCKER_COMPOSE_BIN" "$@"
            return
        fi

        echo "docker-compose requires root or passwordless sudo" >&2
        return
    fi

    echo "docker compose command not found" >&2
    exit 1
}

container_running() {
    state="$(docker_cmd inspect -f '{{.State.Running}}' "$DEPLOY_SERVICE_NAME" 2>/dev/null || true)"
    [ "$state" = "true" ]
}

probe_health_once() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "$DEPLOY_HEALTH_URL" >/dev/null 2>&1
        return
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q -O /dev/null "$DEPLOY_HEALTH_URL" >/dev/null 2>&1
        return
    fi

    docker_cmd exec "$DEPLOY_SERVICE_NAME" python -c "import urllib.request; urllib.request.urlopen('$DEPLOY_HEALTH_URL', timeout=5).read()" >/dev/null 2>&1
}

wait_for_health() {
    attempt=0
    while [ "$attempt" -lt 30 ]; do
        if probe_health_once; then
            echo "Health check passed: $DEPLOY_HEALTH_URL"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done

    echo "Health check failed: $DEPLOY_HEALTH_URL" >&2
    return 1
}

ensure_repo_checkout() {
    if [ -d "$DEPLOY_REPO_DIR/.git" ]; then
        return
    fi

    if [ -e "$DEPLOY_REPO_DIR" ] && [ ! -d "$DEPLOY_REPO_DIR/.git" ]; then
        echo "Deployment directory exists but is not a git working tree: $DEPLOY_REPO_DIR" >&2
        exit 1
    fi

    if [ -z "$DEPLOY_REPO_URL" ]; then
        echo "Repository directory not found and DEPLOY_REPO_URL is empty: $DEPLOY_REPO_DIR" >&2
        exit 1
    fi

    parent_dir="$(dirname "$DEPLOY_REPO_DIR")"
    mkdir -p "$parent_dir"
    echo "Cloning repository into $DEPLOY_REPO_DIR"
    git clone --branch "$DEPLOY_BRANCH" --single-branch "$DEPLOY_REPO_URL" "$DEPLOY_REPO_DIR"
}

ensure_repo_checkout

cd "$DEPLOY_REPO_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git working tree: $DEPLOY_REPO_DIR" >&2
    exit 1
fi

if [ -n "$DEPLOY_REPO_URL" ]; then
    current_remote_url="$(git remote get-url "$DEPLOY_REMOTE" 2>/dev/null || true)"
    if [ -z "$current_remote_url" ]; then
        git remote add "$DEPLOY_REMOTE" "$DEPLOY_REPO_URL"
    elif [ "$current_remote_url" != "$DEPLOY_REPO_URL" ]; then
        git remote set-url "$DEPLOY_REMOTE" "$DEPLOY_REPO_URL"
    fi
fi

tracked_changes="$(git status --porcelain --untracked-files=no)"
if [ -n "$tracked_changes" ]; then
    echo "Tracked local changes exist on Synology. Deployment aborted." >&2
    echo "$tracked_changes" >&2
    exit 1
fi

git fetch "$DEPLOY_REMOTE" "$DEPLOY_BRANCH" --prune

target_ref="$DEPLOY_REMOTE/$DEPLOY_BRANCH"
current_head="$(git rev-parse HEAD)"
target_head="$(git rev-parse "$target_ref")"
changed_files=""

if [ "$current_head" != "$target_head" ]; then
    changed_files="$(git diff --name-only "$current_head" "$target_head")"
    echo "Changed files:"
    printf '%s\n' "$changed_files"
fi

git checkout -B "$DEPLOY_BRANCH" "$target_ref" >/dev/null 2>&1

needs_rebuild=0
if [ "$DEPLOY_FORCE_REBUILD" = "1" ] || [ "$DEPLOY_FORCE_REBUILD" = "true" ]; then
    needs_rebuild=1
elif printf '%s\n' "$changed_files" | grep -Eq '^(Dockerfile|compose\.yaml|server\.py)$'; then
    needs_rebuild=1
elif ! container_running; then
    needs_rebuild=1
fi

if [ "$needs_rebuild" -eq 1 ]; then
    echo "Running docker compose up --build -d"
    compose up --build -d
else
    echo "Hot-swappable files only. Skipping image rebuild."
fi

echo "Deployed commit: $(git rev-parse --short HEAD)"
wait_for_health