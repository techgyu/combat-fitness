"use strict";
const $ = id => document.getElementById(id);
const state = {page:1, pageSize:12, selected:null, detail:null, listRequest:0, detailRequest:0};
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{"Content-Type":"application/json", ...options.headers}});
  const body = await response.json();
  if (!response.ok) {
    const details = (body.error?.details || []).map(x => x.field + ": " + x.message).join("\n");
    throw new Error((body.error?.message || "요청에 실패했습니다.") + (details ? "\n" + details : ""));
  }
  return body;
}
function notify(message, error=false) { $("notice").hidden = !message; $("notice").textContent=message; $("notice").classList.toggle("error",error); }
function time(value) { const seconds=Math.round(value); return Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0"); }
function signed(value, unit) {return (value>0?"+":"")+value+" "+unit;}
async function list() {
  const request=++state.listRequest;
  const params=new URLSearchParams({page:state.page,page_size:state.pageSize,q:$("search").value,source:$("source").value});
  const data=await api("/api/v1/soldiers?"+params);
  if(request!==state.listRequest)return;
  $("syntheticCount").textContent=(data.source_counts.synthetic||0).toLocaleString();
  $("webCount").textContent=(data.source_counts.web||0).toLocaleString();
  $("soldierList").replaceChildren();
  for(const row of data.items){
    const tr=document.createElement("tr");tr.dataset.id=row.soldier_id;tr.classList.toggle("selected",row.soldier_id===state.selected);
    const cell=document.createElement("td"),button=document.createElement("button");
    button.textContent=row.soldier_id;button.type="button";button.addEventListener("click",()=>select(row.soldier_id).catch(e=>notify(e.message,true)));
    cell.append(button);tr.append(cell);
    for(const value of [row.age+"세",row.source==="web"?"직접 입력":"합성"]){const td=document.createElement("td");td.textContent=value;tr.append(td);}
    $("soldierList").append(tr);
  }
  if(!data.items.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=3;td.textContent="검색 결과가 없습니다.";tr.append(td);$("soldierList").append(tr);}
  const pages=Math.max(1,Math.ceil(data.total/state.pageSize));
  $("pageLabel").textContent=state.page+" / "+pages+" · "+data.total.toLocaleString()+"명";
  $("prev").disabled=state.page<=1;$("next").disabled=state.page>=pages;
  if(!state.selected&&data.items.length)await select(data.items[0].soldier_id);
}
async function select(id) {
  const request=++state.detailRequest;
  const data=await api("/api/v1/soldiers/"+encodeURIComponent(id));
  if(request!==state.detailRequest)return;
  state.selected=id;state.detail=data;
  $("emptyDetail").hidden=true;$("detail").hidden=false;$("delivery").hidden=true;
  $("detailTitle").textContent=id;$("detailSource").textContent=data.record.source==="web"?"직접 입력":"합성 데이터";
  const p=data.result.profile;
  $("profileLine").textContent=p.age+"세 · 남성 · 보병 소총수 · "+p.height_cm+"cm / "+p.weight_kg+"kg · BMI "+p.bmi;
  const now=data.result.now_matrix[0],goal=data.result.goal_matrix[0],diff=data.result.difference_matrix[0];
  $("comparisonBody").replaceChildren();
  const rows=[["팔굽혀펴기",now[0]+"회",goal[0]+"회",signed(diff[0],"회")],["윗몸일으키기",now[1]+"회",goal[1]+"회",signed(diff[1],"회")],["3km 달리기",time(now[2]),time(goal[2]),signed(diff[2],"초")]];
  for(const values of rows){const tr=document.createElement("tr");for(const v of values){const td=document.createElement("td");td.textContent=v;tr.append(td);}$("comparisonBody").append(tr);}
  $("loadRatio").textContent=data.result.load_context.load_ratio_percent+"%";
  $("jsonPreview").textContent=JSON.stringify(data.result,null,2);
  document.querySelectorAll("#soldierList tr").forEach(tr=>tr.classList.toggle("selected",tr.dataset.id===id));
}
async function checkConnection(){
  $("checkConnection").disabled=true;
  try{const r=await api("/api/v1/module2/health");$("connectionBadge").textContent=r.mode==="mock"?"● 모의 서버 연결됨":"● 모듈 2 연결됨";$("connectionText").textContent=r.mode==="mock"?"통신 확인용 서버입니다. 운동 계획은 생성하지 않습니다.":"실제 모듈 2가 요청을 받을 준비가 됐습니다.";}
  catch(e){$("connectionBadge").textContent="○ 모듈 2 연결 안 됨";$("connectionText").textContent=e.message;}
  finally{$("checkConnection").disabled=false;}
}
$("searchForm").addEventListener("submit",e=>{e.preventDefault();state.page=1;list().catch(e=>notify(e.message,true));});
$("source").addEventListener("change",()=>{state.page=1;list().catch(e=>notify(e.message,true));});
$("prev").addEventListener("click",()=>{state.page--;list().catch(e=>notify(e.message,true));});
$("next").addEventListener("click",()=>{state.page++;list().catch(e=>notify(e.message,true));});
$("checkConnection").addEventListener("click",checkConnection);
$("showForm").addEventListener("click",()=>{$("formError").textContent="";$("inputDialog").showModal();});
$("closeForm").addEventListener("click",()=>$("inputDialog").close());
$("inputForm").addEventListener("submit",async e=>{
  e.preventDefault();$("saveButton").disabled=true;$("formError").textContent="";
  const form=new FormData(e.currentTarget);
  const raw={soldier_id:form.get("soldier_id"),sex:"male",role:"infantry_rifleman",is_synthetic:true,combat_load_kg:15,age_basis:"calendar_year_minus_birth_year",record_schema_version:"2.0",pushups_duration_seconds:120,situps_duration_seconds:120,run_distance_m:3000,baseline_test_load_kg:0,run_3km_time:form.get("run_3km_time")};
  for(const key of ["age","height_cm","weight_kg","pushups_2min","situps_2min"])raw[key]=Number(form.get(key));
  try{const data=await api("/api/v1/soldiers",{method:"POST",body:JSON.stringify(raw)});$("inputDialog").close();$("search").value="";$("source").value="";state.page=1;await select(data.record.soldier_id);await list();notify("새 사례를 저장하고 목표 계산을 완료했습니다.");}
  catch(e){$("formError").textContent=e.message;}finally{$("saveButton").disabled=false;}
});
$("sendModule2").addEventListener("click",async()=>{
  if(!state.selected)return;
  const id=state.selected;$("sendModule2").disabled=true;$("delivery").hidden=false;$("delivery").classList.remove("error");$("delivery").textContent="모듈 2에 전송하고 있습니다…";
  try{const data=await api("/api/v1/soldiers/"+encodeURIComponent(id)+"/module2",{method:"POST",body:"{}"});if(id===state.selected){const r=data.module2_response;$("delivery").textContent=r.mode==="mock"?"모의 서버 접수 완료 · 데이터 형식과 계산값을 확인했습니다. 운동 계획은 생성되지 않았습니다.":"모듈 2 접수 완료 · 접수 ID: "+r.receipt_id;}}
  catch(e){if(id===state.selected){$("delivery").textContent=e.message;$("delivery").classList.add("error");}}
  finally{$("sendModule2").disabled=false;}
});
$("download").addEventListener("click",()=>{
  if(!state.detail)return;const url=URL.createObjectURL(new Blob([JSON.stringify(state.detail.result,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=state.selected+"_module1.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
list().catch(e=>notify(e.message,true));checkConnection();
