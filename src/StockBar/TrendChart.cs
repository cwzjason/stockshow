using System;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;

namespace StockBar;
public sealed class TrendChart : FrameworkElement
{
    public Snapshot Snapshot { get; set; } = new();
    private Point? pointer;
    public TrendChart()
    {
        Height = 190;
        MouseMove += (_, e) => { pointer = e.GetPosition(this); InvalidateVisual(); };
        MouseLeave += (_, _) => { pointer = null; InvalidateVisual(); };
    }
    private static Brush Color(string value) => (Brush)new BrushConverter().ConvertFromString(value)!;
    private void Text(DrawingContext dc, string text, double x, double y, string color = "#8290A4", double size = 10)
        => dc.DrawText(new FormattedText(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
            new Typeface("Segoe UI"), size, Color(color), VisualTreeHelper.GetDpi(this).PixelsPerDip), new Point(x, y));
    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        var w = Math.Max(1, ActualWidth - 58); var h = 136d; var ox = 8d; var oy = 23d;
        dc.DrawRectangle(Brushes.Transparent, null, new Rect(0, 0, ActualWidth, ActualHeight));
        double X(double minute) => ox + minute / 1440 * w;
        dc.DrawRoundedRectangle(Color("#101927"), null, new Rect(ox, oy, w, h), 5, 5);
        dc.DrawRectangle(Color("#152A2A"), null, new Rect(X(570), oy, X(960) - X(570), h));
        dc.DrawRectangle(Color("#251F32"), null, new Rect(X(960), oy, X(1200) - X(960), h));
        foreach (var minute in new[] { 240, 570, 960, 1200 })
        {
            dc.DrawLine(new Pen(Color("#2A3445"), 1), new Point(X(minute), oy), new Point(X(minute), oy + h));
            Text(dc, TimeSpan.FromMinutes(minute).ToString(@"hh\:mm"), X(minute) - 12, oy + h + 7);
        }
        var plots = ChartMath.Project(Snapshot.Points ?? new(), w, h, Snapshot.PreviousClose);
        if (plots.Count == 0)
        {
            Text(dc, "等待 WDC 分时数据", ox + 140, oy + 56, "#ABB7C8", 13);
            return;
        }
        var (low, high) = ChartMath.Bounds(Snapshot.Points ?? new(), Snapshot.PreviousClose);
        for (int i = 0; i < 3; i++)
        {
            var y = oy + i * h / 2;
            dc.DrawLine(new Pen(Color("#273244"), .6), new Point(ox, y), new Point(ox + w, y));
            Text(dc, (high - (high - low) * i / 2).ToString("0.00", CultureInfo.InvariantCulture), ox + w + 6, y - 6);
        }
        if (Snapshot.PreviousClose is > 0)
        {
            var y = oy + (high - Snapshot.PreviousClose.Value) / (high - low) * h;
            dc.DrawLine(new Pen(Color("#7C8AA2"), 1) { DashStyle = DashStyles.Dash }, new Point(ox, y), new Point(ox + w, y));
        }
        var up = Snapshot.Price >= Snapshot.Reference;
        var line = new Pen(Color(up ? "#58DCAF" : "#FF8792"), 1.8);
        for (int i = 1; i < plots.Count; i++)
        {
            var a = plots[i - 1]; var b = plots[i];
            // Never draw a fake continuous line across missing trading periods.
            if ((ChartMath.ParseTime(b.Quote.Time)!.Value - ChartMath.ParseTime(a.Quote.Time)!.Value).TotalMinutes <= 5)
                dc.DrawLine(line, new Point(ox + a.X, oy + a.Y), new Point(ox + b.X, oy + b.Y));
        }
        var last = plots[^1];
        dc.DrawEllipse(line.Brush, null, new Point(ox + last.X, oy + last.Y), 2.5, 2.5);
        if (pointer is Point mouse)
        {
            var p = plots.MinBy(p => Math.Abs(p.X + ox - mouse.X))!;
            dc.DrawLine(new Pen(Color("#70819C"), 1) { DashStyle = DashStyles.Dot }, new Point(ox + p.X, oy), new Point(ox + p.X, oy + h));
            dc.DrawEllipse(Brushes.White, null, new Point(ox + p.X, oy + p.Y), 3, 3);
            Text(dc, $"{p.Quote.Time[11..16]} ET  ·  ${p.Quote.Price:0.00}  ·  {p.Quote.Session}", ox, 2, "#D5DFEA", 11);
        }
        else Text(dc, "盘前  /  盘中  /  盘后 · 虚线为昨收 · 时间为美东", ox, 2);
    }
}
