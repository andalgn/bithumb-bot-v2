#!/usr/bin/env bash
# Discord 채널 플러그인 프록시 자동 복구 스크립트.
#
# Claude Code 재시작이나 플러그인 업데이트 시 프록시 설정이 초기화되면
# 자동으로 감지하고 재적용한다.
#
# 사용:
#   bash scripts/fix_discord_proxy.sh          # 체크 + 필요시 패치
#   bash scripts/fix_discord_proxy.sh --force   # 무조건 패치
#   bash scripts/fix_discord_proxy.sh --check   # 체크만 (수정 안 함)

set -euo pipefail

# ─── 로그 로테이션 (100KB 초과 시 최근 50줄만 유지) ──────
LOG_FILE="${HOME}/projects/bithumb-bot-v2/data/discord_proxy_fix.log"
if [[ -f "$LOG_FILE" ]] && [[ $(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0) -gt 102400 ]]; then
    tail -50 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

PROXY_URL="http://127.0.0.1:1081"
PLUGIN_BASE="$HOME/.claude/plugins"
EXT_DIR="$PLUGIN_BASE/marketplaces/claude-plugins-official/external_plugins/discord"
CACHE_BASE="$PLUGIN_BASE/cache/claude-plugins-official/discord"
BOT_DIR="$HOME/projects/bithumb-bot-v2"
LOG_TAG="[discord-proxy-fix]"

# .env에서 시스템 webhook URL 로드
WEBHOOK_URL=""
if [[ -f "$BOT_DIR/.env" ]]; then
    WEBHOOK_URL=$(grep -oP 'DISCORD_WEBHOOK_SYSTEM=\K.*' "$BOT_DIR/.env" 2>/dev/null || true)
fi

MODE="fix"
if [[ "${1:-}" == "--check" ]]; then
    MODE="check"
elif [[ "${1:-}" == "--force" ]]; then
    MODE="force"
fi

patched=0
issues=()

# ─── 알림 함수 ────────────────────────────────────────────
send_notification() {
    local message="$1"
    echo "$LOG_TAG $message"
    if [[ -n "$WEBHOOK_URL" ]]; then
        curl -sf -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"content\": \"🔧 **Discord 프록시 자동복구**\n${message}\"}" \
            -x "$PROXY_URL" \
            --max-time 10 >/dev/null 2>&1 || true
    fi
}

# ─── .mcp.json 체크/패치 ──────────────────────────────────
check_mcp_json() {
    local dir="$1"
    local file="$dir/.mcp.json"
    if [[ ! -f "$file" ]]; then
        issues+=("$file: 파일 없음")
        return 1
    fi
    if ! grep -q "http_proxy" "$file" 2>/dev/null; then
        issues+=("$file: 프록시 설정 없음")
        return 1
    fi
    return 0
}

patch_mcp_json() {
    local dir="$1"
    local file="$dir/.mcp.json"
    cat > "$file" << 'MCPEOF'
{
  "mcpServers": {
    "discord": {
      "command": "bun",
      "args": ["run", "--cwd", "${CLAUDE_PLUGIN_ROOT}", "--shell=bun", "--silent", "start"],
      "env": {
        "http_proxy": "http://127.0.0.1:1081",
        "https_proxy": "http://127.0.0.1:1081",
        "HTTP_PROXY": "http://127.0.0.1:1081",
        "HTTPS_PROXY": "http://127.0.0.1:1081"
      }
    }
  }
}
MCPEOF
    echo "$LOG_TAG 패치 완료: $file"
    patched=1
}

# ─── package.json 체크/패치 ───────────────────────────────
check_package_json() {
    local dir="$1"
    local file="$dir/package.json"
    if [[ ! -f "$file" ]]; then
        issues+=("$file: 파일 없음")
        return 1
    fi
    if ! grep -q "patch-proxy.cjs" "$file" 2>/dev/null; then
        issues+=("$file: patch-proxy.cjs 누락")
        return 1
    fi
    if ! grep -q "https-proxy-agent" "$file" 2>/dev/null; then
        issues+=("$file: https-proxy-agent 의존성 누락")
        return 1
    fi
    return 0
}

patch_package_json() {
    local dir="$1"
    local file="$dir/package.json"
    cat > "$file" << 'PKGEOF'
{
  "name": "claude-channel-discord",
  "version": "0.0.1",
  "license": "Apache-2.0",
  "type": "module",
  "bin": "./server.ts",
  "scripts": {
    "start": "bun install --no-summary && bun -r ./patch-proxy.cjs server.ts"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0",
    "discord.js": "^14.14.0",
    "https-proxy-agent": "^7.0.0"
  }
}
PKGEOF
    echo "$LOG_TAG 패치 완료: $file"
    patched=1
}

