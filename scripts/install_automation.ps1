# Windows 定时任务安装脚本（Scheduled Tasks · per-task v0.2+）
#
# 从 .knowledge-iteration-system.json 的 automation.tasks 表读取每个任务的
# schedule / hour / minute / dayOfWeek，为每个启用的任务注册一个独立的
# Scheduled Task（KnowledgeIteration_<task_key>）。
#
# 支持的 schedule 值：
#   - daily              → New-ScheduledTaskTrigger -Daily -At HH:MM
#   - weekly             → -Weekly -DaysOfWeek <day> -At HH:MM
#   - quarterly-last-day → 4 个 -Once 触发器 (每年 3/31 6/30 9/30 12/31) + 每年重复
#
# 用法：
#   .\scripts\install_automation.ps1
#   .\scripts\install_automation.ps1 -DryRun
#   .\scripts\install_automation.ps1 -Uninstall

param(
    [switch]$Uninstall,
    [switch]$DryRun
)

$TaskPrefix = "KnowledgeIteration_"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VaultDir = Split-Path -Parent $ScriptDir
$LogsDir = Join-Path $ScriptDir "logs"

# ---------- Python 探测 ----------
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

Write-Host "🔬 知识蒸馏自动化安装脚本（Windows · per-task v0.2+）" -ForegroundColor Cyan
Write-Host "======================================================"
Write-Host "Vault:  $VaultDir" -ForegroundColor Green
Write-Host "Python: $PythonCmd" -ForegroundColor Green
Write-Host ""

# ---------- Uninstall 分支 ----------
if ($Uninstall) {
    Write-Host "将卸载所有 $TaskPrefix* 计划任务..."
    $existing = Get-ScheduledTask -TaskName "$TaskPrefix*" -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "没有匹配的任务。" -ForegroundColor Yellow
        exit 0
    }
    foreach ($t in $existing) {
        if ($DryRun) {
            Write-Host "[Dry Run] 将卸载: $($t.TaskName)"
        } else {
            Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
            Write-Host "✅ 已卸载: $($t.TaskName)" -ForegroundColor Green
        }
    }
    exit 0
}

# ---------- 读取任务表（用 Python 解析 kis_config）----------
$ReadTasksPy = @"
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(r'$ScriptDir').resolve()))
from kis_config import ordered_task_items, validate_task
out = []
errs = []
for key, task in ordered_task_items():
    if not task.get('enabled', True):
        continue
    verr = validate_task(key, task)
    if verr:
        errs.extend(verr)
        continue
    out.append({
        'key': key,
        'label': task.get('label', key),
        'schedule': task.get('schedule'),
        'hour': int(task.get('hour', 9)),
        'minute': int(task.get('minute', 0)),
        'dayOfWeek': int(task.get('dayOfWeek', 0)) if task.get('dayOfWeek') is not None else 0,
        'script': task.get('script', ''),
        'args': task.get('args') or [],
    })
if errs:
    for e in errs:
        print(e, file=sys.stderr)
    sys.exit(3)
print(json.dumps(out, ensure_ascii=False))
"@

$TasksJson = & $PythonCmd -c $ReadTasksPy
if ($LASTEXITCODE -ne 0) {
    Write-Error "读取任务表失败。"
    exit 1
}

$Tasks = $TasksJson | ConvertFrom-Json
if (-not $Tasks -or $Tasks.Count -eq 0) {
    Write-Host "⚠️ 没有启用的自动化任务。" -ForegroundColor Yellow
    Write-Host "   先跑：python scripts\setup_preflight.py --ask-tasks"
    exit 0
}

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
}

# 星期几映射：0=Sunday..6=Saturday
$DayNames = @('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')

Write-Host "=== 计划安装的任务 ==="
foreach ($t in $Tasks) {
    $hhmm = "{0:D2}:{1:D2}" -f $t.hour, $t.minute
    switch ($t.schedule) {
        'daily' { $desc = "每天 $hhmm" }
        'weekly' { $desc = "每周 $($DayNames[$t.dayOfWeek]) $hhmm" }
        'quarterly-last-day' { $desc = "季度最后一天 $hhmm" }
        default { $desc = "$($t.schedule) $hhmm" }
    }
    $argsStr = if ($t.args) { $t.args -join ' ' } else { '' }
    Write-Host "  - $TaskPrefix$($t.key)   $desc   → $($t.script) $argsStr"
}
Write-Host ""

