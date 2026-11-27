"""One synchronous production worker. The engine reader threads never enter the timer stack."""
from collections import Counter, OrderedDict
from functools import wraps
import json
from time import perf_counter_ns as clock
from types import SimpleNamespace


class Meter:
    def __init__(self):
        self.values = Counter()
        self.stack = []
        self.command = "startup"
        self.roots = []

    def timed(self, name, fn, *args, **kw):
        start = clock()
        frame = [0]
        self.stack.append(frame)
        try:
            return fn(*args, **kw)
        finally:
            elapsed = clock()-start
            self.stack.pop()
            self.values[name+"/n"] += 1
            self.values[name+"/ns"] += elapsed
            self.values[name+"/self_ns"] += elapsed-frame[0]
            if self.stack:
                self.stack[-1][0] += elapsed

    def wrap(self, owner, name, label):
        fn = getattr(owner, name)
        @wraps(fn)
        def wrapped(*args, **kw):
            return self.timed(label, fn, *args, **kw)
        setattr(owner, name, wrapped)

    def install(self, battle, experience):
        import complete, options5d, search5, semantic, play_loop, deploy5b, loop_battle
        import gzip, sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).resolve().parents[1]/"m1-pre0b"))
        import transport
        from panel5d import cohort

        request = battle.Lane.request
        def rpc(lane, command, **kw):
            self.command = command
            label = "rpc/"+command+("/"+kw["mode"] if "mode" in kw else "")
            if "route" in kw:
                self.values[label+"/prefix/"+str(len(kw["route"]))] += 1
            result = self.timed(label, request, lane, command, **kw)
            for k,ms in result.get("_b1a_ms",{}).items():
                self.values["host_probe/"+command+"/"+k+"/ns"] += round(ms*1e6)
            return result
        battle.Lane.request = rpc
        def dumps(cmd):
            wire = self.timed("rpc_json/send/"+self.command,json.dumps,cmd)
            # ensure_ascii is the transport default and LF is appended by _send.
            self.values["bytes_sent/"+self.command] += len(wire)+1
            return wire
        transport.json = SimpleNamespace(dumps=dumps)
        def loads(line):
            size = len(line)
            self.values["bytes_received/"+self.command] += size
            self.values["response_size_log2/"+self.command+"/"+str(size.bit_length()-1)] += 1
            return self.timed("rpc_json/recv/"+self.command,json.loads,line)
        factory=loop_battle.Host._client
        def client(host):
            cls=factory(host)
            # The engine module is created afresh by some legacy binders.
            original=cls._read
            from types import FunctionType
            cls._read=FunctionType(original.__code__,original.__globals__|{"json":SimpleNamespace(loads=loads)})
            return cls
        loop_battle.Host._client=client

        meter=self
        class HitCache(OrderedDict):
            def __contains__(self,key):
                found=super().__contains__(key)
                if found:meter.values["V2/prior_cache_hits"]+=1
                return found
        evaluator_init=search5.Evaluator.__init__
        def init_eval(obj,net):
            evaluator_init(obj,net)
            obj.cache=HitCache()
        search5.Evaluator.__init__=init_eval
        def read_rows(path):
            self.values["parents/files_opened"]+=1
            self.values["parents/compressed_bytes"]+=path.stat().st_size
            for row in original_rows(path):
                self.values["parents/rows_decoded"]+=1
                yield row
        original_rows=experience.rows
        experience.rows=read_rows
        # Attribute generator execution only while advancing it.
        def timed_rows(path):
            it=read_rows(path)
            while True:
                try: row=self.timed("parents/read_decode",next,it)
                except StopIteration:return
                yield row
        experience.rows=timed_rows
        base_eval = search5.Evaluator.__call__
        def evaluate(obj, states, opening):
            h,m=obj.hits,obj.misses
            try:return self.timed("V2/evaluate",base_eval,obj,states,opening)
            finally:
                self.values["V2/cache_hits_including_batch"]+=obj.hits-h
                self.values["V2/forward_inputs"]+=obj.misses-m
                if obj.misses>m:self.values["V2/batch/"+str(obj.misses-m)]+=1
        search5.Evaluator.__call__=evaluate
        for obj,names,label in [
            (battle.Lane,"open reset close","lane"),(battle,"configure fight","natural"),
            (experience,"sample restore realize menu pair fight","pairs"),(cohort,"start","world"),
            (complete,"graph_plan reference execute_program combine program","search"),
            (complete.Turn,"search score","turn"),(complete.Planner,"__call__","plan"),
            (play_loop,"prepared execute step","execution"),(search5,"encode pack expected","V2"),
            (semantic,"static_rules","V2"),(search5,"sha256","V2"),(deploy5b,"load_net","model"),(semantic.Value,"forward","V2"),
            (options5d,"program","option"),(cohort.Controller,"score act","G2"),
            (gzip.GzipFile,"write flush close","gzip"),
        ]:
            for name in names.split(): self.wrap(obj,name,label+"/"+name)

        self.wrap(experience,"step","restore/replayed_action")
        configure=battle.configure
        def configure_meter(*a,**kw):
            host,g2,net,plan=configure(*a,**kw)
            self.wrap(host,"project","project")
            forward=g2.net.forward
            def score_batch(batch):
                size=next(iter(batch.values())).shape[0]
                self.values["G2/batch/"+str(size)]+=1
                self.values["G2/forward_inputs"]+=size
                return self.timed("G2/forward",forward,batch)
            g2.net.forward=score_batch
            self.wrap(g2.encoder,"encode","G2/encode")
            return host,g2,net,plan
        battle.configure=experience.configure=configure_meter

        class StreamProbe:
            def __init__(self,inner,methods,prefix):
                self.inner=inner
                for name in methods:
                    method=getattr(inner,name)
                    setattr(self,name,lambda *args,fn=method,key=prefix+"/"+name:self.timed_call(key,fn,args))
            def timed_call(self,key,fn,args):
                if key=="file/write":meter.values["storage/file_write_bytes"]+=len(args[0])
                return meter.timed(key,fn,*args)
            def __getattr__(self,name):
                return getattr(self.inner,name)
        original_open=gzip.open
        def open_stream(path,mode,**kw):
            stream=original_open(path,mode,**kw)
            if mode=="xt":
                raw=stream.buffer
                raw.compress=StreamProbe(raw.compress,["compress","flush"],"zlib")
                raw.fileobj=StreamProbe(raw.fileobj,["write","flush"],"file")
            return stream
        battle.gzip=experience.gzip=SimpleNamespace(open=open_stream)
        def record(obj,**kw):
            wire=self.timed("storage/json",json.dumps,obj,**kw)
            if isinstance(obj,dict) and "i" in obj:
                self.values["storage/raw_bytes"]+=len(wire)+1
                self.roots.append((obj["i"],clock(),dict(self.values)))
            return wire
        battle.json=experience.json=SimpleNamespace(dumps=record)
