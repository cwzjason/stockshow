using System;
using System.Collections.Generic;
using System.Linq;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Forms = System.Windows.Forms;

namespace StockBar;

public sealed class MainWindow : Window
{
    private readonly string root;
    private readonly TextBlock ticker = Label("WDC ⌕", 11, "#C7D9F0");
    private WatchlistConfig catalog = new();
    private MarketFeed feed = new();
    private string currentSymbol = "WDC";
    private List<string> recent = new();
    private SearchWindow? searchWindow;
    private readonly TextBlock price = Label("—", 13, "#F0F4FC");
    private readonly TextBlock change = Label("—", 11, "#8FA2B8");
    private readonly TextBlock state = Label("等待行情", 10, "#E8B66C");
    private readonly System.Windows.Shapes.Ellipse dot = new() { Width = 6, Height = 6, Fill = Brush("#7A828E") };
    private readonly Border sessionChip = new() { CornerRadius = new CornerRadius(6), Padding = new Thickness(6, 2, 6, 2), Background = Brush("#2A2E36") };
    private FileSystemWatcher? watcher;
    private double? lastPrice;
    // Push arrives as a file write; the timer is only a safety net and a worker health check.
    private readonly DispatcherTimer poll = new() { Interval = TimeSpan.FromSeconds(2) };
    private readonly Forms.NotifyIcon tray;
    private IntPtr trayHandle;
    private int trayMood = int.MinValue;
    private Process? worker;
    private Snapshot snapshot = new();
    private bool locked;
    private double compactLeft, compactTop;
    private IntPtr hwnd;
    private HwndSource? hwndSource;
    private int restartTicks;
    private Settings settings = new();
    private static Brush Brush(string value) => (Brush)new BrushConverter().ConvertFromString(value)!;
    private static Color Colour(string value) => (Color)ColorConverter.ConvertFromString(value);
    private void Flash(TextBlock target, string colour)
    {
        var brush = new SolidColorBrush(Colour(colour));
        target.Background = brush;
        brush.BeginAnimation(SolidColorBrush.ColorProperty, new ColorAnimation(Colors.Transparent, TimeSpan.FromMilliseconds(450)));
    }
    private static TextBlock Label(string text, double size, string color) => new()
    {
        Text = text, FontSize = size, Foreground = Brush(color),
        VerticalAlignment = VerticalAlignment.Center, FontFamily = new FontFamily("Segoe UI, Microsoft YaHei UI")
    };

