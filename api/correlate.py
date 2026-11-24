from http.server import BaseHTTPRequestHandler
import json, re, sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

def normalize(msg):
    s=str(msg).lower()
    s=re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b","<uuid>",s)
    s=re.sub(r"\b(trace|request|req|user|client|cb)[-_:= ]?[a-z0-9]{3,}\b",r"\1-<id>",s)
    s=re.sub(r"\b\d{4}-\d\d-\d\d[t ][\d:.+z-]+\b","<timestamp>",s)
    return re.sub(r"\s+"," ",re.sub(r"\b\d+(?:\.\d+)?\b","<n>",s)).strip()[:500]

def parse(line):
    if isinstance(line,dict):return line
    raw=str(line).strip()
    if not raw:return None
    try:
        obj=json.loads(raw)
        return obj if isinstance(obj,dict) else {"message":raw}
    except json.JSONDecodeError:
        p=raw.split(None,4)
        if len(p)>=5 and p[1].upper() in ("INFO","WARN","WARNING","ERROR","CRITICAL"):
            return {"timestamp":p[0],"level":p[1],"service":p[2],"endpoint":p[3],"message":p[4]}
        return {"message":raw}

def analyze(p):
    raw=p.get("rawLogs",[]); lines=raw if isinstance(raw,list) else str(raw).splitlines()
    parsed=[x for x in (parse(v) for v in lines[:10000]) if x]
    db=sqlite3.connect(":memory:")
    db.execute("CREATE TABLE logs(timestamp TEXT,level TEXT,service TEXT,endpoint TEXT,message TEXT,trace_id TEXT)")
    rows=[]
    for x in parsed:
        level=str(x.get("level") or "INFO").upper()
        if level=="WARNING":level="WARN"
        if level not in ("INFO","WARN","ERROR","CRITICAL"):level="INFO"
        rows.append((str(x.get("timestamp") or datetime.now(timezone.utc).isoformat()),level,str(x.get("service") or "unknown")[:100],str(x.get("endpoint") or "-")[:200],str(x.get("message") or x.get("msg") or "")[:4000],str(x.get("traceId") or x.get("trace_id") or "")[:160]))
    db.executemany("INSERT INTO logs VALUES(?,?,?,?,?,?)",rows); db.commit()
    names=("timestamp","level","service","endpoint","message","traceId")
    entries=[dict(zip(names,r)) for r in db.execute("SELECT * FROM logs ORDER BY timestamp DESC")]
    counts=Counter(x["level"] for x in entries); total=len(entries); errors=counts["ERROR"]+counts["CRITICAL"]
    pct=round(errors/total*100,1) if total else 0
    threshold=max(0,min(100,float(p.get("errorSpikeThresholdPct",15))))
    groups=defaultdict(list); endpoints=Counter(); traces=Counter()
    for x in entries:
        if x["level"] in ("ERROR","CRITICAL"):
            groups[normalize(x["message"])].append(x); endpoints[x["endpoint"]]+=1
            if x["traceId"]:traces[x["traceId"]]+=1
    clusters=[]
    for sig,items in groups.items():
        clusters.append({"signature":sig,"count":len(items),"sharePct":round(len(items)/max(errors,1)*100,1),"services":sorted({x["service"] for x in items}),"endpoints":sorted({x["endpoint"] for x in items}),"severity":"CRITICAL" if any(x["level"]=="CRITICAL" for x in items) else "ERROR"})
    clusters.sort(key=lambda x:x["count"],reverse=True)
    spike=errors>0 and pct>=threshold
    hypotheses=[{"title":c["signature"],"occurrences":c["count"],"confidence":min(98,55+c["count"]*4),"evidence":"Repeated signature across "+", ".join(c["services"]),"checks":["Inspect recent deploys and dependency health","Check endpoint latency, saturation and upstream timeouts","Correlate representative trace IDs with database and queue metrics"]} for c in clusters[:3]]
    if not hypotheses:hypotheses=[{"title":"No recurring error signature found","occurrences":0,"confidence":35,"evidence":"No ERROR or CRITICAL entries in this batch","checks":["Confirm log ingestion and severity mapping","Compare with the service baseline"]}]
    db.close()
    return {"streamId":p.get("streamId"),"totalLogs":total,"counts":dict(counts),"errorCount":errors,"errorPct":pct,"thresholdPct":threshold,"spikeDetected":spike,"status":"SPIKE_DETECTED" if spike else "NORMAL","clusters":clusters[:12],"topEndpoints":[{"endpoint":k,"count":v} for k,v in endpoints.most_common(8)],"topTraces":[{"traceId":k,"count":v} for k,v in traces.most_common(8)],"hypotheses":hypotheses,"entries":entries}

def send(h,status,data):
    body=json.dumps(data).encode(); h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8"); h.send_header("Cache-Control","no-store"); h.send_header("Access-Control-Allow-Origin","*"); h.send_header("Content-Length",str(len(body))); h.end_headers(); h.wfile.write(body)

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","POST,OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers()
    def do_POST(self):
        if self.path.split("?")[0]!="/api/correlate":return send(self,404,{"error":"Not found"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size>2000000:return send(self,413,{"error":"Payload too large"})
            p=json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(p,dict):return send(self,400,{"error":"Expected JSON object"})
            send(self,200,analyze(p))
        except (ValueError,TypeError) as e:send(self,400,{"error":"Invalid request","detail":str(e)})
    def log_message(self,*args):pass
