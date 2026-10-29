using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;

namespace StockBar;

public static class TickerLayout
{
    public const double Width = 276, Height = 32, PanelHeight = 315;
    public static (double Left, double Top) Default(double screenWidth, double screenHeight, double workBottom)
    {
        var taskbarHeight = Math.Max(0, screenHeight - workBottom);
        var top = taskbarHeight >= Height ? workBottom + (taskbarHeight - Height) / 2 : screenHeight - Height - 2;
        return (Math.Min(120, Math.Max(0, screenWidth - Width)), top);
    }
    public static double ExpandedTop(double compactTop) => Math.Max(0, compactTop - PanelHeight);
}

public record QuotePoint(string Time, double Price, string Session);
public record PlotPoint(double X, double Y, QuotePoint Quote);
public record Snapshot
{
    public string Symbol { get; init; } = "";
    public string Currency { get; init; } = "USD";
    public bool Connected { get; init; }
    public bool Available { get; init; } = true;
    public double? Price { get; init; }
    public double? Reference { get; init; }
    public double? PreviousClose { get; init; }
    public double? ChangePercent { get; init; }
    public string Session { get; init; } = "等待行情";
    public string QuoteTime { get; init; } = "";
    public string ChartDate { get; init; } = "";
    public string Source { get; init; } = "公开行情";
    public string Message { get; init; } = "正在获取 WDC 行情…";
    public DateTimeOffset FetchedAt { get; init; }
    public List<QuotePoint> Points { get; init; } = new();
    public static JsonSerializerOptions JsonOptions { get; } = new() { PropertyNameCaseInsensitive = true };
    public bool IsStale(DateTimeOffset now) => !Connected || now - FetchedAt > TimeSpan.FromSeconds(30) || FetchedAt > now.AddMinutes(1);
    public bool HasPrice => Price is > 0 && double.IsFinite(Price.Value);
    public string DisplayPrice => !HasPrice ? "—" : Currency switch
    {
        "KRW" => "₩" + Price!.Value.ToString("N0", CultureInfo.InvariantCulture),
        "CNY" => "¥" + Price!.Value.ToString("0.00", CultureInfo.InvariantCulture),
        "HKD" => "HK$" + Price!.Value.ToString("0.00", CultureInfo.InvariantCulture),
        "YIELD" => Price!.Value.ToString("0.000", CultureInfo.InvariantCulture) + "%",
        "USD" => Price!.Value.ToString("$0.00", CultureInfo.InvariantCulture),
        _ => Price!.Value.ToString("0.00", CultureInfo.InvariantCulture)
    };
    public string DisplayChange => HasPrice && ChangePercent is double value && double.IsFinite(value)
        ? value.ToString("+0.00;-0.00;0.00", CultureInfo.InvariantCulture) + "%" : "—";
}

public static class SessionStyle
{
    // Only a session the source actually confirmed may wear a live colour.
    public static (string Back, string Fore) For(string label) => label switch
    {
        "盘中" => ("#1E3A33", "#58DCAF"),
        "全天" => ("#1E3A33", "#58DCAF"),
        "盘前" => ("#3B3324", "#E8C46C"),
        "盘后" or "夜盘" => ("#2E2A3C", "#B79CE8"),
        _ => ("#2A2E36", "#8FA2B8")
    };
}

public sealed class MarketFeed
{
    public Dictionary<string, Snapshot> Quotes { get; init; } = new();
    public Snapshot ForSymbol(string symbol) => Quotes.TryGetValue(symbol, out var s) && s.Symbol == symbol ? s :
        new Snapshot { Symbol = symbol, Message = "正在获取 " + symbol + " 行情…" };
}

public static class ChartMath
{
    public static (double Low, double High) Bounds(IEnumerable<QuotePoint> points, double? reference)
    {
        var values = points.Where(p => double.IsFinite(p.Price) && p.Price > 0).Select(p => p.Price).ToList();
        if (reference is > 0 && double.IsFinite(reference.Value)) values.Add(reference.Value);
        if (values.Count == 0) return (0, 1);
        var low = values.Min(); var high = values.Max();
        var pad = Math.Max((high - low) * .12, high * .001);
        return (low - pad, high + pad);
    }
    public static List<PlotPoint> Project(IEnumerable<QuotePoint> points, double width, double height, double? reference)
    {
        var clean = points.Where(p => p.Price > 0 && double.IsFinite(p.Price) && ParseTime(p.Time) != null).OrderBy(p => p.Time, StringComparer.Ordinal).ToList();
        var (low, high) = Bounds(clean, reference);
        return clean.Select(p => new PlotPoint(ParseTime(p.Time)!.Value.TimeOfDay.TotalMinutes / 1440 * width,
            (high - p.Price) / (high - low) * height, p)).ToList();
    }
    public static DateTime? ParseTime(string value) => DateTime.TryParseExact(value, "yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture, DateTimeStyles.None, out var t) ? t : null;
}
