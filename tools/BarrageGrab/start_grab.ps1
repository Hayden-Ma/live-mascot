param(
    [Parameter(Mandatory = $true)][string]$LiveId,
    [string]$OutFile = "E:\project\stream\tools\BarrageGrab\console.txt"
)

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$proc = Get-Process BarrageGrab -ErrorAction Stop | Select-Object -First 1
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if ($null -eq $win) {
    $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}
if ($null -eq $win) { Write-Output "WINDOW_NOT_FOUND"; exit 1 }

function Find-ById($parent, $id) {
    $c = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $parent.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
}

$edit = Find-ById $win "txtLiveUrl"
if ($null -eq $edit) { Write-Output "EDIT_NOT_FOUND"; exit 1 }
$vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
$vp.SetValue($LiveId)
Write-Output "LIVEID_SET"

$btn = Find-ById $win "btnGrab"
if ($null -eq $btn) { Write-Output "BUTTON_NOT_FOUND"; exit 1 }
$ip = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$ip.Invoke()
Write-Output "CLICKED"

Start-Sleep -Seconds 8

# 读取程序自身的控制台输出
$console = Find-ById $win "txtConsole"
if ($null -ne $console) {
    try {
        $tp = $console.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        $text = $tp.DocumentRange.GetText(-1)
        [System.IO.File]::WriteAllText($OutFile, $text, [System.Text.Encoding]::UTF8)
        Write-Output "CONSOLE_SAVED=$OutFile"
    } catch {
        Write-Output ("CONSOLE_READ_ERR=" + $_.Exception.Message)
    }
}
