# Bithumb Bot v2 — Windows 서비스 등록 (nssm)
# 사용법: PowerShell에서 관리자 권한으로 실행
# 사전 요구: nssm이 PATH에 있어야 함 (https://nssm.cc)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = "$ProjectRoot\venv\Scripts\python.exe"
$RunBot = "$ProjectRoot\run_bot.py"
$ServiceName = "BithumbBot"

Write-Host "프로젝트 루트: $ProjectRoot"
Write-Host "Python: $PythonExe"

# 기존 서비스 제거 (있으면)
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "기존 서비스 제거 중..."
    nssm stop $ServiceName
    nssm remove $ServiceName confirm
}

# 서비스 설치
Write-Host "서비스 설치 중..."
nssm install $ServiceName $PythonExe $RunBot
nssm set $ServiceName AppDirectory $ProjectRoot
nssm set $ServiceName AppStdout "$ProjectRoot\data\bot_stdout.log"
nssm set $ServiceName AppStderr "$ProjectRoot\data\bot_stderr.log"
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName AppRestartDelay 5000
nssm set $ServiceName Description "Bithumb Auto Trading Bot v2"

# 서비스 시작
Write-Host "서비스 시작 중..."
nssm start $ServiceName

Write-Host "완료. 상태 확인: nssm status $ServiceName"