function Build-Trigger($task) {
    $hh = [int]$task.hour
    $mm = [int]$task.minute
    # 生成一个 base DateTime（今天的 HH:MM）
    $today = (Get-Date).Date
    $baseTime = $today.AddHours($hh).AddMinutes($mm)
    if ($baseTime -lt (Get-Date)) { $baseTime = $baseTime.AddDays(1) }

    switch ($task.schedule) {
        'daily' {
            return @(New-ScheduledTaskTrigger -Daily -At $baseTime)
        }
        'weekly' {
            $day = $DayNames[[int]$task.dayOfWeek]
            return @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek $day -At $baseTime)
        }
        'quarterly-last-day' {
            # 4 个 -Once 触发器 + 每年重复 (RepetitionInterval 365d)
            # 更清晰的做法是每年注册一个新的 -Once，但为最小化维护，用 -Once + RepetitionInterval 365 天。
            $triggers = @()
            $year = (Get-Date).Year
            $lastDays = @(
                (Get-Date -Year $year -Month 3 -Day 31 -Hour $hh -Minute $mm -Second 0),
                (Get-Date -Year $year -Month 6 -Day 30 -Hour $hh -Minute $mm -Second 0),
                (Get-Date -Year $year -Month 9 -Day 30 -Hour $hh -Minute $mm -Second 0),
                (Get-Date -Year $year -Month 12 -Day 31 -Hour $hh -Minute $mm -Second 0)
            )
            foreach ($d in $lastDays) {
                if ($d -lt (Get-Date)) { $d = $d.AddYears(1) }
                $trg = New-ScheduledTaskTrigger -Once -At $d -RepetitionInterval (New-TimeSpan -Days 365) -RepetitionDuration ([TimeSpan]::MaxValue)
                $triggers += $trg
            }
            return $triggers
        }
        default {
            throw "unknown schedule: $($task.schedule)"
        }
    }
}

if ($DryRun) {
    Write-Host "=== [Dry Run] 预览首个任务参数 ==="
    $t = $Tasks[0]
    $argsList = @("`"$($ScriptDir)\$($t.script)`"") + $t.args
    Write-Host "任务名称: $TaskPrefix$($t.key)"
    Write-Host "执行程序: $PythonCmd"
    Write-Host "参数:      $($argsList -join ' ')"
    Write-Host "工作目录: $VaultDir"
    Write-Host "调度:      $($t.schedule) $($t.hour):$($t.minute)"
    Write-Host ""
    Write-Host "实际安装请去掉 -DryRun。"
    exit 0
}

# 先清理所有前缀任务（避免残留）
$existing = Get-ScheduledTask -TaskName "$TaskPrefix*" -ErrorAction SilentlyContinue
foreach ($t in $existing) {
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
}

$installed = 0
foreach ($t in $Tasks) {
    $taskName = "$TaskPrefix$($t.key)"
    $scriptPath = Join-Path $ScriptDir $t.script
    $argsList = @("`"$scriptPath`"") + ($t.args | ForEach-Object { $_ })
    $Action = New-ScheduledTaskAction `
        -Execute $PythonCmd `
        -Argument ($argsList -join ' ') `
        -WorkingDirectory $VaultDir

    $Triggers = Build-Trigger $t

    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $Action `
        -Trigger $Triggers `
        -Settings $Settings `
        -Description "$($t.label) (knowledge-iteration-system)" `
        -Force | Out-Null

    Write-Host "✅ 安装: $taskName ($($t.label))" -ForegroundColor Green
    $installed++
}

Write-Host ""
Write-Host "✅ 完成，共安装 $installed 个计划任务。" -ForegroundColor Cyan
Write-Host ""
Write-Host "管理命令："
Write-Host "  查看:      Get-ScheduledTask -TaskName '$TaskPrefix*'"
Write-Host "  立即触发:  Start-ScheduledTask -TaskName '${TaskPrefix}<task_key>'"
Write-Host "  查看日志:  Get-ChildItem '$LogsDir'"
Write-Host "  卸载全部:  .\scripts\install_automation.ps1 -Uninstall"
