"""Render paired throughput and resources from the exported complete workloads."""
from statistics import mean
from common import E,json

def export():
    rows=json.loads((E/"treatments.json").read_bytes())
    comps=json.loads((E/"comparisons.json").read_bytes())
    text=["# 端到端对照","本表仅使用逐行验收通过的完整生产，单 worker。时间单位为秒；速率按有效产出总数除以本 treatment 平均整任务 wall。"]
    text.append("| workload | 原版各遍 s | 纯批处理各遍 s | 倍率 | 有效根/对数 | 原版→批处理 有效根或对/s | 原版→批处理 C 或准入世界/s |\n|---|---|---|---:|---:|---|---|")
    def rates(data,key):
        if key not in data["totals"]:return "—"
        return " → ".join(f'{data["rates"][v][key]:.4f}' for v in ("original","batch"))
    for k in ("natural","pairs","initial-train","initial-dev","audit"):
        if k not in comps:continue
        d=comps[k];w=d["walls"]
        times=lambda v:", ".join(f"{x:.2f}" for x in w[v])
        text[-1]+=f"\n| {k} | {times('original')} | {times('batch')} | {d['speedup']:.4f} | {d['totals']['valid']} | {rates(d,'valid')} | {rates(d,'valid_C' if k=='natural' else 'admitted_worlds')} |"
    text.append("各遍次的真实动作数和完整策略数、每秒工作量、准入分母及逐次收据见 comparisons.json、treatments.json。")
    table=["| workload | 实现 | 遍数 | Python CPU s | 宿主 CPU s | Python 峰值 MiB | 宿主单进程峰值 MiB |","|---|---|---:|---:|---:|---:|---:|"]
    for k in ("natural","pairs","initial-train","initial-dev","audit"):
        for v in ("original","batch","reuse"):
            rr=[r for r in rows if r["kind"]==k and r["variant"]==v and r["success"] and
                (r["phase"].startswith("cross") or r["phase"] in ("bounded","cache-repeat"))]
            if rr:
                table.append(f"| {k} | {v} | {len(rr)} | {mean(r['python_cpu'] for r in rr):.2f} | {mean(r['host_cpu'] for r in rr):.2f} | {max(r['python_rss'] for r in rr)/2**20:.1f} | {max(r['host_rss'] for r in rr)/2**20:.1f} |")
    text.append("\n".join(table))
    (E/"tables.md").write_text("\n\n".join(text)+"\n",encoding="utf8")
if __name__=="__main__":export()