    public MainWindow(string projectRoot)
    {
        root = projectRoot;
        Title = "桌面股票行情";
        Width = TickerLayout.Width; Height = TickerLayout.Height; WindowStyle = WindowStyle.None;
        ResizeMode = ResizeMode.NoResize; AllowsTransparency = true; Background = Brushes.Transparent;
        Topmost = true; ShowInTaskbar = false; ShowActivated = false;
        try { settings = JsonSerializer.Deserialize<Settings>(File.ReadAllText(Path.Combine(root, "runtime", "settings.json"))) ?? new(); } catch { }
        currentSymbol = WatchlistParser.Normalize(settings.SelectedSymbol) ?? "WDC";
        recent = (settings.RecentSymbols ?? new()).Prepend(currentSymbol).Distinct().Take(12).ToList();
        try { catalog = JsonSerializer.Deserialize<WatchlistConfig>(File.ReadAllText(Path.Combine(root, "watchlist.json")), Snapshot.JsonOptions) ?? new(); } catch { }
        Opacity = Math.Clamp(settings.Opacity, .45, 1);
        // First launch opts in to login start; afterwards the tray toggle is the user's choice.
        try
        {
            if (settings.AutoStart == null) { AutoStart.Set(true); settings.AutoStart = true; }
            else AutoStart.Repair();
        }
        catch (Exception e) { Log("autostart: " + e.Message); }
        locked = settings.Locked;
        var area = SystemParameters.WorkArea;
        var home = TickerLayout.Default(SystemParameters.PrimaryScreenWidth, SystemParameters.PrimaryScreenHeight, area.Bottom);
        compactLeft = Math.Clamp(settings.LayoutVersion == 2 ? settings.Left ?? home.Left : home.Left, 0, Math.Max(0, SystemParameters.PrimaryScreenWidth - Width));
        compactTop = Math.Clamp(settings.LayoutVersion == 2 ? settings.Top ?? home.Top : home.Top, 0, Math.Max(0, SystemParameters.PrimaryScreenHeight - Height));
        Left = compactLeft; Top = compactTop;

        var row = new Grid { Margin = new Thickness(10, 0, 10, 0) };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(12) });
        foreach (var width in new[] { 58d, 76d, 58d }) row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(width) });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        dot.VerticalAlignment = VerticalAlignment.Center;
        dot.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(1, .35, TimeSpan.FromMilliseconds(1400)) { AutoReverse = true, RepeatBehavior = RepeatBehavior.Forever });
        row.Children.Add(dot);
        ticker.FontWeight = FontWeights.SemiBold;
        var pill = new Border { Background = Brush("#333C4B"), CornerRadius = new CornerRadius(7), Padding = new Thickness(6, 2, 6, 2),
            Child = ticker, HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center };
        var searchButton = new Button { Content = pill, Background = Brushes.Transparent, BorderThickness = new Thickness(0), Padding = new Thickness(0), HorizontalContentAlignment = HorizontalAlignment.Left, Focusable = false, ToolTip = "搜索股票：输入代码或公司名称" };
        searchButton.Click += (_, _) => OpenSearch();
        Grid.SetColumn(searchButton, 1); row.Children.Add(searchButton);
        price.Background = new SolidColorBrush(Colors.Transparent);
        price.Padding = new Thickness(4, 2, 4, 2);
        Grid.SetColumn(price, 2); row.Children.Add(price);
        Grid.SetColumn(change, 3); row.Children.Add(change);
        sessionChip.Child = state;
        sessionChip.HorizontalAlignment = HorizontalAlignment.Left;
        sessionChip.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(sessionChip, 4); row.Children.Add(sessionChip);
        var bar = new Border { Width = TickerLayout.Width, Height = TickerLayout.Height, HorizontalAlignment = HorizontalAlignment.Left,
            Background = new LinearGradientBrush(Colour("#2B3038"), Colour("#1B1F25"), new Point(0, 0), new Point(0, 1)),
            BorderBrush = Brush("#4A515C"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(9), Child = row, Cursor = Cursors.Hand };
        Content = bar;

        bar.MouseLeftButtonDown += (_, e) =>
        {
            if (locked) return;
            try { DragMove(); } catch (InvalidOperationException) { }
            compactLeft = Left;
            compactTop = Top;
            SaveSettings(); e.Handled = true;
        };
        ContextMenu = BuildMenu();
        tray = new Forms.NotifyIcon { Text = "桌面股票行情 · 点击代码搜索换股", Visible = true };
        UpdateTrayIcon(0);
        tray.MouseClick += (_, e) => { if (e.Button == Forms.MouseButtons.Left) Dispatcher.Invoke(Toggle); };
        var trayMenu = new Forms.ContextMenuStrip();
        trayMenu.Items.Add("搜索 / 换股票", null, (_, _) => Dispatcher.Invoke(OpenSearch));
        trayMenu.Items.Add("显示 / 隐藏", null, (_, _) => Dispatcher.Invoke(Toggle));
        var startItem = new Forms.ToolStripMenuItem("开机自启") { CheckOnClick = true, Checked = SafeIsAutoStart() };
        startItem.Click += (_, _) => Dispatcher.Invoke(() =>
        {
            try { AutoStart.Set(startItem.Checked); settings.AutoStart = startItem.Checked; SaveSettings(); }
            catch (Exception e) { startItem.Checked = SafeIsAutoStart(); Log("autostart: " + e.Message); }
        });
        trayMenu.Items.Add(startItem);
        trayMenu.Items.Add("长桥实时行情设置…", null, (_, _) => Dispatcher.Invoke(OpenLongbridgeSetup));
        trayMenu.Items.Add("连接帮助", null, (_, _) => Dispatcher.Invoke(OpenHelp));
        trayMenu.Items.Add("退出", null, (_, _) => Dispatcher.Invoke(Close));
        trayMenu.Opening += (_, _) => startItem.Checked = SafeIsAutoStart();
        tray.ContextMenuStrip = trayMenu;
        SourceInitialized += (_, _) =>
        {
            hwnd = new WindowInteropHelper(this).Handle;
            hwndSource = HwndSource.FromHwnd(hwnd); hwndSource.AddHook(WndProc);
            // Tool window: no taskbar button and no Alt+Tab entry; it lives in the tray.
            SetWindowLong(hwnd, GWL_EXSTYLE, GetWindowLong(hwnd, GWL_EXSTYLE) | WS_EX_TOOLWINDOW);
            bool hotkey = RegisterHotKey(hwnd, 1, 0x0002 | 0x0001 | 0x4000, 0x57);
            if (!hotkey) tray.Text = "WDC 桌面行情 · 快捷键被占用，双击托盘显示/隐藏";
            // ShowActivated=false avoids focus on startup; hovering/resizing does not activate.
            // Keep ordinary click activation so context menus remain keyboard accessible.
        };
        Loaded += (_, _) => { WriteSelection(); StartWorker(); StartWatch(); poll.Start(); Refresh(); };
        poll.Tick += (_, _) => { KeepOnTop(); Refresh(); };
        Closed += (_, _) =>
        {
            searchWindow?.Close();
            poll.Stop(); watcher?.Dispose(); SaveSettings();
            UnregisterHotKey(hwnd, 1); hwndSource?.RemoveHook(WndProc);
            tray.Visible = false; tray.Dispose();
            if (trayHandle != IntPtr.Zero) DestroyIcon(trayHandle);
            try { if (worker is { HasExited: false }) worker.Kill(true); worker?.Dispose(); } catch { }
        };
    }

    private ContextMenu BuildMenu()
    {
        var menu = new ContextMenu();
        void Add(string text, Action action) { var item = new MenuItem { Header = text }; item.Click += (_, _) => action(); menu.Items.Add(item); }
        Add("搜索 / 换股票…", OpenSearch);
        var lockItem = new MenuItem { Header = "锁定位置", IsCheckable = true, IsChecked = locked };
        lockItem.Click += (_, _) => { locked = lockItem.IsChecked; SaveSettings(); }; menu.Items.Add(lockItem);
        var opacity = new MenuItem { Header = "透明度" };
        foreach (var value in new[] { 1d, .85, .65, .45 })
        {
            var item = new MenuItem { Header = $"{value:P0}" }; item.Click += (_, _) => { Opacity = value; SaveSettings(); }; opacity.Items.Add(item);
        }
        menu.Items.Add(opacity);
        Add("恢复到天气右侧", () => { var home = TickerLayout.Default(SystemParameters.PrimaryScreenWidth, SystemParameters.PrimaryScreenHeight, SystemParameters.WorkArea.Bottom); Left = compactLeft = home.Left; Top = compactTop = home.Top; SaveSettings(); });
        Add("查看当前股票行情来源", OpenHelp);
        Add("隐藏（Ctrl+Alt+W 恢复）", Hide);
        Add("退出", Close);
        return menu;
    }
    private static bool SafeIsAutoStart() { try { return AutoStart.IsEnabled(); } catch { return false; } }
    private void OpenLongbridgeSetup()
    {
        var path = Path.Combine(root, "runtime", "longbridge.json");
        try
        {
            if (!File.Exists(path))
                File.WriteAllText(path, JsonSerializer.Serialize(new Dictionary<string, string>
                {
                    ["appKey"] = "<App Key>", ["appSecret"] = "<App Secret>", ["accessToken"] = "<Access Token>",
                    ["_说明"] = "在 open.longbridge.com 开发者中心获取三项后替换尖括号内容并保存；约 3 秒内自动生效，无需重启。"
                }, new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
            Process.Start(new ProcessStartInfo("notepad.exe") { ArgumentList = { path }, UseShellExecute = false });
            Process.Start(new ProcessStartInfo("https://open.longbridge.com/") { UseShellExecute = true });
        }
        catch (Exception e) { Log("longbridge setup: " + e.Message); }
    }
    // Clicking the taskbar raises it over topmost windows; put the bar back on top.
    private void KeepOnTop()
    {
        if (IsVisible && hwnd != IntPtr.Zero && searchWindow == null && ContextMenu?.IsOpen != true)
            SetWindowPos(hwnd, new IntPtr(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);
    }
    private void UpdateTrayIcon(int mood)
    {
        if (mood == trayMood) return;
        trayMood = mood;
        int size = Math.Max(16, Forms.SystemInformation.SmallIconSize.Width);
        using var bitmap = new System.Drawing.Bitmap(size, size);
        using (var g = System.Drawing.Graphics.FromImage(bitmap))
        {
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            using var back = new System.Drawing.SolidBrush(System.Drawing.ColorTranslator.FromHtml("#1B1F25"));
            g.FillEllipse(back, 0, 0, size - 1, size - 1);
            using var fore = new System.Drawing.SolidBrush(System.Drawing.ColorTranslator.FromHtml(mood > 0 ? "#58DCAF" : mood < 0 ? "#FF8792" : "#8FA2B8"));
            float m = size * .25f, w = size - 2 * m;
            if (mood == 0) g.FillRectangle(fore, m, size * .44f, w, size * .14f);
            else
            {
                float top = size * .3f, bottom = size * .7f;
                var points = mood > 0
                    ? new[] { new System.Drawing.PointF(size / 2f, top), new(m + w, bottom), new(m, bottom) }
                    : new[] { new System.Drawing.PointF(m, top), new(m + w, top), new(size / 2f, bottom) };
                g.FillPolygon(fore, points);
            }
        }
        var handle = bitmap.GetHicon();
        tray.Icon = System.Drawing.Icon.FromHandle(handle);
        if (trayHandle != IntPtr.Zero) DestroyIcon(trayHandle);
        trayHandle = handle;
    }
    private void OpenHelp() => Process.Start(new ProcessStartInfo("https://finance.yahoo.com/quote/" + Uri.EscapeDataString(currentSymbol) + "/") { UseShellExecute = true });
    private void OpenSearch()
    {
        if (searchWindow != null) { searchWindow.Activate(); return; }
        if (!IsVisible) Show();
        var dialog = new SearchWindow(this, catalog, recent);
        searchWindow = dialog;
        dialog.Closed += (_, _) =>
        {
            if (dialog.SelectedSymbol is string symbol)
            {
                currentSymbol = symbol;
                recent = recent.Prepend(symbol).Distinct().Take(12).ToList();
                snapshot = feed.ForSymbol(symbol);
                WriteSelection(); SaveSettings(); Refresh();
            }
            searchWindow = null;
        };
        dialog.Show();
    }
    private void WriteSelection()
    {
        try
        {
            var path = Path.Combine(root, "runtime", "selection.json");
            File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(new { symbol = currentSymbol, nextSymbol = currentSymbol }));
            File.Move(path + ".tmp", path, true);
        }
        catch (IOException e) { Log(e.Message); }
    }
    private void Toggle()
    {
        if (IsVisible) { searchWindow?.Close(); Hide(); }
        else Show();
    }
    public void ShowFromShortcut()
    {
        Show();
        Activate();
        if (searchWindow != null) searchWindow.Activate();
    }
    private void StartWorker()
    {
        try
        {
            var python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            if (!File.Exists(python)) { ToolTip = "缺少行情依赖，请运行安装依赖.cmd"; return; }
            var info = new ProcessStartInfo(python) { WorkingDirectory = root, CreateNoWindow = true, UseShellExecute = false };
            info.ArgumentList.Add(Path.Combine(root, "bridge", "worker.py"));
            info.ArgumentList.Add("--output"); info.ArgumentList.Add(Path.Combine(root, "runtime", "market.json"));
            // Without this the worker outlives a killed UI and keeps writing quotes nobody shows.
            info.ArgumentList.Add("--owner"); info.ArgumentList.Add(Environment.ProcessId.ToString());
            // SDK logging is kept outside the visible desktop UI.
            info.RedirectStandardOutput = true; info.RedirectStandardError = true;
            worker = new Process { StartInfo = info };
            worker.OutputDataReceived += (_, e) => Log(e.Data);
            worker.ErrorDataReceived += (_, e) => Log(e.Data);
            worker.Start(); worker.BeginOutputReadLine(); worker.BeginErrorReadLine();
        }
        catch (Exception e) { ToolTip = "行情服务启动失败：" + e.Message; Log(e.ToString()); }
    }
    private void StartWatch()
    {
        try
        {
            var folder = Path.Combine(root, "runtime");
            watcher = new FileSystemWatcher(folder, "market.json") { NotifyFilter = NotifyFilters.LastWrite };
            // The worker writes atomically via os.replace; a rename lands as Created here.
            watcher.Changed += OnMarketChanged;
            watcher.Created += OnMarketChanged;
            watcher.EnableRaisingEvents = true;
        }
        catch (Exception e) { Log(e.Message); }
    }
    private void OnMarketChanged(object sender, FileSystemEventArgs e) => Dispatcher.BeginInvoke(Refresh);
    private readonly object logLock = new();
    private void Log(string? message)
    {
        if (string.IsNullOrWhiteSpace(message)) return;
        lock (logLock)
        {
            try
            {
                var path = Path.Combine(root, "runtime", "bridge.log");
                if (File.Exists(path) && new FileInfo(path).Length > 1_000_000) File.WriteAllText(path, "");
                File.AppendAllText(path, DateTime.Now.ToString("s") + " " + message + Environment.NewLine);
            }
            catch { }
        }
    }
    private void Refresh()
    {
        if (worker == null || worker.HasExited)
        {
            if (++restartTicks >= 8) { restartTicks = 0; worker?.Dispose(); StartWorker(); }
        }
        try
        {
            var path = Path.Combine(root, "runtime", "market.json");
            if (File.Exists(path)) feed = JsonSerializer.Deserialize<MarketFeed>(File.ReadAllText(path), Snapshot.JsonOptions) ?? feed;
        }
        catch (Exception e) when (e is IOException || e is JsonException) { Log(e.Message); }
        snapshot = feed.ForSymbol(currentSymbol);
        ticker.Text = currentSymbol + " ⌕";
        ticker.FontSize = currentSymbol.Length > 7 ? 9 : 11;
        bool stale = snapshot.IsStale(DateTimeOffset.UtcNow);
        price.Text = snapshot.DisplayPrice; change.Text = snapshot.DisplayChange;
        price.FontSize = price.Text.Length > 9 ? 10.5 : 13;
        var moved = snapshot.HasPrice ? snapshot.Price : null;
        if (lastPrice is double was && moved is double now && Math.Abs(now - was) > 1e-9)
            Flash(price, now > was ? "#2E6B54" : "#6B3540");
        lastPrice = moved;
        change.Foreground = stale ? Brush("#8993A3") : Brush(snapshot.ChangePercent >= 0 ? "#58DCAF" : "#FF8792");
        state.Text = stale ? (snapshot.HasPrice ? "断线·旧报价" : snapshot.FetchedAt == default ? "连接中" : "暂无行情") : !snapshot.Available ? snapshot.Session + "·暂无" : snapshot.Session;
        var (chipBack, chipFore) = SessionStyle.For(stale ? "断线" : !snapshot.Available ? "休市" : snapshot.Session);
        sessionChip.Background = Brush(chipBack);
        state.Foreground = Brush(chipFore);
        dot.Fill = Brush(!snapshot.Connected ? "#7A828E" : stale ? "#E8B66C" : "#58DCAF");
        var message = stale && snapshot.Connected ? "行情超过 30 秒未更新，当前为旧数据" : snapshot.Message;
        var broker = "长桥：" + feed.Providers.GetValueOrDefault("longbridge", "未配置") + "（托盘菜单可设置）";
        ToolTip = $"{currentSymbol} · {catalog.Names.GetValueOrDefault(currentSymbol, currentSymbol)}\n{snapshot.Source}\n数据时间：{(string.IsNullOrWhiteSpace(snapshot.QuoteTime) ? "尚未提供" : snapshot.QuoteTime + " ET")}\n{message}\n{broker}";
        if (!stale && snapshot.HasPrice && snapshot.Session is "盘前" or "盘中" or "盘后" or "夜盘")
        {
            if (DateTime.TryParse(snapshot.QuoteTime, out var sourceTime))
            {
                var eastern = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
                var nowEt = TimeZoneInfo.ConvertTime(DateTimeOffset.UtcNow, eastern).DateTime;
                if (nowEt - sourceTime > TimeSpan.FromMinutes(3)) state.Text = snapshot.Session + "·旧报价";
            }
        }
        UpdateTrayIcon(!snapshot.HasPrice || stale ? 0 : snapshot.ChangePercent >= 0 ? 1 : -1);
        var trayText = $"{currentSymbol} {snapshot.DisplayPrice} {snapshot.DisplayChange} {state.Text}\n{snapshot.Source}";
        tray.Text = trayText.Length > 127 ? trayText[..127] : trayText;
        var referenceLabel = snapshot.Session is "盘后" or "夜盘" ? "涨跌幅对比常规收盘价" : "涨跌幅对比昨收";
        change.ToolTip = referenceLabel;
    }
    private void SaveSettings()
    {
        try
        {
            File.WriteAllText(Path.Combine(root, "runtime", "settings.json"), JsonSerializer.Serialize(new Settings { LayoutVersion = 2, Left = compactLeft, Top = compactTop, Opacity = Opacity, Locked = locked, SelectedSymbol = currentSymbol, RecentSymbols = recent, AutoStart = settings.AutoStart }));
        }
        catch (IOException) { }
    }
    private IntPtr WndProc(IntPtr handle, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == 0x0312 && wParam.ToInt32() == 1) { Toggle(); handled = true; }
        return IntPtr.Zero;
    }
    [DllImport("user32.dll")] private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] private static extern int GetWindowLong(IntPtr hWnd, int index);
    [DllImport("user32.dll")] private static extern int SetWindowLong(IntPtr hWnd, int index, int value);
    [DllImport("user32.dll")] private static extern bool DestroyIcon(IntPtr handle);
    private const int GWL_EXSTYLE = -20, WS_EX_TOOLWINDOW = 0x80;
    private sealed class Settings
    {
        public int LayoutVersion { get; set; }
        public double? Left { get; set; }
        public double? Top { get; set; }
        public double Opacity { get; set; } = .95;
        public bool Locked { get; set; }
        public string SelectedSymbol { get; set; } = "WDC";
        public List<string> RecentSymbols { get; set; } = new();
        public bool? AutoStart { get; set; }
    }
}
