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

$dir = "E:\project\stream\tools\BarrageGrab"

function Find-ById($parent, $id) {
    $c = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $id)
    return $parent.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $c)
}

$out = ""
$btn = Find-ById $win "btnGrab"
if ($null -ne $btn) { $out += "BTN_STATE=" + $btn.Current.Name + "`r`n" }
$edit = Find-ById $win "txtLiveUrl"
if ($null -ne $edit) {
    try {
        $vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        $out += "LIVEID=" + $vp.Current.Value + "`r`n"
    } catch { $out += "LIVEID=(read failed)`r`n" }
}

$docCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Document)
$docs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCond)
foreach ($d in $docs) {
    try {
        $tp = $d.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        $text = $tp.DocumentRange.GetText(-1)
        $out += "=== CONSOLE ===`r`n" + $text + "`r`n"
    } catch {}
}
[System.IO.File]::WriteAllText("$dir\console_dump.txt", $out, [System.Text.Encoding]::UTF8)
Write-Output "SAVED"
