from http.server import BaseHTTPRequestHandler
import json, sqlite3
from datetime import datetime, timedelta, timezone

def ts(n=0):
    return (datetime.now(timezone.utc)-timedelta(minutes=n)).isoformat()

def seed(db):
    db.executescript("""CREATE TABLE IF NOT EXISTS log_streams(id TEXT PRIMARY KEY,name TEXT,service TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS log_entries(id INTEGER PRIMARY KEY,stream_id TEXT,timestamp TEXT,level TEXT,service TEXT,endpoint TEXT,message TEXT,trace_id TEXT);""")
    if db.execute("SELECT COUNT(*) FROM log_streams").fetchone()[0]: return
    presets=[("checkout-api-spike","Checkout API · DB pool exhaustion","checkout-api"),("worker-cron-healthy","Worker cron · healthy baseline","worker"),("auth-gateway-401-surge","Auth gateway · 401 surge","auth-gateway")]
    db.executemany("INSERT INTO log_streams VALUES(?,?,?,?)",[(a,b,c,ts()) for a,b,c in presets])
    rows=[]
    for i in range(24):
        level="ERROR" if i<17 else "INFO"
        msg=("database pool exhausted: acquire timeout after 3000ms request_id=req-%04d"%i) if i<12 else ("payment callback timeout trace_id=cb-%04d"%i if i<17 else "checkout completed")
        rows.append(("checkout-api-spike",ts(i),level,"checkout-api","/v1/checkout",msg,"tr-checkout-%d"%(i%4)))
    for i in range(18): rows.append(("worker-cron-healthy",ts(i*3),"INFO","worker","/jobs/reconcile","job completed duration_ms=%d"%(120+i*7),"tr-worker-%d"%i))
    for i in range(20): rows.append(("auth-gateway-401-surge",ts(i),"ERROR" if i<15 else "WARN","auth-gateway","/oauth/token","invalid token signature client_id=client-%03d"%i,"tr-auth-%d"%(i%6)))
    db.executemany("INSERT INTO log_entries(stream_id,timestamp,level,service,endpoint,message,trace_id) VALUES(?,?,?,?,?,?,?)",rows)
    db.commit()

def send(h,status,data):
    body=json.dumps(data).encode()
    h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8"); h.send_header("Cache-Control","no-store"); h.send_header("Access-Control-Allow-Origin","*"); h.send_header("Content-Length",str(len(body))); h.end_headers(); h.wfile.write(body)

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers()
    def do_GET(self):
        if self.path.split("?")[0]!="/api/streams": return send(self,404,{"error":"Not found"})
        db=sqlite3.connect(":memory:"); db.row_factory=sqlite3.Row; seed(db); result=[]
        for s in db.execute("SELECT * FROM log_streams"):
            entries=[dict(x) for x in db.execute("SELECT * FROM log_entries WHERE stream_id=? ORDER BY timestamp DESC",(s["id"],))]
            errors=sum(x["level"] in ("ERROR","CRITICAL") for x in entries)
            result.append({**dict(s),"entries":entries,"totalLogs":len(entries),"errorCount":errors,"errorPct":round(errors/len(entries)*100,1) if entries else 0})
        db.close(); send(self,200,{"streams":result,"engine":"active"})
    def do_POST(self):
        if self.path.split("?")[0]!="/api/streams": return send(self,404,{"error":"Not found"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size>2000000:return send(self,413,{"error":"Payload too large"})
            p=json.loads(self.rfile.read(size) or b"{}"); db=sqlite3.connect(":memory:"); seed(db)
            if p.get("reset"):
                db.execute("DELETE FROM log_entries"); db.execute("DELETE FROM log_streams"); seed(db)
            else:
                sid=str(p.get("streamId") or "custom-stream")[:100]; service=str(p.get("service") or "custom-service")[:100]
                db.execute("INSERT OR IGNORE INTO log_streams VALUES(?,?,?,?)",(sid,str(p.get("name") or "Custom log batch")[:160],service,ts()))
                raw=p.get("rawLogs",""); lines=raw if isinstance(raw,list) else str(raw).splitlines()
                for line in lines[:10000]:
                    try:item=json.loads(line) if isinstance(line,str) else line
                    except json.JSONDecodeError:item={"message":str(line)}
                    if not isinstance(item,dict):item={"message":str(item)}
                    db.execute("INSERT INTO log_entries(stream_id,timestamp,level,service,endpoint,message,trace_id) VALUES(?,?,?,?,?,?,?)",(sid,str(item.get("timestamp") or ts()),str(item.get("level") or "INFO").upper(),str(item.get("service") or service)[:100],str(item.get("endpoint") or "-")[:200],str(item.get("message") or item.get("msg") or "")[:4000],str(item.get("traceId") or item.get("trace_id") or "")[:160]))
            count=db.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0]; db.commit(); db.close(); send(self,200,{"ok":True,"totalLogs":count})
        except (ValueError,TypeError) as e:send(self,400,{"error":"Invalid request","detail":str(e)})
    def log_message(self,*args):pass
