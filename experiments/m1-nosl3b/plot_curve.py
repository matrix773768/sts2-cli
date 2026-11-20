"""Write a standalone plot of the frozen learning curves (requires Plotly)."""
import argparse
import json
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots


def main(summary, output):
    data = json.loads(summary.read_bytes())
    stages = sorted({int(key.split(":")[0]) for key in data["report"] if not key.startswith("reference")})
    names = {"mechanism": ("机制与条件关系", "#245c96"),
             "id": ("ID-only", "#a05a11"), "no_relation": ("去关系层", "#348168")}
    figures = [
        ("Sample 胜率", "sample", "wins_per_attempt"),
        ("Greedy 胜率", "greedy", "wins_per_attempt"),
        ("Sample 胜利加权 HP", "sample", "weighted_hp"),
        ("Greedy 胜利加权 HP", "greedy", "weighted_hp"),
    ]
    fig = make_subplots(rows=2, cols=2, subplot_titles=[x[0] for x in figures])
    any_model = next(iter(data["train"]["1"]["updates"]))
    budget = [sum(data["train"][str(u)]["updates"][any_model]["attempt_stats"]["attempts"]
                  for u in range(1, step + 1)) for step in stages]
    for i, (_, mode, metric) in enumerate(figures):
        row, col = i // 2 + 1, i % 2 + 1
        for name, (label, color) in names.items():
            stats = [data["report"][f"{step}:{name}:{mode}"] for step in stages]
            mid = [x["overall"][metric] for x in stats]
            lows = [min(s[metric] for s in x["by_seed"].values()) for x in stats]
            highs = [max(s[metric] for s in x["by_seed"].values()) for x in stats]
            fig.add_trace(go.Scatter(x=budget, y=mid, name=label, legendgroup=name,
                                     mode="lines+markers", line=dict(color=color), showlegend=i == 0,
                                     error_y=dict(type="data", symmetric=False,
                                                  array=[abs(h-y) for h, y in zip(highs, mid, strict=True)],
                                                  arrayminus=[abs(y-l) for y, l in zip(mid, lows, strict=True)])),
                          row=row, col=col)
        fig.update_xaxes(title_text="每个模型累计尝试数", tickmode="array", tickvals=budget, row=row, col=col)
        fig.update_yaxes(tickformat=".0%", rangemode="tozero", row=row, col=col)
    fig.update_layout(title="M1-NOSL3B 学习曲线（误差线为三个初始化的范围）", height=720,
                      template="plotly_white", legend=dict(orientation="h", y=-.16))
    fig.write_html(output, include_plotlyjs=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("summary", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    main(args.summary, args.output)