# ─── patch-proxy.cjs 체크/패치 ────────────────────────────
check_patch_proxy() {
    local dir="$1"
    local file="$dir/patch-proxy.cjs"
    if [[ ! -f "$file" ]]; then
        issues+=("$file: 파일 없음")
        return 1
    fi
    return 0
}

patch_patch_proxy() {
    local dir="$1"
    local file="$dir/patch-proxy.cjs"
    cat > "$file" << 'PATCHEOF'
/**
 * WebSocket Gateway 프록시 패치.
 *
 * bun 환경에서 @discordjs/ws는 globalThis.WebSocket(bun 네이티브)을 사용하는데,
 * bun 네이티브 WebSocket은 프록시를 지원하지 않는다.
 * 해결: globalThis.WebSocket을 프록시 agent가 주입된 ws 모듈로 교체한다.
 */
const { HttpsProxyAgent } = require('https-proxy-agent');

const proxyUrl = process.env.https_proxy || process.env.HTTPS_PROXY;
if (proxyUrl) {
  const agent = new HttpsProxyAgent(proxyUrl);
  const WS = require('ws');
  const OrigWS = WS.WebSocket || WS;

  const PatchedWS = function PatchedWebSocket(url, protocols, opts) {
    if (typeof protocols === 'object' && !Array.isArray(protocols)) {
      opts = protocols;
      protocols = undefined;
    }
    opts = Object.assign({}, opts, { agent });
    if (protocols) {
      return new OrigWS(url, protocols, opts);
    }
    return new OrigWS(url, opts);
  };
  PatchedWS.prototype = OrigWS.prototype;
  Object.assign(PatchedWS, OrigWS);

  // ws 모듈 캐시 패치
  if (WS.WebSocket) {
    WS.WebSocket = PatchedWS;
  }
  require.cache[require.resolve('ws')] = {
    id: require.resolve('ws'),
    filename: require.resolve('ws'),
    loaded: true,
    exports: PatchedWS,
  };

  // 핵심: bun에서 @discordjs/ws가 globalThis.WebSocket을 사용하므로
  // globalThis.WebSocket을 프록시된 ws 모듈로 교체한다.
  // W3C WebSocket API와 호환되도록 래핑.
  const W3CCompatWS = function WebSocket(url, protocols) {
    const ws = protocols
      ? new OrigWS(url, protocols, { agent })
      : new OrigWS(url, { agent });
    return ws;
  };
  W3CCompatWS.prototype = OrigWS.prototype;
  W3CCompatWS.CONNECTING = 0;
  W3CCompatWS.OPEN = 1;
  W3CCompatWS.CLOSING = 2;
  W3CCompatWS.CLOSED = 3;
  globalThis.WebSocket = W3CCompatWS;

  process.stderr.write('discord channel: ws + globalThis.WebSocket proxy patched\n');
}
PATCHEOF
    echo "$LOG_TAG 패치 완료: $file"
    patched=1
}

# ─── server.ts ProxyAgent 체크/패치 ──────────────────────
check_server_ts() {
    local dir="$1"
    local file="$dir/server.ts"
    if [[ ! -f "$file" ]]; then
        issues+=("$file: 파일 없음")
        return 1
    fi
    if ! grep -q "ProxyAgent" "$file" 2>/dev/null; then
        issues+=("$file: REST ProxyAgent 패치 없음")
        return 1
    fi
    return 0
}

