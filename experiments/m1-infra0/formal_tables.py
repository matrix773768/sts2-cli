"""Regenerate numeric tables from validated treatment receipts."""
from collections import defaultdict
from statistics import mean,median
from profile_results import export,HERE

NAMES={"natural":"自然","pairs":"反事实","initial-train":"条件训练","initial-dev":"条件开发","audit":"独立复评"}
def table(cols,rows):
    return "\n".join(["| "+" | ".join(cols)+" |","|"+"---|"*len(cols)]+["| "+" | ".join(map(str,r))+" |" for r in rows])
def emit():
    records=export()
    blocks=[]
    def append(s):blocks.append(s)
    groups=defaultdict(list)
    for r in records:groups[r["kind"],r["arm"],r["n"]].append(r)
    throughput=[];cost=[];performance=[];profiles=[];margins=[];scaling=[];coverage=[]
    traversals=[];io=[];suffix_rows=[];fixed_rows=[];startup=[];strata=[]
    for (kind,arm,n),rs in groups.items():
        base=[r for r in rs if r["mode"]=="baseline"]
        agg=[r for r in rs if r["mode"]=="aggregate"]
        if not base:continue
        b=base[0];tot=b["totals"]
        target=NAMES[kind]+"/"+arm;wall=mean(r["wall_s"] for r in base)
        worker=mean(r["worker_s"] for r in base)
        if agg:
            traversals.append([target,", ".join(f"{r['wall_s']:.2f}" for r in base),", ".join(f"{r['wall_s']:.2f}" for r in agg)])
        startup.append([target,n,f"{min(b['first_s']):.2f}–{max(b['first_s']):.2f}",f"{b['steady_valid_per_worker_s']:.4f}",f"{max(b['after_last_flush_s']):.4f}"])
        if kind=="natural" and n==1:
            for label,v in sorted(b["strata"].items()):
                strata.append([arm,label,v["attempts"],v["valid"],v["valid_C"],v["actual_decisions"],f"{v['root_worker_seconds']:.2f}"])
        overhead=(mean(r["wall_s"] for r in agg)/wall-1)*100 if agg else None
        throughput.append([target,n,f"{len(base)}/{len(agg)}",f"{wall:.2f}",f"{mean(r['worker_s'] for r in base):.2f}",
            tot["valid"],f"{tot['valid']/wall:.4f}",f"{overhead:+.2f}%" if overhead is not None else "—"])
        performance.append([target,n,f"{mean(r['python_cpu_s'] for r in base):.2f}",f"{mean(r['host_cpu_s'] for r in base):.2f}",
            f"{max(m['python_peak'] for r in base for m in r['memory'])/2**20:.1f}",
            f"{max(m['host_peak'] for r in base for m in r['memory'])/2**20:.1f}",
            f"{max(r['inter_record_s']['p95'] for r in base):.2f}" if b["inter_record_s"] else "—",
            f"{min(b['worker_spans_s']):.1f}–{max(b['worker_spans_s']):.1f}"])
        if n>1:
            single=mean(r["wall_s"] for r in groups[kind,arm,1] if r["mode"]=="baseline")
            scaling.append([n,len(base),", ".join(f"{r['wall_s']:.2f}" for r in base),f"{wall:.2f}",f"{single/wall:.3f}",f"{100*single/wall/n:.1f}%",b["peak_workers"],"通过" if b["comparable"] else "存在差异"])
        if "admitted_worlds" in tot:
            coverage.append([NAMES[kind],tot["attempted_roots"],tot["valid"],tot["started_worlds"],tot["paired_worlds"],
                tot["locally_valid_worlds"],tot["admitted_worlds"],tot["returned_sides"],tot["terminal_sides"],
                f"{tot['admitted_worlds']/wall:.3f}",f"{worker/tot['admitted_worlds']:.3f}",f"{worker/tot['valid']:.3f}"])
        if not agg:continue
        a=agg[0];inc=a["inclusive_s"];t=a["wall_s"]
        share=lambda s:f"{100*s/t:.1f}%"
        rpc=a["rpc"];wait=sum(v["wait_s"] for v in rpc.values())
        profiles.append([target,share(wait),share(sum(v["handle"] for v in rpc.values())),
            share(sum(v["python_json"]+v["parse"]+v["serialize"] for v in rpc.values())),
            share(sum(v["residual_s"] for v in rpc.values())),share(inc.get("V2/encode",0)+inc.get("G2/encode",0)),
            share(inc.get("V2/forward",0)+inc.get("G2/forward",0)),share(inc.get("storage/json",0)+inc.get("gzip/write",0)+inc.get("gzip/flush",0))])
        res=a["resource_totals"]
        io.append([target,a["raw_bytes"],a["compressed_bytes"],f"{a['totals']['valid']*2**20/a['compressed_bytes']:.1f}",
            f"{a['exclusive_uncovered_s']:.2f}",
            "/".join(str(res[f"python_gc_{i}"]) for i in range(3)),"/".join(str(res[f"host_gc_{i}"]) for i in range(3)),
            f"{res['python_read_bytes']/2**20:.0f}/{res['python_write_bytes']/2**20:.0f}",
            f"{res['host_read_bytes']/2**20:.0f}/{res['host_write_bytes']/2**20:.0f}"])
        if not a.get("roots"):continue
        roots=a["roots"];m=a["marginal"]
        # Counts from the measured execution; aggregate and baseline rows use identical production records.
        suffix_rows.append([NAMES[kind],m["attempted_sides"],m["fight_n"],m["returned_fight_n"],m["nonempty_fight_n"],
            m["suffix_turns"],m["suffix_decisions"],m["suffix_sim_calls"],f"{m['fight_n']/t:.3f}",f"{m['nonempty_fight_n']/t:.3f}",
            f"{m['nonempty_fight_n']/a['worker_s']:.3f}"])
        fixed_rows.append([NAMES[kind],sum(r["fixed_restore_n"] for r in roots),m["side_root_creates"],m["prefix_actions"],
            f"{inc.get('conditions/natural_rows',0):.3f}",f"{inc.get('conditions/followup',0):.3f}",
            f"{sum(x['fixed_pair_s'] for x in roots):.4f}",f"{sum(x['fixed_compile_s'] for x in roots):.4f}",
            f"{m['shuffle_sent']:,}",f"{m['shuffle_received']:,}"])
        fix=sum(x["fixed_s"] for x in roots)
        cost.append([NAMES[kind],f"{t:.1f}",f"{fix:.1f}",f"{sum(x['fixed_menu_s'] for x in roots):.1f}",
            f"{m['pairs/restore_s']:.1f}",f"{m['shuffle_s']:.2f}",f"{m['verify_s']:.3f}",f"{m['conditions/initial_execute_s']:.1f}",
            f"{m['suffix_wall_s']:.1f} ({share(m['suffix_wall_s'])})",f"{m['lane/reset_s']:.1f}"])
        for count in sorted({r["count"] for r in roots}):
            rows=[r for r in roots if r["count"]==count]
            worlds=[v for r in rows for v in r["world_s"]]
            margins.append([NAMES[kind],count,len(rows),sum(r["valid"] for r in rows),len(worlds),
                f"{mean(r['fixed_s'] for r in rows):.2f}",f"{mean(worlds):.2f}" if worlds else "—",
                f"{median(worlds):.2f}" if worlds else "—",f"{max(worlds):.2f}" if worlds else "—"])
    append("## 正式生产与计量开销")
    append("wall 从任务启动计至完整 gzip 关闭可读。B/A 为完成的 Baseline/Aggregate 遍数；多遍取同一 treatment 的算术均值。有效数在自然、反事实与条件世界表中分别指有效战斗、完整对、整组准入的根。")
    append(table(["负载","worker","B/A","Baseline wall s","累计 worker s","有效数","有效数/wall s","Aggregate 开销"],throughput))
    append(table(["单 worker 对照","各遍 Baseline wall s","各遍 Aggregate wall s"],traversals))
    append(table(["负载","worker","Python CPU s","宿主 CPU s","单 Python 峰值 MiB","单宿主峰值 MiB","刷新间隔 P95 s¹","首遍各 worker 秒"],performance))
    append("¹ 报告各 Baseline 遍合并本遍 worker 间隔后的最大 P95。首根另外保存，各进程峰值可能发生在不同时间。")
    append(table(["首遍 Baseline","worker","首根刷新范围 s","首根后有效数/worker s","末次刷新至关闭最长 s"],startup))
    append(table(["自然预算","冻结层","尝试数","有效数","实际 C","决策","首遍根内累计 s"],strata))
    density=[]
    for (kind,arm,n),rs in groups.items():
        base=[r for r in rs if r["mode"]=="baseline"]
        if not base:continue
        b=base[0];wall=mean(r["wall_s"] for r in base);worker=mean(r["worker_s"] for r in base)
        t=b["totals"]
        for k in (("valid_C","decisions","full_policies") if kind=="natural" else ("complete_conditional_plans","matched_realized_sides") if kind=="pairs" else ("admitted_worlds",)):
            density.append([kind+"/"+arm,n,k,t[k],f"{t[k]/wall:.3f}",f"{t[k]/worker:.3f}"])
    append(table(["workload","worker","quantity","count","/wall s","/worker s"],density))
    if scaling:
        append(table(["worker","遍数","各遍 wall s","均值 s","吞吐倍率","并行效率","实测并发峰值","逐行语义"],scaling))
    append("## 条件世界的准入与分阶段成本")
    append(table(["负载","尝试根","有效根","启动世界","双侧返回","局部有效","整根准入世界","返回方案","取得终局","准入世界/wall s","worker s/准入世界","worker s/有效根"],coverage))
    append("以下阶段取每种负载的第一遍 Aggregate。固定成本含选择根、必要的前缀恢复与 menu；menu 已包含在固定成本内。侧内 restore 含建根、公开历史重建和前缀 step。该列与固定阶段中的 restore 分开。")
    append(table(["负载","总 wall s","固定 s","其中 menu s","侧内 restore s","重排 s","验证 s","首方案执行 s","V2 续战 s（占 wall）","侧内 reset s"],cost))
    append(table(["负载","原配额","根","有效根","启动世界","每根固定 s","边际均值 s/世界","中位 s","最大 s"],margins))
    append("配额 0 表示未取得可执行方案。每世界边际是已尝试侧的区间和，含中途失败侧。世界间 seed 哈希及循环切换留在整根 wall。4/8/12 组的根及续战长度分布不同。")
    append(table(["负载","实际方案侧尝试","fight 调用","续战返回","有实际决策的续战","搜索回合/查询","续战决策","模拟调用","fight/wall s","有决策续战/wall s","有决策续战/worker s"],suffix_rows))
    append("续战表的计数及分母均来自同一首遍 Aggregate。到达终局后调用 fight 可立即返回。发生异常的调用计入次数及耗时，逐回合工作量仅计成功返回的 fight；每个有搜索的实际回合一次 planner 查询。")
    append(table(["负载","候选回合 restore 次数","世界侧新建根","世界侧重放步数","建父轨迹索引 s","历史复评筛选 s","固定 pair s","固定 option/program s","重排发送 B","重排接收 B"],fixed_rows))
    append("option/program 是 menu 内的候选编译计量，pair 是选择两条候选，源分片扫描包含解压和逐行反序列化。整根、逐侧原始阶段还保存宿主 project、前缀 step、目标回合、重排牌数及推理计数。")
    inference=[]
    for (kind,arm,n),runs in groups.items():
        a=next((r for r in runs if r["mode"]=="aggregate" and r.get("marginal",{}).get("inference_sampled_fights")),None)
        if a:
            m=a["marginal"]
            inference.append([NAMES[kind],m["inference_sampled_fights"],m["suffix_G2/forward/n"],
                f"{m['suffix_G2/forward/s']:.3f}",m["suffix_V2/forward/n"],f"{m['suffix_V2/forward/s']:.3f}",
                f"{m['suffix_G2/encode/s']:.3f}",f"{m['suffix_V2/encode/s']:.3f}"])
    if inference:
        append(table(["反向 Aggregate","fight 样本","G2 前向次数","G2 前向 s","V2 前向次数","V2 前向 s","G2 编码 s","V2 编码 s"],inference))
        append("首遍按整个方案侧累计推理。反向 Aggregate 在同一已有 fight 入口和返回处加计数差，表内推理只含续战，异常退出也采样。")
    append("## 热点分解")
    append(table(["负载","RPC 总等待","其中宿主 handle","两端 JSON","有符号 residual","G2+V2 编码","网络 forward","JSON/gzip 写出²"],profiles))
    append("² 写出列取记录序列化、gzip 的 write 与 flush，底层压缩和文件写已嵌套。宿主 parse、handle 和 serialize 来自同一宿主命令；residual 含同步等待、传输、缓冲、未覆盖工作及测量边界差异。表中嵌套列不求和。")
    append(table(["首遍 Aggregate","记录 JSONL B","gzip B","有效根或对/MiB","Python 未覆盖 s","Python GC 0/1/2","宿主 GC 0/1/2","Python 读/写 MiB","宿主读/写 MiB"],io))
    append("未覆盖时间为进程累计 wall 减去 Python 同步计量栈排他耗时之和，含启动、清理及未包裹代码。Windows 进程 I/O 同时包含管道与缓存。GC 为各代收集次数。")
    (HERE/"evidence/formal/tables.md").write_text("\n\n".join(blocks)+"\n",encoding="utf8")
if __name__=="__main__":emit()
