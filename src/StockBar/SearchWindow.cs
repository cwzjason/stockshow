using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace StockBar;

public sealed class SearchWindow : Window
{
    private static readonly HttpClient client = CreateClient();
    private readonly WatchlistConfig config;
    private readonly IEnumerable<string> recent;
    private readonly TextBox input;
    private readonly ListBox results;
    private readonly TextBlock status;
    private readonly DispatcherTimer debounce = new() { Interval = TimeSpan.FromMilliseconds(350) };
    private CancellationTokenSource? cancellation;
    private int generation;
    private bool searching;
    public string? SelectedSymbol { get; private set; }
    private static Brush Color(string value) => (Brush)new BrushConverter().ConvertFromString(value)!;
    private static HttpClient CreateClient()
    {
        var result = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        result.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0");
        return result;
    }
    public SearchWindow(Window owner, WatchlistConfig watchlist, IEnumerable<string> recentSymbols)
    {
        config = watchlist; recent = recentSymbols.ToArray();
        Title = "搜索股票"; Width = 510; Height = 390;
        ResizeMode = ResizeMode.NoResize; WindowStyle = WindowStyle.SingleBorderWindow;
        ShowInTaskbar = true; Topmost = true; Background = Color("#111B2B"); Foreground = Brushes.White;
        FontFamily = new FontFamily("Segoe UI, Microsoft YaHei UI");
        Left = Math.Clamp(owner.Left, 0, Math.Max(0, SystemParameters.PrimaryScreenWidth - Width));
        Top = Math.Max(0, owner.Top - Height - 8);
        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition());
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var hint = new TextBlock { Text = "搜索代码或公司名称，不限于自选列表", Foreground = Color("#A8B8CE"), Margin = new Thickness(0, 0, 0, 10) };
        grid.Children.Add(hint);
        input = new TextBox { FontSize = 17, Padding = new Thickness(10, 8, 10, 8), Background = Color("#202D40"), Foreground = Brushes.White, BorderBrush = Color("#40536D") };
        Grid.SetRow(input, 1); grid.Children.Add(input);
        results = new ListBox { FontSize = 13, Background = Color("#162233"), Foreground = Brushes.White, BorderThickness = new Thickness(0), Margin = new Thickness(0, 10, 0, 10) };
        ScrollViewer.SetHorizontalScrollBarVisibility(results, ScrollBarVisibility.Disabled);
        Grid.SetRow(results, 2); grid.Children.Add(results);
        var footer = new DockPanel();
        var select = new Button { Content = "切换", Padding = new Thickness(18, 5, 18, 5), Background = Color("#286B98"), Foreground = Brushes.White, BorderThickness = new Thickness(0), IsDefault = true };
        select.Click += (_, _) => Choose(); DockPanel.SetDock(select, Dock.Right); footer.Children.Add(select);
        status = new TextBlock { Text = "输入后选择结果，回车或双击切换", Foreground = Color("#91A6BF"), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
        footer.Children.Add(status); Grid.SetRow(footer, 3); grid.Children.Add(footer); Content = grid;
        input.TextChanged += (_, _) =>
        {
            generation++; cancellation?.Cancel(); searching = false; debounce.Stop(); ShowResults(SearchCatalog.Local(input.Text, config, recent));
            if (input.Text.Trim().Length > 0) debounce.Start();
        };
        debounce.Tick += async (_, _) => { debounce.Stop(); await Search(); };
        input.PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Down && results.Items.Count > 0) { results.Focus(); results.SelectedIndex = 0; e.Handled = true; }
        };
        results.MouseDoubleClick += (_, _) => Choose();
        PreviewKeyDown += (_, e) => { if (e.Key == Key.Escape) { Close(); e.Handled = true; } };
        ContentRendered += (_, _) => { ShowResults(SearchCatalog.Local("", config, recent)); input.Focus(); };
        Closed += (_, _) => { debounce.Stop(); cancellation?.Cancel(); cancellation?.Dispose(); };
    }
    private void ShowResults(IEnumerable<SearchCandidate> candidates)
    {
        results.ItemsSource = candidates.ToList();
        if (results.Items.Count > 0) results.SelectedIndex = 0;
    }
    private async System.Threading.Tasks.Task Search()
    {
        var query = input.Text.Trim(); var version = generation;
        if (query.Length == 0 || query.Length > 80) return;
        cancellation?.Dispose(); cancellation = new CancellationTokenSource();
        var token = cancellation.Token;
        status.Text = "正在搜索…";
        searching = true;
        var combined = SearchCatalog.Local(query, config, recent);
        try
        {
            var url = "https://query1.finance.yahoo.com/v1/finance/search?q=" + Uri.EscapeDataString(query) + "&quotesCount=12&newsCount=0";
            var json = await client.GetStringAsync(url, token);
            if (version != generation || !IsLoaded) return;
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("quotes", out var quotes))
                foreach (var q in quotes.EnumerateArray())
                {
                    if (!q.TryGetProperty("symbol", out var code)) continue;
                    var symbol = WatchlistParser.Normalize(code.GetString() ?? "");
                    if (symbol == null || combined.Any(c => c.Symbol == symbol)) continue;
                    var name = q.TryGetProperty("shortname", out var shortname) ? shortname.GetString() ?? symbol : symbol;
                    var market = q.TryGetProperty("exchDisp", out var exchange) ? exchange.GetString() ?? "" : "";
                    combined.Add(new SearchCandidate(symbol, name, market));
                }
            status.Text = "回车或双击选择；行情可能有延迟";
        }
        catch (OperationCanceledException) { if (version != generation || !IsLoaded) return; status.Text = "搜索超时，仍可直接输入股票代码"; }
        catch (Exception e) when (e is HttpRequestException || e is JsonException)
        { if (version != generation || !IsLoaded) return; status.Text = "网络搜索暂不可用，仍可使用自选或直接输入代码"; }
        if (version != generation || !IsLoaded) return;
        searching = false;
        var direct = WatchlistParser.Normalize(query);
        if (direct != null && !combined.Any(c => c.Symbol == direct)) combined.Add(new SearchCandidate(direct, "直接使用此代码", ""));
        ShowResults(combined);
    }
    private void Choose()
    {
        if ((searching || debounce.IsEnabled) && results.Items.Count == 0)
        { status.Text = "正在查找，请稍候选择搜索结果"; return; }
        var symbol = (results.SelectedItem as SearchCandidate)?.Symbol ?? WatchlistParser.Normalize(input.Text);
        if (symbol == null) { status.Text = "请选择结果，或输入有效股票代码"; return; }
        SelectedSymbol = symbol; Close();
    }
}
