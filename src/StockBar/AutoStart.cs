using System;
using Microsoft.Win32;

namespace StockBar;

// Per-user Run key: no admin rights, and Windows' own startup-apps page can still turn it off.
public static class AutoStart
{
    private const string Key = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string Name = "WdcStockBar";
    private static string Command => "\"" + Environment.ProcessPath + "\"";

    public static bool IsEnabled()
    {
        using var run = Registry.CurrentUser.OpenSubKey(Key);
        return run?.GetValue(Name) is string;
    }

    public static void Set(bool enabled)
    {
        using var run = Registry.CurrentUser.CreateSubKey(Key);
        if (enabled) run.SetValue(Name, Command);
        else run.DeleteValue(Name, false);
    }

    // A moved or rebuilt folder must not leave login launching a stale path.
    public static void Repair()
    {
        using var run = Registry.CurrentUser.OpenSubKey(Key);
        if (run?.GetValue(Name) is string current && current != Command) Set(true);
    }
}
