using System;
using System.IO;
using System.Threading;
using System.Windows;

namespace StockBar;
public static class Program
{
    [STAThread]
    public static void Main()
    {
        using var mutex = new Mutex(true, "Local\\WdcStockBar", out bool first);
        if (!first)
        {
            if (EventWaitHandle.TryOpenExisting("Local\\WdcStockBar.Show", out var existing))
            { using (existing) existing.Set(); }
            return;
        }
        using var showSignal = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\WdcStockBar.Show");
        var root = FindRoot();
        Directory.CreateDirectory(Path.Combine(root, "runtime"));
        var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
        app.DispatcherUnhandledException += (_, e) =>
        {
            File.AppendAllText(Path.Combine(root, "runtime", "error.log"), DateTime.Now + " " + e.Exception + Environment.NewLine);
        };
        var window = new MainWindow(root);
        var registration = ThreadPool.RegisterWaitForSingleObject(showSignal,
            (_, _) => app.Dispatcher.BeginInvoke(new Action(window.ShowFromShortcut)), null, Timeout.Infinite, false);
        try { app.Run(window); }
        finally { registration.Unregister(null); }
    }
    public static string FindRoot()
    {
        var folder = new DirectoryInfo(AppContext.BaseDirectory);
        while (folder != null)
        {
            if (File.Exists(Path.Combine(folder.FullName, "bridge", "worker.py"))) return folder.FullName;
            folder = folder.Parent;
        }
        return AppContext.BaseDirectory;
    }
}
