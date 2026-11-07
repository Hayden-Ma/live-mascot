Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public class WinDump {
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, StringBuilder l);

    public static string Dump(uint targetPid) {
        var sb = new StringBuilder();
        EnumWindows((h, l) => {
            uint p; GetWindowThreadProcessId(h, out p);
            if (p == targetPid) {
                EnumChildWindows(h, (c, l2) => {
                    var cls = new StringBuilder(256); GetClassName(c, cls, 256);
                    var txt = new StringBuilder(8192);
                    SendMessage(c, 0x000D, (IntPtr)8192, txt);
                    if (txt.Length > 0) sb.AppendLine(cls.ToString() + " => " + txt.ToString());
                    return true;
                }, IntPtr.Zero);
            }
            return true;
        }, IntPtr.Zero);
        return sb.ToString();
    }
}
"@
$p = Get-Process BarrageGrab -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { "NO_PROCESS"; exit }
[System.IO.File]::WriteAllText(
    "E:\project\stream\tools\bg_wintext.txt",
    [WinDump]::Dump([uint32]$p.Id),
    [System.Text.Encoding]::UTF8)
"SAVED"
