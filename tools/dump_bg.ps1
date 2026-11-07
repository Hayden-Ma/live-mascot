Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$p = Get-Process BarrageGrab -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { "NO_PROCESS"; exit }
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if ($null -eq $win) { $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond) }
if ($null -eq $win) { "NO_WINDOW"; exit }
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
"ELEMENTS=" + $all.Count
$out = ""
foreach ($it in $all) {
    $ct = $it.Current.ControlType.ProgrammaticName
    if ($ct -match "Document|Edit|Text") {
        try {
            $tp = $it.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
            $out += $tp.DocumentRange.GetText(-1) + "`r`n"
        } catch {}
    }
}
[System.IO.File]::WriteAllText(
    "E:\project\stream\tools\bg_console_dump.txt", $out, [System.Text.Encoding]::UTF8)
"SAVED len=" + $out.Length