patch_server_ts() {
    local dir="$1"
    local file="$dir/server.ts"
    if [[ ! -f "$file" ]]; then
        echo "$LOG_TAG server.ts 없음, 스킵: $dir"
        return
    fi
    # 이미 패치되어 있으면 스킵
    if grep -q "ProxyAgent" "$file" 2>/dev/null; then
        return
    fi
    python3 - "$file" << 'PYEOF'
import sys

with open(sys.argv[1], 'r') as f:
    content = f.read()

if 'ProxyAgent' in content:
    print("server.ts 이미 패치됨")
    sys.exit(0)

# 1) import 추가: join, sep from 'path' 줄 뒤에
old_import = "import { join, sep } from 'path'"
new_import = "import { join, sep } from 'path'\nimport { ProxyAgent } from 'undici'"
content = content.replace(old_import, new_import, 1)

# 2) Client 생성 앞에 proxyUrl/proxyAgent 선언
old_client = "const client = new Client({"
new_client = (
    "const proxyUrl = process.env.https_proxy || process.env.HTTPS_PROXY || ''\n"
    "const proxyAgent = proxyUrl ? new ProxyAgent(proxyUrl) : undefined\n\n"
    "const client = new Client({"
)
content = content.replace(old_client, new_client, 1)

# 3) partials 닫는 줄 뒤에 rest 옵션
old_partials = "  partials: [Partials.Channel],\n})"
new_partials = "  partials: [Partials.Channel],\n  ...(proxyAgent ? { rest: { agent: proxyAgent } } : {}),\n})"
content = content.replace(old_partials, new_partials, 1)

with open(sys.argv[1], 'w') as f:
    f.write(content)
print("server.ts REST proxy 패치 완료")
PYEOF
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        echo "$LOG_TAG 패치 완료: $file"
        patched=1
    else
        echo "$LOG_TAG 패치 실패: $file"
    fi
}

# ─── skip-worktree 보호 체크/적용 ─────────────────────────
check_skip_worktree() {
    local repo_dir="$PLUGIN_BASE/marketplaces/claude-plugins-official"
    if [[ ! -d "$repo_dir/.git" ]]; then
        return 0  # git repo 아니면 스킵
    fi
    local flags
    flags=$(cd "$repo_dir" && git ls-files -v external_plugins/discord/.mcp.json 2>/dev/null || true)
    if [[ "$flags" != S* ]]; then
        issues+=("skip-worktree: .mcp.json 보호 안 됨")
        return 1
    fi
    return 0
}

apply_skip_worktree() {
    local repo_dir="$PLUGIN_BASE/marketplaces/claude-plugins-official"
    if [[ ! -d "$repo_dir/.git" ]]; then
        return
    fi
    cd "$repo_dir"
    for f in external_plugins/discord/.mcp.json external_plugins/discord/package.json external_plugins/discord/server.ts; do
        git update-index --skip-worktree "$f" 2>/dev/null || true
    done
    cd "$BOT_DIR"
    echo "$LOG_TAG skip-worktree 보호 재적용"
    patched=1
}

# ─── 디렉토리 단위 체크/패치 ──────────────────────────────
process_dir() {
    local dir="$1"
    local name="$2"
    local needs_patch=0

    if [[ ! -d "$dir" ]]; then
        echo "$LOG_TAG $name: 디렉토리 없음, 스킵"
        return
    fi

    if [[ "$MODE" == "force" ]]; then
        needs_patch=1
    else
        check_mcp_json "$dir" || needs_patch=1
        check_package_json "$dir" || needs_patch=1
        check_patch_proxy "$dir" || needs_patch=1
        check_server_ts "$dir" || needs_patch=1
    fi

    if [[ $needs_patch -eq 1 ]]; then
        if [[ "$MODE" == "check" ]]; then
            echo "$LOG_TAG $name: 패치 필요"
        else
            echo "$LOG_TAG $name: 패치 적용 중..."
            patch_mcp_json "$dir"
            patch_package_json "$dir"
            patch_patch_proxy "$dir"
            patch_server_ts "$dir"
        fi
    else
        echo "$LOG_TAG $name: 정상"
    fi
}

# ─── 메인 ────────────────────────────────────────────────
echo "$LOG_TAG 시작 (모드: $MODE)"

# 1) external_plugins 체크/패치
process_dir "$EXT_DIR" "external_plugins"

# 2) 모든 cache 버전 체크/패치
if [[ -d "$CACHE_BASE" ]]; then
    for version_dir in "$CACHE_BASE"/*/; do
        if [[ -d "$version_dir" ]]; then
            version=$(basename "$version_dir")
            process_dir "$version_dir" "cache/$version"
        fi
    done
fi

# 3) skip-worktree 보호
if [[ "$MODE" != "check" ]]; then
    check_skip_worktree || apply_skip_worktree
fi

# 4) 결과 보고
if [[ ${#issues[@]} -gt 0 ]]; then
    issue_text=$(printf '• %s\n' "${issues[@]}")
    if [[ "$MODE" == "check" ]]; then
        echo "$LOG_TAG 문제 발견:"
        echo "$issue_text"
        exit 1
    elif [[ $patched -eq 1 ]]; then
        send_notification "프록시 설정 복구 완료.\n문제:\n${issue_text}"
    fi
else
    echo "$LOG_TAG 모든 항목 정상"
fi

echo "$LOG_TAG 완료"
