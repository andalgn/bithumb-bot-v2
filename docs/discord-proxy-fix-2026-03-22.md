# Discord 채널 플러그인 프록시 문제 해결 기록 (2026-03-22)

## 증상
- Claude Code 재시작 후 Discord 봇이 오프라인 상태 유지
- 3시간 이상 반복 재시작해도 동일 증상
- 재시작 직전까지는 정상 작동했음

## 근본 원인

Claude Code의 Discord 플러그인은 **두 개의 디렉토리**에 존재한다:

| 경로 | 역할 |
|------|------|
| `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/discord/` | **원본 (git repo)** — Claude Code가 재시작 시 여기서 로드 |
| `~/.claude/plugins/cache/claude-plugins-official/discord/0.0.1/` | **캐시** — 런타임 실행용 복사본 |

이전 수정은 `cache/`에만 적용했다. Claude Code 재시작 시:
1. 마켓플레이스 git repo를 `pull`하여 `external_plugins/` 원본이 복원됨
2. 원본(프록시 설정 없음)이 `cache/`를 덮어쓰거나, `external_plugins/`에서 직접 실행됨
3. 프록시 없이 Discord API 연결 시도 → 중국 네트워크에서 차단 → 봇 오프라인

## 수정한 내용 (external_plugins/ + cache/ 양쪽)

### 1. `.mcp.json` — 프록시 env 추가
```json
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
```

### 2. `package.json` — 의존성 + 패치 스크립트 추가
```json
{
  "scripts": {
    "start": "bun install --no-summary && node patch-proxy.cjs && bun server.ts"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0",
    "discord.js": "^14.14.0",
    "https-proxy-agent": "^8.0.0"
  }
}
```
변경점: `https-proxy-agent` 의존성 추가, start 스크립트에 `node patch-proxy.cjs` 추가

### 3. `server.ts` — REST API 프록시 코드 삽입
`const client = new Client({...})` 직전에 삽입:
```ts
// Proxy support for REST API (undici)
const _restProxyUrl = process.env.https_proxy || process.env.HTTPS_PROXY || process.env.http_proxy || process.env.HTTP_PROXY
let _restOptions: Record<string, unknown> = {}
if (_restProxyUrl) {
  try {
    const { ProxyAgent } = await import('undici')
    _restOptions = { agent: new ProxyAgent(_restProxyUrl) }
    process.stderr.write(`discord channel: REST routing through proxy ${_restProxyUrl}\n`)
  } catch (e) {
    process.stderr.write(`discord channel: failed to set REST proxy: ${e}\n`)
  }
}

const client = new Client({
  ...,
  rest: _restOptions,  // ← 이것 추가
})
```

### 4. `patch-proxy.cjs` — WebSocket 프록시 패치 (새 파일)
`@discordjs/ws/dist/index.js`의 WebSocket 생성자를 `HttpsProxyAgent` 경유하도록 런타임 패치.
- 파일명 `.cjs` 필수: `package.json`의 `"type": "module"` 때문에 `.js`면 ESM으로 처리되어 `require()` 실패
- `bun install` 후 `bun server.ts` 전에 실행되어야 함

### 5. git skip-worktree 보호
```bash
cd ~/.claude/plugins/marketplaces/claude-plugins-official
git update-index --skip-worktree external_plugins/discord/.mcp.json
git update-index --skip-worktree external_plugins/discord/package.json
git update-index --skip-worktree external_plugins/discord/server.ts
```
`git pull`로 원본 복원 방지. `patch-proxy.cjs`는 untracked 파일이라 보호 불필요.

## 검증 완료 사항
- ✅ 프록시 연결: `curl -x http://127.0.0.1:1081 https://discord.com/api/v10/gateway` → HTTP 200
- ✅ 수동 서버 실행: REST 프록시 정상, WebSocket 게이트웨이 연결 성공 (`bithumb-bot#3887`)
- ✅ 토큰: `~/.claude/channels/discord/.env`에 `DISCORD_BOT_TOKEN` 존재
- ✅ 플러그인 활성화: `~/.claude/settings.json` → `enabledPlugins.discord@claude-plugins-official: true`
- ✅ skip-worktree: `git ls-files -v`에서 `S` 플래그 확인

## 재시작 후에도 안 된다면

### 체크 1: skip-worktree가 유지되는지
```bash
cd ~/.claude/plugins/marketplaces/claude-plugins-official
git ls-files -v external_plugins/discord/
# S = 보호됨, H = 보호 안 됨 (원본 복원 위험)
```

### 체크 2: external_plugins 파일에 프록시 설정이 남아있는지
```bash
grep "proxy" ~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/discord/.mcp.json
# 출력 없으면 → 원본으로 리셋된 것
```

### 체크 3: MCP 서버 프로세스가 뜨는지
```bash
ps aux | grep -E "bun.*server.ts|bun.*discord" | grep -v grep
# 출력 없으면 → Claude Code가 MCP 서버 스폰에 실패한 것
```

### 체크 4: Claude Code가 플러그인 디렉토리를 완전 삭제 후 재생성하는지
```bash
ls -la ~/.claude/plugins/cache/claude-plugins-official/discord/0.0.1/patch-proxy.cjs
# 파일 없으면 → 캐시가 초기화된 것. external_plugins가 올바르면 자동 복구됨
```

### 체크 5: git reset --hard가 실행되는지
skip-worktree는 `git reset --hard`에도 보호되지만, Claude Code가 디렉토리 자체를 삭제 후 `git clone`하면 보호 무효.
이 경우 근본적으로 다른 접근 필요:
- `~/.claude/settings.json`에서 MCP 서버 env를 직접 설정하는 방법 검토
- 또는 Discord 봇을 systemd 독립 서비스로 분리
