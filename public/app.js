const $=id=>document.getElementById(id);
const state={streams:[],result:null,filter:"ALL",backend:false};
const escapeHtml=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const demo=()=>Array.from({length:24},(_,i)=>JSON.stringify({timestamp:new Date(Date.now()-i*18000).toISOString(),level:i<17?(i%7===0?"CRITICAL":"ERROR"):"INFO",service:"checkout-api",endpoint:"/v1/checkout",message:i<12?"database pool exhausted: acquire timeout after 3000ms request_id=req-"+(4100+i):i<17?"payment callback timeout trace_id=cb-"+(900+i):"checkout completed",traceId:"trace-"+(i%5)+"-"+(8000+i)}));
const fallback=[
{id:"checkout-api-spike",name:"Checkout API · DB pool exhaustion",entries:demo()},
{id:"worker-cron-healthy",name:"Worker cron · healthy baseline",entries:Array.from({length:18},(_,i)=>JSON.stringify({timestamp:new Date().toISOString(),level:"INFO",service:"worker",endpoint:"/jobs/reconcile",message:"job completed duration_ms="+(120+i*5),traceId:"worker-"+i}))},
{id:"auth-gateway-401-surge",name:"Auth gateway · 401 surge",entries:Array.from({length:20},(_,i)=>JSON.stringify({timestamp:new Date().toISOString(),level:i<15?"ERROR":"WARN",service:"auth-gateway",endpoint:"/oauth/token",message:"invalid token signature client_id=client-"+i,traceId:"auth-"+i}))}
];
async function api(path,options={}){const r=await fetch(path,{headers:{"Content-Type":"application/json"},...options});if(!r.ok)throw Error("API "+r.status);return r.json()}
function notice(s,bad=false){$("notice").textContent=s;$("notice").style.color=bad?"#fb7185":"#718096"}
function setRaw(v){$("rawLogs").value=v;$("lineCount").textContent=v.split("\n").filter(Boolean).length+" LINES"}
function selectStreams(list){state.streams=list;$("streamSelect").innerHTML=list.map(s=>'<option value="'+escapeHtml(s.id)+'">'+escapeHtml(s.name)+'</option>').join("");}
function loadSelected(){const s=state.streams.find(x=>x.id===$("streamSelect").value)||state.streams[0];if(s)setRaw((s.entries||[]).map(x=>typeof x==="string"?x:JSON.stringify(x)).join("\n"))}
function localAnalyze(raw,threshold){
 const entries=raw.split("\n").filter(Boolean).map(line=>{try{return JSON.parse(line)}catch{const p=line.trim().split(/\s+/,5);return p.length>=5?{timestamp:p[0],level:p[1],service:p[2],endpoint:p[3],message:p[4]}:{message:line}}}).map(x=>({timestamp:x.timestamp||new Date().toISOString(),level:String(x.level||"INFO").toUpperCase(),service:x.service||"unknown",endpoint:x.endpoint||"-",message:x.message||x.msg||"",traceId:x.traceId||x.trace_id||""}));
 const counts={INFO:0,WARN:0,ERROR:0,CRITICAL:0},groups={},endpoints={},traces={};
 entries.forEach(x=>{if(x.level==="WARNING")x.level="WARN";if(!Object.hasOwn(counts,x.level))x.level="INFO";counts[x.level]++;if(["ERROR","CRITICAL"].includes(x.level)){const sig=String(x.message).toLowerCase().replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/g,"<uuid>").replace(/\b(trace|request|req|user|client|cb)[-_:= ]?[a-z0-9]{3,}\b/g,"$1-<id>").replace(/\b\d+(?:\.\d+)?\b/g,"<n>").replace(/\s+/g," ").trim();(groups[sig]??=[]).push(x);endpoints[x.endpoint]=(endpoints[x.endpoint]||0)+1;if(x.traceId)traces[x.traceId]=(traces[x.traceId]||0)+1}});
 const errors=counts.ERROR+counts.CRITICAL,pct=entries.length?+(errors/entries.length*100).toFixed(1):0;
 const clusters=Object.entries(groups).map(([signature,items])=>({signature,count:items.length,sharePct:+(items.length/Math.max(errors,1)*100).toFixed(1),services:[...new Set(items.map(x=>x.service))],endpoints:[...new Set(items.map(x=>x.endpoint))],severity:items.some(x=>x.level==="CRITICAL")?"CRITICAL":"ERROR"})).sort((a,b)=>b.count-a.count);
 const top=(obj,key)=>Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,8).map(([k,v])=>({[key]:k,count:v}));
 return {totalLogs:entries.length,counts,errorCount:errors,errorPct:pct,thresholdPct:threshold,spikeDetected:errors>0&&pct>=threshold,status:errors>0&&pct>=threshold?"SPIKE_DETECTED":"NORMAL",clusters,topEndpoints:top(endpoints,"endpoint"),topTraces:top(traces,"traceId"),hypotheses:clusters.slice(0,3).map(c=>({title:c.signature,occurrences:c.count,confidence:Math.min(98,55+c.count*4),evidence:"Repeated signature across "+c.services.join(", "),checks:["Inspect recent deploys and dependency health","Check endpoint latency, saturation and upstream timeouts","Correlate representative traces with database and queue metrics"]})),entries};
}
function render(r){
 state.result=r;$("totalLogs").textContent=r.totalLogs.toLocaleString();$("errorRate").textContent=r.errorPct+"%";$("signatureCount").textContent=r.clusters.length;$("spikeStatus").textContent=r.status;$("spikeStatus").className=r.spikeDetected?"":"green";$("spikeStatus").style.color=r.spikeDetected?"#f43f5e":"#10b981";$("thresholdLabel").textContent="Threshold: "+r.thresholdPct+"%";
 $("clusters").className="";$("clusters").innerHTML=r.clusters.length?r.clusters.map(c=>'<article class="cluster"><div class="clusterhead"><div class="signature">'+escapeHtml(c.signature)+'</div><span class="severity '+c.severity+'">'+c.severity+'</span></div><div class="clusterMeta"><span><b>'+c.count+'</b> occurrences</span><span><b>'+c.sharePct+'%</b> of errors</span><span>'+escapeHtml(c.services.join(", "))+'</span><span>'+escapeHtml(c.endpoints.join(", "))+'</span></div></article>').join(""):'<div class="empty">No recurring error signatures found.</div>';
 $("endpoints").innerHTML=r.topEndpoints.length?r.topEndpoints.map(x=>'<div class="offender"><span>'+escapeHtml(x.endpoint)+'</span><b>'+x.count+'</b></div>').join(""):'<div class="empty">No failing endpoints.</div>';
 const hypotheses=r.hypotheses?.length?r.hypotheses:[{title:"No recurring error signature found",occurrences:0,confidence:35,evidence:"No matching errors",checks:["Confirm log ingestion and severity mapping","Compare with baseline"]}];
 $("triage").innerHTML=hypotheses.map(h=>'<article class="hypothesis"><strong>'+escapeHtml(h.title)+'</strong><p>'+h.occurrences+' matching events · '+h.confidence+'% heuristic confidence<br>'+escapeHtml(h.evidence)+'</p><ul>'+h.checks.map(c=>'<li>'+escapeHtml(c)+'</li>').join("")+'</ul></article>').join("");renderRows();
}
function renderRows(){if(!state.result)return;const rows=state.result.entries.filter(x=>state.filter==="ALL"||(state.filter==="ERROR"?["ERROR","CRITICAL"].includes(x.level):x.level===state.filter));$("logRows").innerHTML=rows.length?rows.slice(0,250).map(x=>'<tr><td>'+escapeHtml(String(x.timestamp).replace("T"," ").slice(0,19))+'</td><td><span class="level '+escapeHtml(x.level)+'">'+escapeHtml(x.level)+'</span></td><td>'+escapeHtml(x.service)+'<br><span style="color:#22d3ee">'+escapeHtml(x.endpoint)+'</span></td><td>'+escapeHtml(x.message)+'</td><td>'+escapeHtml(x.traceId||"—")+'</td></tr>').join(""):'<tr><td colspan="5" class="empty">No matching entries.</td></tr>'}
async function analyze(){
 const raw=$("rawLogs").value,threshold=Number($("threshold").value);if(!raw.trim())return notice("Add log lines before running analysis.",true);if(!Number.isFinite(threshold)||threshold<0||threshold>100)return notice("Threshold must be between 0 and 100.",true);
 $("analyzeBtn").disabled=true;$("analyzeBtn").textContent="Analyzing…";
 try{const r=state.backend?await api("/api/correlate",{method:"POST",body:JSON.stringify({streamId:$("streamSelect").value,rawLogs:raw,errorSpikeThresholdPct:threshold})}):localAnalyze(raw,threshold);render(r);notice((state.backend?"Python + SQLite":"Offline fallback")+" analysis complete · "+r.totalLogs+" entries · "+r.clusters.length+" signatures")}
 catch(e){notice("API unavailable; local analyzer used. "+e.message,true);render(localAnalyze(raw,threshold))}
 finally{$("analyzeBtn").disabled=false;$("analyzeBtn").textContent="Correlate logs →"}
}
async function init(){
 $("streamSelect").addEventListener("change",loadSelected);$("rawLogs").addEventListener("input",()=>$("lineCount").textContent=$("rawLogs").value.split("\n").filter(Boolean).length+" LINES");$("analyzeBtn").addEventListener("click",analyze);
 $("loadSpike").addEventListener("click",()=>{$("streamSelect").value="checkout-api-spike";loadSelected();analyze()});
 $("resetBtn").addEventListener("click",async()=>{try{if(state.backend)await api("/api/streams",{method:"POST",body:JSON.stringify({reset:true})});selectStreams(fallback);$("streamSelect").value="checkout-api-spike";loadSelected();notice("Demo streams reset.")}catch(e){notice("Local demo reset: "+e.message,true)}});
 $("filters").addEventListener("click",e=>{const b=e.target.closest("[data-filter]");if(!b)return;state.filter=b.dataset.filter;document.querySelectorAll(".filter").forEach(x=>x.classList.toggle("active",x===b));renderRows()});
 try{const d=await api("/api/streams");state.backend=true;$("engineState").textContent="ACTIVE";selectStreams(d.streams);notice("Connected to Python + SQLite engine · "+d.streams.length+" seeded streams.")}
 catch(e){state.backend=false;$("engineState").textContent="LOCAL MODE";selectStreams(fallback);notice("API unavailable; browser fallback is ready.",true)}
 $("streamSelect").value="checkout-api-spike";loadSelected();await analyze();
}
document.addEventListener("DOMContentLoaded",init);
