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

$c = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, "btnGrab")
$btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
if ($null -eq $btn) { Write-Output "BUTTON_NOT_FOUND"; exit 1 }

$before = $btn.Current.Name
$ip = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$ip.Invoke()
Start-Sleep -Seconds 1

$btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
$after = $btn.Current.Name
[System.IO.File]::WriteAllText(
    "E:\project\stream\tools\BarrageGrab\toggle.txt",
    "before=$before`r`nafter=$after",
    [System.Text.Encoding]::UTF8)
Write-Output "TOGGLED"
