# Windows 定时任务安装脚本
# 从 .knowledge-iteration-system.json 的 automation 配置读取：
#   - dailyIntervalDays: 1/2/3/4（0/空 表示不安装）
#   - dailyRunAtHour: 每天/每 N 天在几点跑
#   - dailyScanDays: 每次扫描最近多少天
# 用法：
#   .\install_automation.ps1
#   .\install_automation.ps1 -DryRun
#   .\install_automation.ps1 -Interval 3
#   .\install_automation.ps1 -Uninstall
# 需要在 Windows 上以“可注册计划任务”的账户运行。

param(
    [switch]$Uninstall,
    [switch]$DryRun,
    [int]$Interval = 0
)

$TaskName = "KnowledgeIterationDaily"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VaultDir = Split-Path -Parent $ScriptDir
$RunAllPy = Join-Path $ScriptDir "run_all.py"

# 检测 Python（需 3.10+，run_all.py 依赖 PEP 604 联合类型，
# 其他子脚本也用了 3.10+ 语法）。任务计划环境 PATH 可能与交互式不同，
# 所以解析真实绝对路径后再写入任务。
$PythonCmd = $null
$Candidates = @("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python", "py")
foreach ($cmd in $Candidates) {
    try {
        $exe = & $cmd -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            $ok = & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $PythonCmd = $exe.Trim()
                break
            }
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Error "未找到 Python 3.10+。请先安装（run_all.py 依赖 PEP 604 联合类型语法）。"
    exit 1
}

Write-Host "Python: $PythonCmd" -ForegroundColor Green
Write-Host "Vault:  $VaultDir" -ForegroundColor Green
Write-Host ""

if ($Uninstall) {
    Write-Host "正在卸载定时任务..."
    if ($DryRun) {
        Write-Host "[Dry Run] 将删除任务: $TaskName"
    } else {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "任务已卸载。" -ForegroundColor Yellow
    }
    exit 0
}

# 从 kis_config 读取自动化配置
$SettingsPython = @"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'$ScriptDir').resolve()))
from kis_config import automation_interval_days, automation_scan_days, automation_run_hour
interval = automation_interval_days()
override = $Interval
if override and override > 0:
    interval = override
elif override == 0:
    pass
print(interval if interval is not None else 'NONE', automation_scan_days(), automation_run_hour())
"@

$SettingsRaw = & $PythonCmd -c $SettingsPython
if ($LASTEXITCODE -ne 0) {
    Write-Error "读取自动化配置失败。"
    exit 1
}
$Parts = $SettingsRaw.Trim().Split(" ")
$IntervalDays = $Parts[0]
$ScanDays = [int]$Parts[1]
$RunHour = [int]$Parts[2]

if ($IntervalDays -eq "NONE") {
    Write-Host "⚠️ 当前配置为“不开启自动化”。" -ForegroundColor Yellow
    Write-Host "   先运行：python3 scripts/setup_preflight.py --set-daily-interval N (N 为 1/2/3/4)"
    Write-Host "   或临时安装：.\install_automation.ps1 -Interval N"
    exit 0
}
$IntervalDays = [int]$IntervalDays

Write-Host "配置：每 $IntervalDays 天在 ${RunHour}:00 自动运行，扫描最近 $ScanDays 天。" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "=== [Dry Run] 预览 ==="
    Write-Host "任务名称: $TaskName"
    Write-Host "执行程序: $PythonCmd"
    Write-Host "脚本路径: $RunAllPy"
    Write-Host "参数:      --only daily --days $ScanDays"
    Write-Host "工作目录: $VaultDir"
    Write-Host "触发时间: 每 $IntervalDays 天 ${RunHour}:00"
    Write-Host ""
    Write-Host "实际安装请去掉 -DryRun 参数。"
    exit 0
}

# 检查是否已存在
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "任务已存在，正在更新..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 创建任务操作
$Action = New-ScheduledTaskAction `
    -Execute $PythonCmd `
    -Argument "`"$RunAllPy`" --only daily --days $ScanDays" `
    -WorkingDirectory $VaultDir

# 创建触发器：每 N 天在 RunHour:00
$StartTime = (Get-Date).Date.AddHours($RunHour)
if ($StartTime -lt (Get-Date)) { $StartTime = $StartTime.AddDays(1) }
$Trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $IntervalDays -At $StartTime

# 创建任务设置
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# 注册任务
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "小夏知识蒸馏系统 - 每 $IntervalDays 天自动蒸馏" `
    -Force

Write-Host "✅ 定时任务已安装！" -ForegroundColor Green
Write-Host ""
Write-Host "任务名称:   $TaskName"
Write-Host "运行频率:   每 $IntervalDays 天 ${RunHour}:00"
Write-Host "执行内容:   python run_all.py --only daily --days $ScanDays"
Write-Host ""
Write-Host "管理命令："
Write-Host "  查看任务:   Get-ScheduledTask -TaskName $TaskName"
Write-Host "  手动运行:   Start-ScheduledTask -TaskName $TaskName"
Write-Host "  卸载任务:   .\install_automation.ps1 -Uninstall"
