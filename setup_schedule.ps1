# setup_schedule.ps1
# Registers a Windows Task Scheduler job to run the question bank pipeline
# on the 1st of every month from June through September at 9 AM.
#
# Run once to set up:  Right-click → "Run with PowerShell" (or run in terminal)
# To remove the task:  Unregister-ScheduledTask -TaskName "QuestionBankPipeline" -Confirm:$false

$TaskName    = "QuestionBankPipeline"
$ScriptPath  = "$PSScriptRoot\pipeline.py"
$PythonPath  = (Get-Command python -ErrorAction SilentlyContinue).Source

if (-not $PythonPath) {
    Write-Host "ERROR: Python not found in PATH. Please install Python and try again." -ForegroundColor Red
    exit 1
}

Write-Host "Setting up scheduled task: $TaskName" -ForegroundColor Cyan
Write-Host "  Script:  $ScriptPath"
Write-Host "  Python:  $PythonPath"
Write-Host "  Schedule: 1st of June, July, August, September at 9:00 AM"

# Remove existing task if present
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  Removed existing task."
}

# Action: run python pipeline.py
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory (Split-Path $ScriptPath)

# Trigger: 1st of each month in June-September at 9:00 AM
# Windows Task Scheduler doesn't support month ranges natively,
# so we create one trigger per month.
$Triggers = @(
    New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -MonthsOfYear June      -At "9:00AM",
    New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -MonthsOfYear July      -At "9:00AM",
    New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -MonthsOfYear August    -At "9:00AM",
    New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -MonthsOfYear September -At "9:00AM"
)

# Settings: run even if on battery, allow on-demand run
$Settings = New-ScheduledTaskSettingsSet `
    -DisallowStartIfOnBatteries:$false `
    -StopIfGoingOnBatteries:$false `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Principal: current user
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

# Register the task
Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Triggers `
    -Settings   $Settings `
    -Principal  $Principal `
    -Description "Monthly check for new MCAS/STAAR Grade 7 Math tests and question bank update." `
    | Out-Null

Write-Host ""
Write-Host "Task registered successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "To run it immediately:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To view in Task Scheduler: Open 'Task Scheduler' and look for '$TaskName'"
Write-Host "To remove the task:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
