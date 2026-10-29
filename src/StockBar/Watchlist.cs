using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace StockBar;

public sealed class WatchlistConfig
{
    public List<string> Symbols { get; set; } = new() { "WDC" };
    public int RotationSeconds { get; set; } = 5;
    public string Source { get; set; } = "本机列表";
    public Dictionary<string, string> Names { get; set; } = new();
    public Dictionary<string, string> Unsupported { get; set; } = new();
}

public static class WatchlistParser
{
    public static string? Normalize(string raw)
    {
        var s = raw.Trim().Trim('"', '\'').ToUpperInvariant();
        s = s switch { "US10Y.BD" => "^TNX", "CLMAIN.US" => "CL=F", ".KOSPI.KR" => "^KS11", "BTC.CC" => "BTC-USD", _ => s };
        if (s.StartsWith("US.")) s = s[3..];
        if (s.EndsWith(".US")) s = s[..^3];
        if (s.EndsWith(".SH")) s = s[..^3] + ".SS";
        if (s.EndsWith(".KR")) s = s[..^3] + ".KS";
        if (s.StartsWith("HK.")) s = s[3..].TrimStart('0').PadLeft(4, '0') + ".HK";
        if (s.StartsWith("SH.")) s = s[3..] + ".SS";
        if (s.StartsWith("SZ.")) s = s[3..] + ".SZ";
        if (s == "BRK.B" || s == "BRK.A") s = s.Replace('.', '-');
        if (new[] { "SYMBOL", "TICKER", "CODE", "NAME", "LATEST", "PRICE", "MARKET" }.Contains(s)) return null;
        if (!Regex.IsMatch(s, @"^(?:[A-Z^][A-Z0-9.^=\-]{0,24}|\d{1,6}\.[A-Z]{1,4})$")) return null;
        return s;
    }
    private static List<string> Cells(string line) => Regex.Matches(line, "\"(?:[^\"]|\"\")*\"|[^,\t]+")
        .Select(m => m.Value.Trim().Trim('"')).ToList();
    public static List<string> Parse(string text)
    {
        var lines = text.Trim('\uFEFF').Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
        if (lines.Length == 0) return new();
        var headers = Cells(lines[0]);
        var codeIndex = headers.FindIndex(h => h is "代码" or "股票代码" || h.Equals("symbol", StringComparison.OrdinalIgnoreCase) || h.Equals("ticker", StringComparison.OrdinalIgnoreCase));
        var result = new List<string>();
        void Add(string raw) { var symbol = Normalize(raw); if (symbol != null && !result.Contains(symbol)) result.Add(symbol); }
        if (codeIndex >= 0)
        {
            foreach (var line in lines.Skip(1)) { var cells = Cells(line); if (cells.Count > codeIndex) Add(cells[codeIndex]); }
        }
        else foreach (var raw in Regex.Split(text, @"[\s,;，；]+")) Add(raw);
        return result.Take(1000).ToList();
    }
}

public record SearchCandidate(string Symbol, string Name, string Market)
{
    public override string ToString() => Symbol + "  ·  " + Name + (string.IsNullOrWhiteSpace(Market) ? "" : "  ·  " + Market);
}

public static class SearchCatalog
{
    public static List<SearchCandidate> Local(string query, WatchlistConfig config, IEnumerable<string> recent)
    {
        query = query.Trim();
        return recent.Concat(config.Symbols).Distinct().Where(s => query.Length == 0 ||
            s.Contains(query, StringComparison.OrdinalIgnoreCase) ||
            config.Names.GetValueOrDefault(s, "").Contains(query, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(s => s.Equals(query, StringComparison.OrdinalIgnoreCase))
            .Take(30).Select(s => new SearchCandidate(s, config.Names.GetValueOrDefault(s, s), "自选 / 最近")).ToList();
    }
}
