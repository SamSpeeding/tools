
const $ = s => document.querySelector(s);
const esc = s => (s==null?"":String(s)).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0; };   // numbers from the catalog go into HTML as numbers only
let cart = {};                 // { id: {title, total, cover} }
let lastStatus = { running:false, series:[], log:[] };
let DEMO = false;
// Demo/preview data is ONLY for the offline artifact preview (file:// or claude.ai).
// On the real app (served from localhost) never fall back to fake data — retry the backend.
const ALLOW_DEMO = !/^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname);

try { cart = JSON.parse(localStorage.getItem("hg-cart")||"{}") || {}; } catch(e){ cart = {}; }
const saveCart = () => { const c={}; for(const k in cart){ if(!(cart[k]&&cart[k].unavailable)) c[k]=cart[k]; } localStorage.setItem("hg-cart", JSON.stringify(c)); };  // #4: don't persist "unavailable" placeholders

/* ---------- theme ---------- */
function applyTheme(t){ document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("hg-theme", t); $("#themeBtn").setAttribute("aria-checked", t==="dark" ? "true" : "false"); }   // ☀ | ☾ switch: on = dark
applyTheme(localStorage.getItem("hg-theme") || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light"));
$("#themeBtn").onclick = () => applyTheme(document.documentElement.getAttribute("data-theme")==="dark" ? "light" : "dark");

/* ---------- toast ---------- */
let toastT;
function toast(msg, err){ const t=$("#toast"); t.textContent=msg; t.classList.toggle("err",!!err); t.classList.add("show");
  clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"), 2600); }

/* Dropdown lists (customizable <select>, see the CSS) are drawn inside the page, so keys pressed in an open list also
   reached the page's own shortcuts: Esc closed the whole dialog / player around it, ←/→/Space drove the player. A
   native list swallowed them. While a list is open the page's handlers sit out (window capture, registered before
   every other key handler) and the list keeps its keys; nothing is prevented, so Esc still closes just the list. */
window.addEventListener("keydown", e=>{
  let open=false; try{ open=!!document.querySelector("select:open"); }catch(_){}   // no :open support = native lists
  if(open) e.stopImmediatePropagation();
}, true);
/* A customizable <select> is only as wide as the value it shows (a native one is as wide as its longest option), so
   the Library header would shift sideways each time Sort changed (and the Catalog row with its Sort / Status). Pin each
   one to its widest option: measured once it is on screen, again when the web fonts arrive and when Display size changes.
   Setting selectedIndex fires no change event. The stretching (flex:1) Convert selects are left alone. */
(function pinSelectWidths(){
  if(!(window.CSS && CSS.supports && CSS.supports("appearance","base-select")) || !window.ResizeObserver) return;
  const forced=()=>{ try{ return matchMedia("(forced-colors: active)").matches; }catch(e){ return false; } };
  let gen=0; const key=()=>(document.documentElement.style.zoom||"1")+"|"+gen+"|"+(forced()?1:0);
  const due=s=>{ if(s._pinKey===key() || !s.isConnected || !s.getClientRects().length) return false;   // hidden: when it shows
    try{ return !s.matches(":open"); }catch(e){ return true; } };
  function pin(s){ s._pinKey=key();
    const vu=s.parentElement && s.parentElement.classList.contains("vu");
    if(vu && !forced()){ vuPin(s); return; }      // value + unit: its own width (high contrast: the select's own text, below)
    if(vu) s.style.width="";
    if(getComputedStyle(s).flexGrow!=="0") return;
    const cur=s.selectedIndex; let w=0; s.style.minWidth="";
    for(let i=0;i<s.options.length;i++){ s.selectedIndex=i; w=Math.max(w, parseFloat(getComputedStyle(s).width)||0); }
    s.selectedIndex=cur;
    if(w) s.style.minWidth=Math.ceil(w)+"px";
  }
  const all=()=>document.querySelectorAll("select"), again=()=>all().forEach(s=>{ if(due(s)) pin(s); });
  // on screen for the first time (or again after a zoom / font change): resizing an observed element inside the
  // observer's own callback would raise a "ResizeObserver loop" error, so it is watched again from the next frame
  const ro=new ResizeObserver(es=>es.forEach(({target:s})=>{ if(!due(s)) return;
    ro.unobserve(s); pin(s); requestAnimationFrame(()=>ro.observe(s)); }));
  all().forEach(s=>ro.observe(s));
  window.addEventListener("resize", again);                    // Display size sends one; a no-op unless the zoom changed
  if(document.fonts && document.fonts.ready) document.fonts.ready.then(()=>{ gen++; again(); });
  try{ matchMedia("(forced-colors: active)").addEventListener("change", again); }catch(e){}   // high contrast on / off
})();

/* A click on a dialog's backdrop closes it only when the press AND the release were both on the backdrop: a drag
   between the card and the backdrop (selecting the key text, pressing an episode chip, scrubbing the video, in
   either direction) lands its click on the backdrop too -- their common ancestor -- and must not close the dialog. */
let _pressT=null, _releaseT=null;
document.addEventListener("mousedown", e=>{ _pressT=e.target; }, true);
document.addEventListener("mouseup", e=>{ _releaseT=e.target; }, true);
function backdropClick(e){ const b=e.currentTarget; return e.target===b && _pressT===b && _releaseT===b; }

/* ---------- in-app confirm (replaces the browser's confirm() box) ---------- */
// ask(title, msg, {ok, cancel, danger}) -> Promise<true | false>. Cancel, Esc and the backdrop all answer false. Focus
// stays inside while it's open and starts on Cancel for a destructive question, so Enter only confirms when the
// confirm button itself has focus (Enter just presses the focused button -- there's no dialog-wide Enter key).
let _askDone=null, _askAt=0, _askFirst=null;
function ask(title, msg, o){ o=o||{};
  if(_askDone) _askDone(false);                                  // one question at a time: a newer one cancels the older
  const m=$("#askModal"), yes=$("#askYes"), no=$("#askNo"), back=document.activeElement;
  $("#askTitle").textContent=title||""; $("#askMsg").textContent=msg||""; $("#askMsg").hidden=!msg;
  yes.textContent=o.ok||"OK"; no.textContent=o.cancel||"Cancel";
  yes.className="btn sm "+(o.danger?"danger":"primary");
  m.hidden=false; _askAt=performance.now();                       // monotonic: a clock change can't stretch/skip the guard
  return new Promise(res=>{
    _askDone=v=>{ _askDone=null; m.hidden=true;
      try{ if(back && back.isConnected && back!==document.body) back.focus({preventScroll:true}); }catch(e){}
      res(!!v); };
    _askFirst=o.danger?no:yes;
    try{ _askFirst.focus({preventScroll:true}); }catch(e){}
  });
}
(function initAsk(){
  const m=$("#askModal");
  // A pointer click that belongs to the gesture that opened the question can't answer it unseen: any 2nd/3rd click of a
  // multi-click (detail>1 -- it began before the question was up, however long the system double-click time is) and a
  // single click in the first 400 ms. Keyboard presses (detail 0) always count.
  // An ignored press still focused the button it hit, so focus goes back to the one ask() chose (Cancel on a destructive
  // question) -- a reflex Enter can't confirm through the click that was just ignored.
  const early=e=>e.detail>1 || (e.detail>0 && performance.now()-_askAt<=400);
  const ignored=e=>{ if(!early(e)) return false; try{ if(_askFirst) _askFirst.focus({preventScroll:true}); }catch(_){} return true; };
  $("#askYes").onclick=e=>{ if(_askDone && !ignored(e)) _askDone(true); };
  $("#askNo").onclick=e=>{ if(_askDone && !ignored(e)) _askDone(false); };
  // backdrop = Cancel (same guard; also ignored for a moment after opening even without a pointer detail)
  m.addEventListener("click", e=>{ if(_askDone && backdropClick(e) && !(e.detail>1) && performance.now()-_askAt>400) _askDone(false); });
  // window capture: runs before the page's own Esc handlers, so Esc answers the question and closes nothing else
  window.addEventListener("keydown", e=>{
    if(!_askDone) return;
    if(e.key==="Escape"){ e.preventDefault(); e.stopPropagation(); _askDone(false); return; }
    if(e.key==="Tab"){                                           // keep focus on the dialog's two buttons
      const f=[$("#askNo"), $("#askYes")], i=f.indexOf(document.activeElement);
      e.preventDefault(); e.stopPropagation();
      f[i<0 ? 0 : (i+(e.shiftKey?f.length-1:1))%f.length].focus();
    }
  }, true);
})();

/* ---------- gradient poster (covers-less fallback + demo) ---------- */
function hue(s){ let t="";                         // any value (a non-string title from odd data): hashed as its text
  try{ t = typeof s==="string" ? s : (s==null ? "" : String(s)); }catch(e){}
  let h=0; for(let i=0;i<t.length;i++) h=(h*31+t.charCodeAt(i))>>>0; return h%360; }
function gradFor(title){ const h=hue(title); const h2=(h+34)%360;
  return `background:linear-gradient(155deg,hsl(${h} 62% 46%),hsl(${h2} 68% 30%))`; }
function posterArt(x, big, raw){
  const t = x.title||"";
  const grad = `<div class="grad" style="${gradFor(t)}">${big?esc(t):''}</div>`;
  if (x.cover && !DEMO){
    const src = raw ? (/^https?:\/\//i.test(x.cover) ? x.cover : "") : `/img?url=${encodeURIComponent(x.cover)}`;
    if (src) return `<img ${raw?`src="${esc(src)}"`:covAttr(src)} alt="" loading="lazy" onerror="this.remove()">` + grad;
  }
  return grad;
}
/* ---------- cover loads: at most COV_MAX /img requests at once ----------
   Chrome keeps only ~6 connections to this app, and a slow cover (byteimg's slow lane: 12 s + the server's one ~20 s
   retry) holds one the whole time: EVERY /img cover -- the grids', the queue rows', the Library's fallback covers and
   the series detail's (<img data-img="/img?...">) -- goes through this small queue, near the screen first, so
   /dl/search, its re-asks and the /dl/status poll always find a free connection. A cover frees its slot the moment it
   loads or fails; one whose grid is replaced meanwhile is dropped (its request cancelled); and none holds a slot past
   COV_HOLD_MS, the server's own longest try (12 s + ~20 s): still loading then, it is cancelled (the gradient stays).
   A cover that loaded once is drawn straight from the browser's cache (covAttr: src, no slot) when its grid is drawn
   again -- the Library grid is redrawn every few polls during a download -- and one still loading when its grid is
   redrawn hands its request and slot (and what is left of its COV_HOLD_MS) to the new card's image of the same URL. */
const COV_MAX=3, COV_HOLD_MS=32000, covWait=[], covRun=new Map(), covDone=new Set();
function covAttr(u){ return (covDone.has(u) ? 'src="' : 'data-img="') + esc(u) + '"'; }   // (u: a "/img?url=..." path)
function covStart(img, u, t0){
  let tm=0; const fin=()=>{ if(!covRun.has(img)) return; covRun.delete(img); clearTimeout(tm); setTimeout(covPump, 0); };
  covRun.set(img, fin); img._cu=u; img._ct=t0;
  tm=setTimeout(()=>{ if(covRun.has(img) && !img.complete){ img.removeAttribute("src"); img.remove(); } fin(); },
                Math.max(0, COV_HOLD_MS-(Date.now()-t0)));
  img.addEventListener("load", ()=>{ if(covDone.size>2000) covDone.clear(); covDone.add(u); fin(); }, {once:true});
  img.addEventListener("error", fin, {once:true});
  img.removeAttribute("data-img"); img.src=u;
}
const covIO=("IntersectionObserver" in window)
  ? new IntersectionObserver(es=>es.forEach(e=>{ if(e.isIntersecting){ covIO.unobserve(e.target); covWait.push(e.target); covPump(); } }), {rootMargin:"400px"})
  : null;
function covPump(){
  covRun.forEach((fin, img)=>{ if(img.isConnected) return;       // its grid is gone: its slot back -- or, redrawn, to
    const u=img._cu, n=u && [...document.querySelectorAll("img[data-img]")].find(i=>i.getAttribute("data-img")===u);
    if(n){ if(covIO) covIO.unobserve(n); const w=covWait.indexOf(n); if(w>=0) covWait.splice(w, 1);
      fin(); covStart(n, u, img._ct||Date.now()); }             // the new card's image: the same request goes on
    else { img.removeAttribute("src"); fin(); } });
  while(covRun.size<COV_MAX && covWait.length){
    const img=covWait.shift(), u=img.getAttribute("data-img");
    if(!img.isConnected || !u) continue;
    covStart(img, u, Date.now());
  }
}
function covScan(n){
  const l=n.matches("img[data-img]") ? [n] : [...n.querySelectorAll("img[data-img]")];
  l.forEach(img=>{ if(img._cq) return; img._cq=1; if(covIO) covIO.observe(img); else covWait.push(img); });
  if(!covIO && l.length) covPump();
}
new MutationObserver(ms=>{ let gone=false;
  ms.forEach(m=>{ m.addedNodes.forEach(n=>{ if(n.nodeType===1) covScan(n); });
    m.removedNodes.forEach(n=>{ gone=true;               // (a cover not started yet: no longer watched)
      if(covIO && n.nodeType===1) (n.matches("img[data-img]") ? [n] : [...n.querySelectorAll("img[data-img]")]).forEach(i=>{ covIO.unobserve(i); i._cq=0; }); }); });
  if(gone && covRun.size) covPump();
}).observe(document.body, {childList:true, subtree:true});

/* ---------- omni: search vs link ---------- */
const looksLikeLink = t => /https?:\/\/|novelquickapp|novelapp|hongguoduanju|\/s\/|fqnovel|\.com\/|reading\//i.test(t) || /\n/.test(t.trim());
$("#omni").addEventListener("input", e=>{
  const link = looksLikeLink(e.target.value);
  const m=$("#omniMode"); m.textContent = link?"Link":"Search"; m.classList.toggle("link",link);
});
function omniGo(){
  const v=$("#omni").value.trim(); if(!v) return;
  if (looksLikeLink(v)) addLinks(v); else doSearch(v);
}
$("#omniGo").onclick=omniGo;
$("#omni").addEventListener("keydown",e=>{ if(e.key==="Enter") omniGo(); });

/* ---------- search ---------- */
function resultCards(res, raw, startRank){
  return res.map((x,idx)=>{
    const on = !!cart[x.series_id];
    const rk = (typeof startRank==='number') ? `<span class="rankno${(startRank+idx)<=3?' top':''}">${startRank+idx}</span>` : '';
    return `<button class="poster" data-id="${esc(x.series_id)}" data-t="${esc(x.title)}" data-n="${num(x.episode_cnt)}" data-cov="${esc(x.cover||'')}" data-sc="${esc(x.score||'')}" aria-pressed="${on}">
      <div class="art">${posterArt(x,true,raw)}<div class="scrim"></div>
        ${rk}
        ${x.score?`<span class="score" title="rating">★ ${esc(x.score)}</span>`:''}
        ${x.episode_cnt?`<span class="eps"><span>${num(x.episode_cnt)} eps</span></span>`:(x.heat?`<span class="eps"><span>🔥 ${esc(x.heat)}</span></span>`:``)}
        <span class="check">${on?'✓':'+'}</span>
        <span class="prev" role="button" tabindex="-1" aria-label="Preview ${esc(x.title)}" title="Preview"><span class="pv">▶</span><span class="tip">Preview</span></span>
      </div>
      <div class="ttl">${esc(x.title)}</div>
    </button>`;
  }).join("");
}

/* populate the main page with a live "Trending" row on open (real posters, no login) */
function trendRows(){ const g=$("#results"); if(!g) return 12; const cols=getComputedStyle(g).gridTemplateColumns.split(" ").filter(x=>x&&x!=="0px").length; return Math.max(1,cols)*2; }  // exactly 2 rows (responsive to width)
let trendData=[], trendBoard="new", trendCategory="ai", trendExpanded=false, trendPage=1, trendHasMore=false, trendOffsets={1:0}, trendLoading=false;   // leaderboard = hongguoduanju hot-rank (AI default)
// Leaderboard, Catalog and Search share the one results grid: each load takes a ticket and only the newest
// one may draw, so a slow reply (e.g. the first /dl/rank at launch) can't overwrite the view the user moved to.
let viewSeq=0;
async function loadTrending(board, page){
  if(DEMO || ALLOW_DEMO) return;         // only on the real app (localhost); preview keeps its sample grid
  const vs=++viewSeq;
  const boardChanged = !!board && board!==trendBoard;
  if(board) trendBoard=board;
  if(boardChanged){ trendPage=1; trendOffsets={1:0}; }   // switching tab -> page 1 (keep expanded/collapsed state)
  if(page) trendPage=page;
  const sec=$("#resultsSec"), box=$("#results");
  ssHide();                              // the search's season strip + "More results" belong to the search view only
  sec.hidden=false; $("#resLabel").textContent="🏆 Leaderboard"; $("#boardTabs").hidden=false; $("#backHome").hidden=true; $("#explorerPager").hidden=true; $("#explorerControls").hidden=true; $("#resCount").textContent="";
  $("#trendCats").hidden=false;          // the category selector (All · Live-action · Animated · AI)
  document.querySelectorAll("#boardTabs .tab").forEach(t=>t.classList.toggle("on", t.dataset.board==="trend"));
  document.querySelectorAll("#trendCats .exchip").forEach(c=>c.classList.toggle("on", c.dataset.cat===trendCategory));
  if(trendExpanded) box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="sm">Loading…</div></div>';
  const off = trendOffsets[trendPage]||0; trendLoading=true;
  try{
    const j = await (await fetch(`/dl/rank?board=${encodeURIComponent(trendBoard)}&category=${encodeURIComponent(trendCategory)}&offset=${off}&size=100`,{cache:"no-store"})).json();
    if(vs!==viewSeq) return;             // the user moved on (Catalog / Search / another board or page): drop it
    trendData = j.results||[]; trendHasMore = !!j.has_more; trendOffsets[trendPage+1] = (j.next_offset!=null? j.next_offset : off); trendLoading=false;
    if(!trendData.length && trendPage===1){ sec.hidden=true; return; }
    renderTrending();
  }catch(e){ if(vs!==viewSeq) return; trendLoading=false; if(trendPage===1) sec.hidden=true; }   // backend not ready -> just show the hero
}
function renderTrending(){
  const box=$("#results");
  if(!trendExpanded){                                  // collapsed default: 2 responsive rows + Expand
    box.innerHTML = resultCards(trendData.slice(0, trendRows()), false, 1);
    $("#resCount").textContent = "";
  } else {                                             // expanded: show the full chart (single Collapse lives in #moreRow)
    box.innerHTML = resultCards(trendData, false, (trendPage-1)*100+1);
    $("#resCount").textContent = "· "+trendData.length;
  }
  renderTrendControls();
  syncResultButtons();
  enrichTrendEpisodes();          // fill REAL episode counts into the cards on screen (lazy, cached, no signer)
}
/* Leaderboard cards render instantly with 🔥heat; then we fetch the true episode count (共N集 from
   hongguoduanju /detail) for just the cards currently on screen and swap 🔥heat -> "N eps". */
async function enrichTrendEpisodes(){
  const box=$("#results"); if(!box) return;
  const cards=[...box.querySelectorAll('.poster[data-id]')];
  const ids=cards.map(c=>c.dataset.id).filter(Boolean);
  if(!ids.length) return;
  let j; try{ j=await (await fetch("/dl/rank-episodes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({series_ids:ids})})).json(); }
  catch(e){ return; }
  const eps=(j&&j.eps)||{};
  cards.forEach(c=>{ const n=eps[c.dataset.id]; if(n&&n>0){ c.dataset.n=n; const s=c.querySelector('.eps span'); if(s) s.textContent=n+" eps"; } });
  (trendData||[]).forEach(x=>{ const n=eps[x.series_id]; if(n&&n>0) x.episode_cnt=n; });   // persist so collapse/expand keeps eps
}
function renderTrendControls(){
  const row=$("#moreRow");
  row.classList.toggle("trendctl-sticky", trendExpanded);   // sticky bar when expanded
  if(!trendExpanded){
    if(trendData.length > trendRows()){                      // only offer Expand when there's more than 2 rows
      row.hidden=false;
      row.innerHTML = `<button class="btn ghost sm" id="trendExpand">Expand ↓ &nbsp;·&nbsp; all ${trendData.length}</button>`;
      $("#trendExpand").onclick=()=>{ trendExpanded=true; renderTrending(); trendTop(); };
    } else { row.hidden=true; }                              // everything already fits in 2 rows
  } else {
    row.hidden=false;
    const hasPager = trendHasMore || trendPage>1;            // rank is a single page -> just Collapse
    row.innerHTML = (hasPager
        ? `<button class="btn ghost sm" id="trendPrev"${trendPage<=1?" disabled":""}>‹ Prev</button>`
          + `<span class="trend-pageno">Page ${trendPage}</span>`
          + `<button class="btn ghost sm" id="trendNext"${trendHasMore?"":" disabled"}>Next ›</button>`
          + `<span class="cluster-div" aria-hidden="true"></span>`
        : ``)
      + `<button class="btn ghost sm" id="trendCollapse">↑ Collapse</button>`;
    if(hasPager){
      $("#trendPrev").onclick=()=>{ if(trendPage>1) loadTrending(null, trendPage-1).then(trendTop); };
      $("#trendNext").onclick=()=>{ if(trendHasMore) loadTrending(null, trendPage+1).then(trendTop); };
    }
    $("#trendCollapse").onclick=collapseTrend;
  }
}
function trendTop(){ try{ $("#resultsSec").scrollIntoView({block:"start"}); }catch(e){} }
function collapseTrend(){
  trendExpanded=false;
  if(trendPage!==1){ trendPage=1; trendOffsets={1:0}; loadTrending(null,1).then(trendTop); }
  else { renderTrending(); trendTop(); }
}

/* Explorer: the full ~20k verified catalogue, served from the Cloudflare Worker (D1 + covers).
   Paged, with genre tabs / in-catalogue search / sort / status filter. */
const EXPLORER_API = "https://explorer.hongguodownloader.com";  // custom domain (privacy) — same worker; workers.dev stays alive for older installs
let expPage=1, expPages=1;   // Catalog shows a fixed 100 cards per page (rows selector removed)
let exGenre="", exSort="newest", exStatus="", exQ="", exGenresLoaded=false, exSeq=0;   // default: Newest (newly-scraped dramas first)
async function ensureGenres(){
  if(exGenresLoaded) return; exGenresLoaded=true;
  try{
    const r = await fetch(EXPLORER_API+"/genres?limit=22", {cache:"no-store"});  // #5: always fresh labels (no stale browser cache)
    const j = await r.json();
    // busy (429) or any error reply: not loaded -- the catch clears the flag, so the next Catalog load asks again
    if(!r.ok || j.error || !Array.isArray(j.genres)) throw new Error("genres unavailable");
    const chips = j.genres.map(g=>`<button class="exchip" data-g="${esc(g.genre)}">${esc(g.genre)}</button>`).join("");
    $("#exGenres").innerHTML = `<button class="exchip on" data-g="">All</button>`+chips;
    $("#exGenres").querySelectorAll(".exchip").forEach(c=>c.onclick=()=>{
      exGenre=c.dataset.g;
      $("#exGenres").querySelectorAll(".exchip").forEach(x=>x.classList.toggle("on", x===c));
      loadExplorer(1);
    });
  }catch(e){ exGenresLoaded=false; }
}
async function loadExplorer(page){
  if(DEMO || ALLOW_DEMO) return;
  const seq=++exSeq, vs=++viewSeq;
  const sec=$("#resultsSec"), box=$("#results");
  ssHide();
  sec.hidden=false; $("#resLabel").textContent="🎬 Catalog"; $("#boardTabs").hidden=false; $("#backHome").hidden=true; $("#moreRow").hidden=true; $("#trendCats").hidden=true;
  $("#explorerControls").hidden=false;
  document.querySelectorAll("#boardTabs .tab").forEach(t=>t.classList.toggle("on", t.dataset.board==="explorer"));
  ensureGenres();
  box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="sm">Loading catalogue…</div></div>';
  try{
    const p = new URLSearchParams({ page:page||1, size:100, sort:exSort });
    if(exGenre) p.set("genre", exGenre);
    if(exStatus) p.set("status", exStatus);
    if(exQ) p.set("q", exQ);
    const r = await fetch(EXPLORER_API+"/explorer?"+p.toString(), {cache:"no-store"});   // fresh (catalog grows weekly; avoids stale browser cache)
    const j = await r.json().catch(e=>{ if(r.status===429) return {error:"rate_limited"}; throw e; });   // a 429 without a JSON body is still "busy"
    if(seq!==exSeq || vs!==viewSeq) return;   // a newer request (or another view) superseded this one — drop the stale result
    if(r.status===429 || j.error){            // the catalogue's per-user limit (or a server error): not "no matches"
      $("#explorerPager").hidden=true; $("#resCount").textContent="";
      box.innerHTML = (r.status===429 || j.error==="rate_limited")
        ? '<div class="empty" style="grid-column:1/-1"><div class="big">Catalog is busy</div><div class="sm">Try again in a moment.</div></div>'
        : '<div class="empty" style="grid-column:1/-1"><div class="big">Couldn’t load the catalogue</div><div class="sm">Try again in a moment.</div></div>';
      return;
    }
    const res=j.items||[];
    if(!(j.count>0)){
      $("#explorerPager").hidden=true; $("#resCount").textContent="· 0";
      box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="big">No matches</div><div class="sm">Try a different genre, filter, or search term.</div></div>';
      return;
    }
    expPage=j.page; expPages=j.pages;
    box.innerHTML = resultCards(res, true); syncResultButtons();
    $("#resCount").textContent = "· "+j.count;
    $("#explorerPager").hidden=false;
    $("#expInfo").textContent = "/ "+j.pages; $("#expPage").value = j.page;
    $("#expPrev").disabled = j.page<=1; $("#expNext").disabled = j.page>=j.pages;
    try{ $("#resultsSec").scrollIntoView({block:"start"}); }catch(e){}
  }catch(e){
    if(seq!==exSeq || vs!==viewSeq) return;
    $("#explorerPager").hidden=true;
    box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="big">Couldn’t reach the catalogue</div><div class="sm">Check your internet connection.</div></div>';
  }
}

async function doSearch(q){
  const sec=$("#resultsSec"), box=$("#results"), vs=++viewSeq;
  sec.hidden=false; $("#resLabel").textContent="Results"; $("#resCount").textContent=""; $("#boardTabs").hidden=true; $("#backHome").hidden=false; $("#moreRow").hidden=true; $("#trendCats").hidden=true; $("#explorerPager").hidden=true; $("#explorerControls").hidden=true;
  ssHide(); ssQ=q;
  box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="sm">Searching “'+esc(q)+'”…</div></div>';
  try{
    const j = DEMO ? demoSearch(q) : await (await fetch("/dl/search?q="+encodeURIComponent(q))).json();
    if(vs!==viewSeq) return;             // a newer search / Leaderboard / Catalog took over the grid meanwhile
    ssFirst(q, vs, j);
  }catch(e){ if(vs!==viewSeq) return; ssHide(); box.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="big">Search unavailable</div><div class="sm">Is the signer + backend running? '+esc(""+e)+'</div></div>'; }
}
function ssFirst(q, vs, j){              // a first paint: the grid, the strip, the cursor (also the late page 1 swapped in)
  const box=$("#results"), res=j.results||[];
  ssCursor = (typeof j.cursor==="string" && j.cursor) ? j.cursor : null;
  ssData = {series:j.series, related:j.related, complete:j.complete, pending:j.pending===true && !DEMO,
            backup:(j.backup==="down"||j.backup==="slow") ? j.backup : false, slow:j.slow===true && !DEMO};
  ssRender(); ssMoreRender();
  $("#resCount").textContent = res.length?("· "+res.length):"";
  if(res.length) box.innerHTML = resultCards(res);
  else if(ssData.pending && !ssData.slow) box.innerHTML='';   // the strip above says it is looking for the seasons
  else ssEmpty(j);
  if(ssData.slow) ssAskAgain(q, vs);     // page 1 is late: the website's results for now, the real ones swapped in
  else if(ssData.pending) ssLoadStrip(q, vs);
}
/* A late page 1 (the main server is slow: the reply says slow, with Hongguo's website's results for now): ask again
   (again=1: the server waits a moment on the SAME search, it never starts a second one) every ~1 s for up to ~30 s --
   ~50 s while the signer is reconnecting (source 'degraded': the server's own ~45 s window) -- and swap the real page 1
   -- its results, strip and "More results" -- in as soon as it is there. Nothing to do for the user. After that the
   banner offers "Search again" (a late page 1 is kept on the server: that search then shows it at once). */
const SS_SLOW_MS=30000, SS_SLOW_DEG_MS=50000, SS_ASK_GAP=1000;
function ssDegraded(){ const s=lastStatus && lastStatus.source; return !!(s && s.mode==="degraded"); }
async function ssAskAgain(q, vs){
  const t0=Date.now();
  while(vs===viewSeq && q===ssQ && Date.now()-t0<(ssDegraded() ? SS_SLOW_DEG_MS : SS_SLOW_MS)){
    await new Promise(r=>setTimeout(r, SS_ASK_GAP));
    if(vs!==viewSeq || q!==ssQ) return;
    let j; try{ j=await (await fetch("/dl/search?q="+encodeURIComponent(q)+"&again=1")).json(); }catch(e){ continue; }
    if(vs!==viewSeq || q!==ssQ) return;
    if(j && j.slow===true){ ssAppend(j.results); continue; }   // still late: the website's results that came meanwhile
    if(j && j.backup==="down"){ ssFirst(q, vs, j); return; }   // the signed API went down meanwhile: the backup's answer (or its error)
    if(!j) break;
    if(j.error){ if(ssData) ssData.slowErr=String(j.error); break; }   // page 1 failed after all: the website's results stay, the reason shown
    ssFirst(q, vs, j); return;           // page 1: swapped in
  }
  if(vs!==viewSeq || q!==ssQ || !ssData) return;
  ssData.slowEnd=true; ssRender();       // no page 1 in time: the website's results stay (+ "Search again")
  if(!$("#results").querySelector(".poster")) ssEmpty(ssData.slowErr ? {error:ssData.slowErr} : null);
}

/* ---------- search: the drama's season strip + "More results" ----------
   /dl/search answers page 1 fast: its results, an opaque cursor for "More results" (the server keeps the page state),
   and the strip when it is known -- else the platform's own season card, provisional (pending). /dl/search/seasons
   then brings every season of the drama searched, each checked by its album on the server. A chip, "Add all" or a
   Related pill puts series in the queue (the Download button's path). Every server string goes through esc(); the
   clicks are delegated listeners on data-ss / data-ss-all (no inline handlers). */
var ssQ="", ssCursor=null, ssData=null, ssMoreBusy=false;   // var: syncResultButtons may run before this line
var SS_ID=/^[0-9]{15,20}$/;
function ssHide(){ const el=$("#srchSeasons"), m=$("#srchMore");
  el.hidden=true; el.innerHTML=""; m.hidden=true; m.innerHTML=""; ssData=null; ssCursor=null; }
function ssRows(v){ return Array.isArray(v) ? v.filter(x=>x && typeof x==="object" && SS_ID.test(String(x.series_id))) : []; }
function ssSeries(){ return (ssData && Array.isArray(ssData.series) ? ssData.series : []).filter(s=>s && typeof s==="object"); }
function ssOwn(s){ return ssRows(s.seasons).filter(x=>num(x.episode_cnt)>0); }   // the seasons a chip / Add all can queue
function ssName(x){ const s=num(x.season); return (x.short===true && s>0) ? "S"+s : String(x.title||x.series_id); }
function ssTip(x){ return [String(x.title||x.series_id), lsnN(x.episode_cnt,"episode"), String(x.status||""), x.score?"★"+x.score:""].filter(Boolean).join(" · "); }
function ssChip(x, rel){
  const on=!!cart[x.series_id];
  return `<button class="lsn-pill ss-chip${rel?' rel':''}" data-ss="${esc(x.series_id)}" aria-pressed="${on}" title="${esc(ssTip(x))}">`
    +`<span class="lsn-t">${esc(rel ? String(x.title||x.series_id) : ssName(x))}</span><span class="lsn-m">${esc(lsnEps(x.episode_cnt))}</span>`
    +`<span class="ss-ck" aria-hidden="true">${on?'✓':'+'}</span></button>`;
}
function ssSoon(x){ const s=num(x.season), t=String(x.title||x.series_id);
  return `<span class="lsn-pill soon" title="${esc(t)} · coming soon">${esc(s>0 ? "S"+s : t)} · coming soon</span>`; }
function ssRender(){
  const el=$("#srchSeasons"), series=ssSeries(), rels=ssRows(ssData && ssData.related), wait=!!(ssData && ssData.pending);
  const eds=rels.filter(x=>x.kind==="edition"), rel=rels.filter(x=>x.kind!=="edition"), bk=ssData && ssData.backup;
  if(!series.length && !rels.length && !wait && !bk){ el.hidden=true; el.innerHTML=""; return; }
  let h="";
  if(bk==="slow") h+='<div class="ss-backup">'+(ssData.slowEnd   // page 1 is late: swapped in later -- or no longer waited for
      ? 'Main server is slow — showing Hongguo\'s website results.'+(ssData.slowErr ? ' '+esc(ssData.slowErr) : '')
        +' <button class="lsn-add" data-ss-again>Search again</button>'
      : '<span class="ss-dot" aria-hidden="true"></span>Main server is slow — showing results from Hongguo\'s website for now')+'</div>';
  else if(bk) h+='<div class="ss-backup">Limited results (up to 10) from Hongguo\'s website</div>';
  series.forEach((s,i)=>{
    const rows=ssOwn(s), soon=ssRows(s.coming_soon), prov=s.provisional===true;
    const eps=rows.reduce((a,x)=>a+num(x.episode_cnt),0), all=rows.length>0 && rows.every(x=>cart[x.series_id]);
    const note = prov ? ' · <span class="ss-dot" aria-hidden="true"></span>checking every season…' : (s.complete===false ? ' · more may exist' : '');
    h+=`<div class="ss-strip"><div class="ss-head"><span class="ss-title">${esc(String(s.base||""))}</span>`
      +`<span class="ss-sub">${esc(lsnN(rows.length,"season"))} · ${esc(lsnN(eps,"episode"))}${note}</span>`
      +`<button class="lsn-add ss-all" data-ss-all="${i}"${(prov||!rows.length||all)?' disabled':''}${prov?' title="Available once every season is checked"':''}>${all?'✓ All in queue':'Add all'}</button></div>`
      +`<div class="ss-chips">${rows.map(x=>ssChip(x,false)).join("")}${soon.map(ssSoon).join("")}</div></div>`;
  });
  if(!series.length && wait && bk!=="slow") h+=`<div class="ss-strip"><span class="ss-note"><span class="ss-dot" aria-hidden="true"></span>Looking for every season…</span></div>`;
  if(eds.length) h+=`<div class="ss-rel"><span class="ss-k">Other edition</span><div class="ss-chips">${eds.slice(0,24).map(x=>ssChip(x,true)).join("")}</div></div>`;
  if(rel.length) h+=`<div class="ss-rel"><span class="ss-k">Related</span><div class="ss-chips">${rel.slice(0,24).map(x=>ssChip(x,true)).join("")}</div></div>`;
  el.innerHTML=h; el.hidden=false;
}
function srcRender(src, paused){        // poll(): the backup-source pill (the signed API is down), gone when it's back
  const el=$("#srcPill"); if(!el) return;
  const mode=src && src.mode, on=mode==="backup" || mode==="degraded";
  if(!on){ if(!el.hidden){ el.hidden=true; el.innerHTML=""; el._h=""; } return; }
  // degraded: the signer lost its connection and is reconnecting (before any backup mode): a small note only
  const h = mode==="degraded"
    ? '<span class="sp-tag"><i aria-hidden="true"></i>Main server slow</span><span class="sp-t">Reconnecting — a search may show Hongguo\'s website results for a moment.</span>'
    : '<span class="sp-tag"><i aria-hidden="true"></i>Backup source</span><span class="sp-t"><b>The download server is busy.</b> '
    + 'Search and episode checks use Hongguo\'s website'
    + (paused ? '; downloads are paused and resume by themselves.' : '; downloads wait and resume by themselves.') + '</span>';
  if(el._h!==h){ el._h=h; el.innerHTML=h; }
  el.hidden=false;
}
function ssFind(id){
  for(const s of ssSeries()){ const x=ssRows(s.seasons).find(r=>String(r.series_id)===id); if(x) return x; }
  return ssRows(ssData && ssData.related).find(r=>String(r.series_id)===id) || null;
}
function ssEmpty(j){                     // no drama in the grid: say why (the strip above may still hold the seasons)
  const box=$("#results"), found=ssSeries().length || ssRows(ssData && ssData.related).length;
  const bk=!!(ssData && ssData.backup);   // the backup source: the website's own search simply didn't list it
  const slow=!!(ssData && ssData.slow), wait=slow && !ssData.slowEnd;   // page 1 is late (the main server is slow)
  box.innerHTML = found
    ? '<div class="empty" style="grid-column:1/-1"><div class="sm">No other results'+(ssCursor?' on this page: try More results':'')+'.</div></div>'
    : '<div class="empty" style="grid-column:1/-1"><div class="big">'+(wait ? 'Waiting for the main server…' : 'Nothing found')+'</div><div class="sm">'+(j&&j.error?esc(j.error)
      : wait ? 'Hongguo\'s website search didn\'t list this title: the full results appear here as soon as the main server answers.'
      : slow ? 'The main server is slow right now and Hongguo\'s website search didn\'t list this title: try the search again in a moment.'
      : bk ? 'Hongguo\'s website search didn\'t list this title. Full search comes back automatically when the main server is available.'
      : 'Try a shorter keyword (e.g. one word of the title), another title, or paste a share link.')+'</div></div>';
}
async function ssLoadStrip(q, vs){
  let j; try{ j=await (await fetch("/dl/search/seasons?q="+encodeURIComponent(q))).json(); }catch(e){ j={series:[], related:[], complete:false}; }
  if(vs!==viewSeq || q!==ssQ) return;    // another search / view took over meanwhile
  ssData={series:j.series, related:j.related, complete:j.complete, pending:false,
          backup:(j.backup==="down"||j.backup==="slow") ? j.backup : false};
  ssRender();
  ssAppend(j.extra);                     // hongguoduanju.com's own results that came after the first paint
  if(!$("#results").querySelector(".poster")) ssEmpty(j);
}
function ssAppend(list){                 // results the grid doesn't show yet (each id once), after the ones it has
  const box=$("#results"), have=new Set([...box.querySelectorAll(".poster[data-id]")].map(p=>p.dataset.id)), add=[];
  (Array.isArray(list)?list:[]).forEach(x=>{ const id=x ? String(x.series_id) : "";
    if(SS_ID.test(id) && !have.has(id)){ have.add(id); add.push(x); } });
  if(!add.length) return 0;
  if(!box.querySelector(".poster")) box.innerHTML="";
  box.insertAdjacentHTML("beforeend", resultCards(add)); syncResultButtons();
  const n=box.querySelectorAll(".poster[data-id]").length; $("#resCount").textContent = n ? "· "+n : "";
  return add.length;
}
function ssMoreRender(){
  const m=$("#srchMore");
  if(!ssCursor){ m.hidden=true; m.innerHTML=""; return; }
  m.innerHTML='<button class="btn ghost sm" id="ssMoreBtn">More results</button>'; m.hidden=false;
}
$("#srchSeasons").addEventListener("click", e=>{
  if(e.target.closest("[data-ss-again]")){ if(ssQ) doSearch(ssQ); return; }   // a late search given up on: the same search again
  const a=e.target.closest("[data-ss-all]");
  if(a){
    const s=ssSeries()[num(a.dataset.ssAll)];
    if(a.disabled || !s || s.provisional===true) return;
    let n=0;
    ssOwn(s).forEach(x=>{ if(!cart[x.series_id]){ addToCart(x.series_id, x.title, num(x.episode_cnt), x.cover||"", true, x.score||""); n++; } });
    saveCart(); renderQueue(); syncResultButtons();
    if(n) toast(`Added ${lsnN(n,"season")} to the queue`);
    return;
  }
  const c=e.target.closest("[data-ss]"); if(!c) return;
  const x=ssFind(c.dataset.ss); if(!x) return;
  if(cart[x.series_id]) removeFromCart(x.series_id);
  else addToCart(x.series_id, x.title, num(x.episode_cnt), x.cover||"", false, x.score||"");
});
$("#srchMore").addEventListener("click", async e=>{
  const b=e.target.closest("#ssMoreBtn"); if(!b || ssMoreBusy || !ssCursor) return;
  const vs=viewSeq, q=ssQ; ssMoreBusy=true; b.disabled=true; b.textContent="Loading…";
  try{
    const j=await (await fetch("/dl/search?q="+encodeURIComponent(q)+"&cursor="+encodeURIComponent(ssCursor))).json();
    if(vs!==viewSeq || q!==ssQ) return;
    if(j.error){ toast("Couldn't load more results: try again", true); return; }   // the cursor stays: More can retry
    const added=ssAppend(j.results);
    ssCursor = (!j.expired && typeof j.cursor==="string" && j.cursor) ? j.cursor : null;
    if(j.expired) toast("Those results expired: search again for more", true);
    else if(!added) toast("No more new results");
  }catch(err){ if(vs===viewSeq) toast("Couldn't load more results", true); }
  finally{ ssMoreBusy=false; if(vs===viewSeq && q===ssQ) ssMoreRender(); }
});

/* ---------- resolve pasted links ---------- */
async function addLinks(text){
  const go=$("#omniGo"); go.disabled=true; go.textContent="Resolving…";
  try{
    const j = DEMO ? demoResolve(text) : await (await fetch("/dl/resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})})).json();
    let ok=0, bad=[], unavail=[], busy=0;
    (j.resolved||[]).forEach(x=>{
      if(x.series_id){ addToCart(x.series_id,x.title,x.total,x.cover,true); ok++; }
      else if(x.unavailable){ addUnavailCard(x.hg_id||x.title, x.title); unavail.push(x.title||"?"); }  // #4: toast + a dismissible 🚫 card
      else if(x.busy) busy++;                 // needs the main server (a title to look up) while it is down
      else bad.push(x.title||"?");
    });
    if(ok||unavail.length){ renderQueue(); saveCart(); syncResultButtons(); }           // working links + 下架 cards appear in the queue
    if(ok||unavail.length){ $("#omni").value=""; $("#omniMode").textContent="Search"; $("#omniMode").classList.remove("link"); }
    if(unavail.length) toast(`⚠️ 《${unavail[0]}》 is no longer available on the platform. This series has been taken offline and cannot be downloaded.`+(unavail.length>1?` (+${unavail.length-1} more)`:''), true);
    else if(busy && !ok) toast("Try again in a minute — the main server is busy", true);
    else toast(ok?`Added ${ok} to queue`+(bad.length?`, ${bad.length} unresolved`:"")+(busy?` · ${busy} more: try again in a minute — the main server is busy`:""):"Couldn't identify that link — paste a Hongguo / 红果漫剧 share (novelquickapp.com / hongguoduanju.com) or search by title", !ok);
  }catch(e){ toast("Resolve failed: "+e, true); }
  go.disabled=false; go.textContent="Go";
}

/* ---------- cart ---------- */
function addToCart(id,title,total,cover,defer,score){ if(!id) return; cart[id]={title:title||id,total:total||0,cover:cover||"",score:score||""}; if(!defer){ saveCart(); renderQueue(); syncResultButtons(); } }
function addUnavailCard(key,title){ if(!key) key="x"+Date.now(); cart[key]={title:title||"?",total:0,unavailable:true}; }  // #4: 下架 placeholder (not persisted, never submitted)
function removeFromCart(id){ delete cart[id]; saveCart(); renderQueue(); syncResultButtons(); }
function syncResultButtons(){ document.querySelectorAll(".poster").forEach(p=>{ const on=!!cart[p.dataset.id];
  p.setAttribute("aria-pressed", on); const c=p.querySelector(".check"); if(c) c.textContent=on?'✓':'+'; });
  ssSync(); }
function ssSync(){                       // the search strip's chips + "Add all" follow the queue
  document.querySelectorAll("#srchSeasons [data-ss]").forEach(c=>{ const on=!!cart[c.dataset.ss];
    c.setAttribute("aria-pressed", on); const k=c.querySelector(".ss-ck"); if(k) k.textContent=on?'✓':'+'; });
  document.querySelectorAll("#srchSeasons [data-ss-all]").forEach(b=>{ const s=ssSeries()[num(b.dataset.ssAll)]; if(!s) return;
    const rows=ssOwn(s), all=rows.length>0 && rows.every(x=>cart[x.series_id]);
    b.disabled = s.provisional===true || !rows.length || all; b.textContent = all ? '✓ All in queue' : 'Add all'; });
}
// After a queue download finishes, series that came out "done" leave the queue (they're in the Library
// now), so the dock no longer says "1 queued" with Download lit for work that's already finished.
// Failed / partial ones stay for a retry. Short delay so the green DONE row is seen first.
function clearFinishedFromQueue(){
  const done=(lastStatus.series||[]).filter(s=>s.status==="done").map(s=>String(s.sid)).filter(id=>cart[id]);
  if(!done.length) return;
  const first=cart[done[0]].title, gen=_runGen;
  setTimeout(()=>{
    if(gen!==_runGen || lastStatus.running) return;      // Download pressed again / a new run started meanwhile: leave the queue alone
    let n=0; done.forEach(id=>{ if(cart[id]){ delete cart[id]; n++; } });
    if(!n) return;
    saveCart(); renderQueue(); syncResultButtons();
    toast(n===1 ? `✓ 《${first}》 downloaded — it's in your Library` : `✓ ${n} series downloaded — they're in your Library`);
  }, 2000);
}

/* ---------- live numbers ---------- */
// MB/s from /dl/status = 10^6 bytes a second (averaged over the last ~3 s); the sizes beside it use the same MB / GB
// (10^6 / 10^9 bytes), so a size over the speed is the time it takes
function fmtRate(r){ r=num(r); return r<=0 ? "0.0" : (r>=99.95 ? String(Math.round(r)) : r.toFixed(1)); }
function fmtMB(b){ b=num(b); if(b<=0) return "0 MB";
  const mb=b/1e6; if(mb<9.95) return mb.toFixed(1)+" MB"; if(mb<999.5) return Math.round(mb)+" MB";
  const gb=b/1e9; return (gb<9.995 ? gb.toFixed(2) : (gb<99.95 ? gb.toFixed(1) : String(Math.round(gb))))+" GB"; }
function _txt(sel, v){ const e=$(sel); if(e && e.textContent!==v) e.textContent=v; return e; }   // no DOM write when unchanged
function _html(e, h){ if(e && e._h!==h){ e._h=h; e.innerHTML=h; } }

/* ---------- queue render ---------- */
// A row of the running (or last) job from its /dl/status row s: chip, meta and bar. The bar = the series' (or chosen
// range's) episodes already on disk + this run's BYTES of the ones it fetches, (have + need x bytes/bytes_total) / total:
// it moves smoothly inside every episode, and a top-up of a series already in the Library starts where its episode count
// says (a series new to the Library: bytes / bytes_total). Never behind the episodes counted (done / total).
function qLive(id, s, total){
  const running=!!lastStatus.running;
  const done=num(s.done), need=num(s.need), dl=num(s.dl_done), bt=num(s.bytes_total), b=num(s.bytes);
  let st=s.status||"queued";
  if(running && st==="queued" && (num(s.active)>0 || b>0)) st="downloading";   // bytes flow before its first episode lands
  if(!running && (st==="downloading" || st==="queued" || st==="waiting")) st="stopped";   // never a live label after the run
  const cls = st==="done"?"done":(st==="downloading"?"downloading":((st==="failed"||st==="incomplete")?"failed":"queued"));
  let frac = total ? Math.min(1, done/total) : (st==="done"?1:0);
  if(total && need>0 && bt>0) frac = Math.max(frac, Math.min(1, (Math.max(0, done-dl) + need*Math.min(1, b/bt)) / total));
  // bytes_total is partly an estimate (sizes looked up 5 at a time): a new batch of sizes can raise it, so while the
  // run lasts the bar never goes back (its high-water mark); the byte text beside it stays the true numbers
  if(running){ frac=Math.max(frac, _rowHW[id]||0); _rowHW[id]=frac; }
  let chip = `<span class="chip ${cls}"${st==="waiting" ? ' title="Retries its failed episodes in a moment"' : ""}>${esc(st==="recheck" ? "backup list" : st)}</span>`;
  // once nothing is running, a finished / failed row can be dismissed on its own (not only via Clear all)
  if(!running) chip += `<button class="x" data-rm="${esc(id)}" title="Remove">✕</button>`;
  // complete by the website's list only (the main server was down): never called done on its word
  const left = st==="recheck" ? "checked with the backup list — will re-check when the main server is back"
    : `${done}/${total||"?"} episodes · ${Math.floor(frac*100)}%` + (need>0 && bt>0 ? ` · ${fmtMB(Math.min(b,bt))} of ${fmtMB(bt)}` : "");
  const right = running && st==="downloading" && (num(s.active)>0 || num(s.rate)>0) ? `${fmtRate(s.rate)} MB/s` : "";   // its own speed while it downloads
  return { chip, meta:`<span class="rm-l">${esc(left)}</span><span class="rm-r">${esc(right)}</span>`,
           w:(frac*100).toFixed(2)+"%", fill:"fill"+(cls==="done"?" done":"")+(cls==="downloading"?" live":"") };
}
// Each poll re-draws a row only when its shape changed (another series, title, cover, a row gaining its job status);
// otherwise just its chip / numbers / bar width change in place, so the bar glides (width transition), the live
// shimmer keeps running and the covers never reload.
let _qKeys="";
function renderQueue(){
  const smap={}; (lastStatus.series||[]).forEach(s=>smap[s.sid]=s);
  const ids=Object.keys(cart);
  $("#queueCount").textContent=ids.length;
  const el=$("#queue");
  if(!ids.length){ _qKeys=""; el.innerHTML='<div class="empty"><div class="big">Your queue is empty</div><div class="sm">Search above and tap a poster, or paste a link.</div></div>'; updateDock(); return; }
  const rows = ids.map(id=>{
    const c=cart[id], s=smap[id];
    const title=(s&&s.title)||c.title, total=num((s&&s.total)||c.total);
    if(c.unavailable){   // #4: 下架 card — 🚫 badge + subtitle, dismissible, never downloadable
      return { key:"U|"+id+"|"+title, html:`<div class="row unavail" data-qid="${esc(id)}">
        <div class="thumb"><div class="grad" style="${gradFor(title)}"></div></div>
        <div class="body">
          <div class="r1"><span class="rttl">${esc(title)}</span><span class="chip unavail">🚫 Unavailable (已下架)</span></div>
          <div class="rmeta">Series is no longer available on the platform</div>
        </div>
        <button class="x" data-rm="${esc(id)}" title="Remove">✕</button>
      </div>` };
    }
    const thumb = c.cover && !DEMO ? `<img ${covAttr("/img?url="+encodeURIComponent(c.cover))} alt="" onerror="this.remove()"><div class="grad" style="${gradFor(title)}"></div>`
                                   : `<div class="grad" style="${gradFor(title)}"></div>`;
    const head = `<div class="row" data-qid="${esc(id)}"><div class="thumb">${thumb}</div><div class="body">`;
    if(s){
      const r=qLive(id, s, total);
      r.key="L|"+id+"|"+title+"|"+(c.cover||"");
      r.html = head+`<div class="r1"><span class="rttl">${esc(title)}</span><span class="rchip">${r.chip}</span></div>
        <div class="rmeta live">${r.meta}</div>
        <div class="track"><div class="${r.fill}" style="width:${r.w}"></div></div>
      </div></div>`;
      return r;
    }
    const partial = c.sel && c.sel.length && total && c.sel.length < total;
    const meta = partial ? `<b>${num(c.sel.length)}</b> of ${total} episodes` : `${total||"?"} episodes`;
    return { key:"Q|"+id+"|"+title+"|"+(c.cover||"")+"|"+meta, html: head+`<div class="r1"><span class="rttl">${esc(title)}</span><span class="rchip"><button class="x" data-rm="${esc(id)}" title="Remove">✕</button></span></div>
        <div class="rmeta">${meta}</div>
        <button class="epbtn" data-ep="${esc(id)}">☰ Choose episodes</button>
      </div></div>` };
  });
  const keys=rows.map(r=>r.key).join("\n");
  if(keys===_qKeys && el.children.length===rows.length){
    rows.forEach((r,i)=>{ if(!r.fill) return;                   // a job row: patch its live parts in place
      const row=el.children[i], f=row.querySelector(".fill");
      _html(row.querySelector(".rchip"), r.chip); _html(row.querySelector(".rmeta"), r.meta);
      if(f){ if(f.className!==r.fill) f.className=r.fill; if(f._w!==r.w){ f._w=r.w; f.style.width=r.w; } }
    });
  } else { _qKeys=keys; el.innerHTML=rows.map(r=>r.html).join(""); }
  updateDock();
}

/* ---------- dock ---------- */
// The job's bar: this run's bytes over the bytes it fetches (a size not looked up yet is estimated by the server).
// est = bytes still to add for series not prepared yet (Download with several series: each is prepared while the
// first ones already download), so the bar doesn't fill up and then fall back each time another series joins.
function dockFrac(st, est){
  const bt=num(st.bytes_total), need=num(st.eps_need);
  return bt>0 ? Math.min(1, num(st.bytes)/(bt+(est||0))) : (need>0 ? Math.min(1, num(st.eps_done)/need) : 0);
}
// Download mode: queue rows the engine hasn't prepared yet (no `need` from it) x the job's average episode size
function _unpreparedBytes(st){
  const need=num(st.eps_need), bt=num(st.bytes_total);
  if(st.mode==="library" || !(need>0 && bt>0)) return 0;
  let n=0; (st.series||[]).forEach(s=>{ if(s && s.need===undefined && s.status!=="unavailable") n+=num(s.total); });
  return n*(bt/need);
}
// High-water marks of this run's bars (dock + each queue row): the expected bytes are re-estimated as sizes arrive,
// so the ratio can dip; the bars never go back while the run lasts. Reset for every new run.
let _dockHW=0, _rowHW={}, _hwStarted=null;
function _hwReset(){ _dockHW=0; _rowHW={}; }
let _dockEnd=null, _dockEndT=0, _dockEndTimer=null;   // a job that just ended: its final numbers stay a moment (.finished)
const DOCK_END_MS=4000;
function dockEnded(st){                                // poll(): the running job just ended (st = its last reply)
  _dockEnd=null;
  // nothing was fetched (all already on disk, all locked, failed before starting): straight back to the queue view
  if(!(num(st.eps_need)>0 || (st.mode==="library" && st.phase==="done"))) return;
  _dockEnd=st; _dockEndT=Date.now()+DOCK_END_MS;
  clearTimeout(_dockEndTimer); _dockEndTimer=setTimeout(updateDock, DOCK_END_MS+50);
}
function updateDock(){
  const ids=Object.keys(cart).filter(id=>!(cart[id]&&cart[id].unavailable));  // 下架 cards never count toward the dock/Start
  const dock=$("#dock");
  dock.classList.add("show");                 // dock stays docked at all times
  const running=!!lastStatus.running, end=(!running && _dockEnd && Date.now()<_dockEndT) ? _dockEnd : null;
  const mode=running ? "run" : (end ? "end" : "idle"), f=$("#dockFill");
  if(dock._mode!==mode){                      // a new job's bar starts at 0 (no slide back from the last job's 100%)
    if(mode==="run"){ _dockHW=0; f.style.transition="none"; f.style.width="0%"; f._w="0%"; void f.offsetWidth; f.style.transition=""; }
    dock._mode=mode;
  }
  dock.classList.toggle("running", running);
  dock.classList.toggle("finished", !!end);
  // the signed API is down (backup source): "Paused" only while nothing transfers -- episodes that already have their
  // links still finish meanwhile, and then the dock stays the running one with a small "server busy" note
  const srvBusy=running && lastStatus.paused===true;
  const pausedDock=srvBusy && num(lastStatus.active)===0 && !(lastStatus.mode==="library" && lastStatus.phase!=="downloading");
  dock.classList.toggle("paused", pausedDock);
  dock.classList.toggle("busy", srvBusy && !pausedDock);
  $("#startBtn").style.display = running?"none":"";
  $("#cancelBtn").style.display = running?"":"none";
  $("#startBtn").disabled = ids.length===0;
  let n, unit, line;
  if(running || end){
    // live: MB/s, this run's episodes done / to fetch, bytes transferred / expected; ended: the final numbers
    const j=end||lastStatus, need=num(j.eps_need), done=Math.min(num(j.eps_done), need), bt=num(j.bytes_total);
    const b=bt>0 ? Math.min(num(j.bytes), bt) : num(j.bytes), lib=j.mode==="library";
    let frac=dockFrac(j, running ? _unpreparedBytes(j) : 0), wait=false, ok=false, stopped=false;
    if(running){
      const moving = num(j.active)>0 || num(j.rate)>0;
      n=fmtRate(j.rate); unit="MB/s";
      if(lib && j.phase!=="downloading"){     // still checking: the total grows batch by batch -> no % yet, counts only
        wait=true; if(!moving){ n="Checking…"; unit=""; }
        line = "Checking library…"+(num(j.to_check)>0 ? ` ${num(j.checked)}/${num(j.to_check)}` : "")
             + (need>0 ? ` · ${done}/${need} new episodes · ${fmtMB(b)}` : "");
      } else if(need>0) line=`${done}/${need} episodes`+(bt>0 ? ` · ${fmtMB(b)} of ${fmtMB(bt)}` : "");
      else{ wait=true;                        // nothing to measure yet
        line = lib ? ("Checking library…"+(num(j.to_check)>0 ? ` ${num(j.checked)}/${num(j.to_check)}` : "")) : "Preparing…"; }
      if(!wait){ frac=Math.max(frac, _dockHW); _dockHW=frac; }   // never back while the run lasts (see _dockHW)
      if(pausedDock){                         // the signed API is down and nothing transfers: the job waits (nothing is lost)
        n="Paused"; unit=""; line=(need>0 ? `${done}/${need} episodes · ` : "")+"waiting for server — retrying automatically";
      } else if(srvBusy && unit==="MB/s") unit="MB/s · server busy";   // link-holding episodes still finish
    } else {
      // ended: "✓ Done" (green) only when everything was really done -- every series read (a failed check batch is
      // not "up to date"), no series left incomplete / failed, every episode fetched
      const unread=num(j.unread), to=num(j.to_check);
      const bad=(j.series||[]).filter(s=>lib ? s.status==="error" : (s.status==="incomplete"||s.status==="failed")).length;
      // complete by the website's list only, never re-read (the run ended while the main server was down)
      const rechk=(j.series||[]).filter(s=>(s.status||s.state)==="recheck").length;
      const rn=rechk ? `${rechk} checked with the backup list — will re-check when the main server is back` : "";
      stopped = lib ? j.phase==="cancelled" : (j.series||[]).some(s=>s.status==="stopped");
      ok = done>=need && !bad && !rechk && !(lib && (unread>0 || (need===0 && to===0)));
      if(need===0) frac = ok ? 1 : 0;
      n = stopped ? "Stopped" : (ok ? "✓ Done" : "Finished"); unit="";
      if(need>0){
        line = `${done}/${need} episodes · ${fmtMB(b)}`+(!stopped && need>done ? ` · ${need-done} failed` : "")
             + (bad ? ` · ${bad} series ${lib ? "failed" : "incomplete"}` : "")
             + (lib && unread>0 ? ` · couldn't check ${unread} series` : "") + (rn ? " · "+rn : "") + lsnDockNote(j);
      } else if(stopped) line="Check stopped"+(rn ? " · "+rn : "");
      else if(lib && to===0) line="Nothing to check";
      else if(lib && unread>0) line = (unread>=to ? "Couldn't check your library — try again" : `Up to date · couldn't check ${unread} series`)+(rn ? " · "+rn : "");
      else line = rn || ((bad ? `${bad} series failed` : "Your library is up to date") + lsnDockNote(j));
    }
    $("#dockProg").classList.toggle("wait", wait);
    const w=(wait ? 0 : frac*100).toFixed(2)+"%";
    if(f._w!==w){ f._w=w; f.style.width=w; }
    f.classList.toggle("done", !!end && ok && !stopped);
    _txt("#dockPct", wait ? "—" : Math.floor(frac*100)+"%");
  } else {
    n=String(ids.length); unit="queued";
    const eps=ids.reduce((a,id)=>{const c=cart[id]||{}; return a+((c.sel&&c.sel.length)?c.sel.length:(c.total||0));},0);
    line = ids.length ? (eps? ("≈ "+eps+" episodes") : "episodes counted after resolve") : "nothing queued yet";
  }
  _txt("#dockN", n); _txt("#dockUnit", unit);
  const e=_txt("#dockEps", line); if(e.title!==line) e.title=line;   // a narrow dock cuts the line (ellipsis): the full text on hover
}

/* ---------- start / cancel ---------- */
// The server accepted a job (Download, or a Library Update). It can start AND finish between two status polls (e.g.
// every episode is already on disk), so no poll ever sees it running. Record it here: the next "idle" reply is its end,
// and the Library refresh, the Free n/2 chip, the finished-rows clean-up and the dock's final numbers still happen.
// Replies requested before now are dropped; one poll right away turns the dock to the running job.
function _jobAccepted(){ _runGen++; _wasRunning=true; _dockEnd=null; _hwReset(); poll(); }
/* Download settings (the download bar): Quality, Series = dramas at once, Episodes = episodes of each drama at once.
   Series x Episodes is at most DL_MAX: raising one lowers the other to fit (never raises it). Saved per viewer and
   sent with every Download and Library Update (the same engine). */
const DL_MAX=16, DL_KEY="hg_dl";
function vuShow(sel){                                 // "2 series" -> bold "2" + muted "series" (the design rule above)
  const v=sel.parentElement.querySelector(".cs-v"); if(!v) return;
  const o=sel.options[sel.selectedIndex], t=o?o.text:"", i=t.indexOf(" ");
  v.querySelector(".cs-n").textContent=i<0?t:t.slice(0,i);
  v.querySelector(".cs-u").textContent=i<0?"":t.slice(i+1);
}
function vuPin(sel){                                  // as wide as its widest bold-number + muted-unit value, not the
  const v=sel.parentElement.querySelector(".cs-v");   // plain option text (a big gap before the chevron) -- and fixed,
  if(!v) return;                                      // so the bar doesn't shift when the value changes
  const cur=sel.selectedIndex; let w=0; sel.style.width=sel.style.minWidth="";
  for(let i=0;i<sel.options.length;i++){ sel.selectedIndex=i; vuShow(sel); w=Math.max(w, parseFloat(getComputedStyle(v).width)||0); }
  sel.selectedIndex=cur; vuShow(sel);
  if(w) sel.style.width=sel.style.minWidth=Math.ceil(12+w+24)+"px";   // + the select's 12px / 24px side padding
}
function dlSettings(){
  return {quality:$("#quality").value, series:Number($("#seriesAtOnce").value)||2, episodes:Number($("#epsAtOnce").value)||4};
}
function dlSave(){ try{ localStorage.setItem(DL_KEY, JSON.stringify(dlSettings())); }catch(e){} }
function dlFit(changed){                              // lower the OTHER control so Series x Episodes <= DL_MAX
  const s=$("#seriesAtOnce"), e=$("#epsAtOnce"), other=changed===s?e:s;
  const max=Math.max(1, Math.floor(DL_MAX/(Number(changed.value)||1)));
  if((Number(other.value)||1)>max) other.value=String(max);
  vuShow(s); vuShow(e);
}
function dlLoad(){
  let v=null, old=false; try{ v=JSON.parse(localStorage.getItem(DL_KEY)||"null"); }catch(e){}
  if(!v){ try{ const u=JSON.parse(localStorage.getItem("hg_ub")||"null");   // 1.0.0.71's Update all Quality: keep it
    if(u && typeof u==="object" && typeof u.quality==="string"){ v={quality:u.quality}; old=true; } }catch(e){} }
  const q=$("#quality"), s=$("#seriesAtOnce"), e=$("#epsAtOnce");
  const has=(sel,x)=>x!=null && [...sel.options].some(o=>o.value===String(x));
  q.value=(v && has(q,v.quality))?v.quality:"1080p";
  s.value=(v && has(s,v.series))?String(v.series):"2";
  e.value=(v && has(e,v.episodes))?String(v.episodes):"4";
  dlFit(s);
  if(old) dlSave();                                   // saved as the download bar's own before hg_ub is dropped
}
$("#quality").addEventListener("change", dlSave);
$("#seriesAtOnce").addEventListener("change", ()=>{ dlFit($("#seriesAtOnce")); dlSave(); });   // dlFit also redraws both
$("#epsAtOnce").addEventListener("change", ()=>{ dlFit($("#epsAtOnce")); dlSave(); });
dlLoad();

async function start(){
  const ids=Object.keys(cart).filter(id=>!(cart[id]&&cart[id].unavailable)); if(!ids.length) return;   // #4: never submit unavailable placeholders
  $("#startBtn").disabled=true;
  _runGen++;                                          // a pending "clear finished rows" must not touch the rows being sent now
  const ranges={};
  ids.forEach(id=>{ const c=cart[id]; if(c && c.sel && c.total && c.sel.length && c.sel.length<c.total){ ranges[id]=compressRange(c.sel); } });
  const scores={}; ids.forEach(id=>{ const sc=(cart[id]||{}).score; if(sc) scores[id]=String(sc); });
  const payload={series_ids:ids,ranges,scores,...dlSettings()};   // + the download bar's Quality / Series / Episodes
  try{
    const j = DEMO ? demoStart(payload) : await (await fetch("/dl/submit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})).json();
    if(!j.ok){
      if(j.reason==='free_limit') promptActivate(j);
      else if(/already running/i.test(j.error||"")){
        // Update All (or another download) holds the single download slot. Offer to stop it
        // rather than silently failing, then the user can start this download.
        if(await ask("An update or download is already running.", "Stop it and free up downloads?", {ok:"Stop it", danger:true})){
          try{ await fetch("/dl/cancel",{method:"POST"}); toast("Stopping the current job — try Download again in a moment"); }
          catch(e){ toast("Couldn't stop the current job", true); }
        }
      }
      else toast(j.error||"Couldn't start", true);
      $("#startBtn").disabled=false;
      clearFinishedFromQueue();                       // nothing new started: finish the clean-up the press postponed
    } else {
      _jobAccepted();                                  // (see there: a run that ends before any poll still "ends")
      if(j.need_license){ promptActivate(j); }         // some started, some held back by the free limit
      else toast("Download started");
      if(!(DEMO||ALLOW_DEMO)){ refreshAccount(); setTimeout(loadLibrary,1200); setTimeout(loadLibrary,3500); }   // pop the series into the Library right away
    }
  }catch(e){ toast("Start failed: "+e, true); $("#startBtn").disabled=false; clearFinishedFromQueue(); }
}
async function cancel(){ $("#cancelBtn").disabled=true;
  try{ if(DEMO) demoCancel(); else await fetch("/dl/cancel",{method:"POST"}); toast("Stopping…"); }catch(e){}
  setTimeout(()=>$("#cancelBtn").disabled=false,800); }

/* ---------- episode picker (pick a subset per series; default = whole series) ---------- */
const epCache={};             // series_id -> [episode indices]
let epCur=null, epSel=null;   // current series id + working Set of selected indices
function compressRange(arr){  // [1,2,3,5,7,8] -> "1-3,5,7-8"
  const a=[...arr].sort((x,y)=>x-y); const out=[]; let i=0;
  while(i<a.length){ let j=i; while(j+1<a.length && a[j+1]===a[j]+1) j++;
    out.push(i===j? ""+a[i] : a[i]+"-"+a[j]); i=j+1; }
  return out.join(",");
}
async function openEpModal(id){
  const c=cart[id]; if(!c) return;
  epCur=id; $("#epTitle").textContent=c.title||id; $("#epSub").textContent="loading episodes…"; $("#epGrid").innerHTML="";
  $("#epModal").hidden=false;
  let eps=epCache[id];
  if(!eps){
    if(DEMO){ eps=Array.from({length:c.total||24},(_,i)=>i+1); }
    else{ try{ const j=await (await fetch("/dl/episodes?series_id="+encodeURIComponent(id))).json();
                eps=(j.episodes||[]).map(Number).filter(n=>Number.isInteger(n)&&n>0);   // platform indices: whole numbers only
                if(j.total) c.total=num(j.total); }
          catch(e){ eps=Array.from({length:c.total||0},(_,i)=>i+1); } }
    epCache[id]=eps;
    if(epCur!==id) return;          // closed, or reopened for another series, while this list loaded: not ours to draw
  }
  epSel=(c.sel&&c.sel.length)? new Set(c.sel) : new Set(eps);   // default: all selected
  $("#epSub").textContent=(c.total||eps.length)+" episodes · tap to pick";
  renderEpGrid(eps);
}
function renderEpGrid(eps){
  $("#epGrid").innerHTML=eps.map(n=>`<button class="epchip" data-ei="${num(n)}" aria-pressed="${epSel.has(n)}">${num(n)}</button>`).join("");
  $("#epCount").textContent=`${epSel.size} / ${eps.length} selected`;
}
function closeEp(){ $("#epModal").hidden=true; epCur=null; epSel=null; }
$("#epGrid").addEventListener("click",e=>{ const b=e.target.closest("[data-ei]"); if(!b||!epSel) return;
  const n=Number(b.dataset.ei);
  if(epSel.has(n)){ epSel.delete(n); b.setAttribute("aria-pressed","false"); } else { epSel.add(n); b.setAttribute("aria-pressed","true"); }
  $("#epCount").textContent=`${epSel.size} / ${(epCache[epCur]||[]).length} selected`; });
$("#epAll").onclick=()=>{ const eps=epCache[epCur]||[]; epSel=new Set(eps); renderEpGrid(eps); };
$("#epNone").onclick=()=>{ epSel=new Set(); renderEpGrid(epCache[epCur]||[]); };
$("#epClose").onclick=closeEp; $("#epCancel").onclick=closeEp;
$("#epModal").addEventListener("click",e=>{ if(backdropClick(e)) closeEp(); });
$("#epDone").onclick=()=>{
  const c=cart[epCur], eps=epCache[epCur]||[]; if(!c){ closeEp(); return; }
  if(epSel.size===0){ toast("Nothing selected — keeping the whole series"); delete c.sel; }
  else if(epSel.size>=eps.length){ delete c.sel; }            // full selection = whole series
  else { c.sel=[...epSel].sort((a,b)=>a-b); }
  saveCart(); renderQueue(); closeEp();
};

/* ---------- output folder ---------- */
async function loadDir(){ /* library folder is set via the native picker now — no path input to populate */ }
async function setDir(){
  const p=$("#outdir").value.trim();
  try{
    const j = DEMO ? {ok:true,output_dir:p||"D:\\Dramas"} : await (await fetch("/dl/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({output_dir:p})})).json();
    if(j.ok){ $("#dirNote").innerHTML='Saved → <span class="path">'+esc(j.output_dir)+'</span> — episodes land here.'; $("#outdir").value=j.output_dir; toast("Folder saved"); }
    else $("#dirNote").innerHTML='<span class="err">'+esc(j.error||"Couldn't save")+'</span>';
  }catch(e){ $("#dirNote").innerHTML='<span class="err">'+esc(""+e)+'</span>'; }
}
async function openDir(){
  if(DEMO){ toast("Preview mode — on the live app this opens the folder in your file browser"); return; }
  try{ const j=await (await fetch("/dl/open",{method:"POST"})).json();
    if(!j.ok) toast(j.error||"Couldn't open folder", true);
  }catch(e){ toast("Open failed: "+e, true); }
}
async function pickDir(){
  if(DEMO){ toast("Preview mode — on the live app this opens a native folder picker"); return; }
  const b=$("#setFolderToggle"); if(b){ b.disabled=true; b.textContent="Choosing…"; }
  try{ const j=await (await fetch("/dl/pick",{method:"POST"})).json();
    if(j.ok && j.path){                                   // native pick -> save directly (no text input)
      const s=await (await fetch("/dl/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({output_dir:j.path})})).json();
      toast(s.ok?("Folder saved → "+s.output_dir):(s.error||"Couldn't save"), !s.ok);
    } else if(j && j.error){ toast(j.error, true); }
  }catch(e){ toast("Picker failed: "+e, true); }
  if(b){ b.disabled=false; b.textContent="📁 Set folder"; }
}

/* ---------- Library (local downloaded series) ---------- */
function libCards(items){
  return items.map(x=>{
    const name=x.name, title=x.title||name;
    const total=num(x.total), local=num(x.local), nNew=num(x.new), nFresh=num(x.fresh);
    const revDeg = total>0 ? Math.max(0,Math.min(1,local/total))*360 : 360;   // completeness reveal (App Store clockwork)
    const grad=`<div class="grad" style="${gradFor(title)}"></div>`;
    let img="";
    if(x.poster) img=`<img src="/dl/poster?name=${encodeURIComponent(name)}" alt="" loading="lazy" onerror="this.remove()">`;
    else if(x.cover) img=`<img ${covAttr("/img?url="+encodeURIComponent(x.cover))} alt="" loading="lazy" onerror="this.remove()">`;
    const _sz = fmtSize(x.size); const eps = (total ? `${local}/${total}` : `${local} eps`) + (_sz?` · ${_sz}`:"");
    const avail = nNew>0 ? `<span class="newbadge" title="${nNew} more episode(s) available — press Update">+${nNew}</span>` : "";
    const fresh = nFresh>0 ? `<span class="freshbadge" title="${nFresh} newly downloaded episode(s) — click to view">${nFresh} new</span>` : "";
    const score = x.score ? `<span class="score" title="rating">★ ${esc(String(x.score))}</span>` : "";
    return `<div class="poster libcard" data-name="${esc(name)}" data-sid="${esc(String(x.series_id||''))}" data-total="${total}" title="Click to open · right-click for actions">
      <div class="art">${grad}${img}<div class="dim" style="--rev:${revDeg.toFixed(1)}deg"></div><div class="scrim"></div>
        <div class="dlstate"></div><span class="selmark"></span>
        <span class="eps"><span>${eps}</span></span>${avail}${fresh}${score}
      </div>
      <div class="ttl">${esc(title)}</div>
    </div>`;
  }).join("");
}
let libItems=[], libSortMode='recent';   // default: Newest downloaded
function _score(x){ const n=parseFloat(x.score); return isNaN(n)?-1:n; }
function sortLibItems(items, mode){
  const arr=items.slice();
  const cmp={
    new:        (a,b)=> (b.fresh-a.fresh) || (b.updated-a.updated),
    recent:     (a,b)=> (b.updated-a.updated),
    rating:     (a,b)=> (_score(b)-_score(a)) || (b.updated-a.updated),
    rating_asc: (a,b)=>{ const x=_score(a),y=_score(b), ax=x<0, ay=y<0; if(ax!==ay) return ax?1:-1; return (x-y)||(b.updated-a.updated); },
    az:         (a,b)=> String(a.title||a.name).localeCompare(String(b.title||b.name)),
  }[mode];
  if(cmp) arr.sort(cmp);
  return arr;
}
function renderLib(){
  const grid=$("#libGrid");
  $("#libCount").textContent = libItems.length ? ("· "+libItems.length) : "";
  if(!libItems.length){ grid.innerHTML='<div class="empty" style="grid-column:1/-1"><div class="big">No downloads yet</div><div class="sm">Download a series and it shows up here.</div></div>'; return; }
  grid.innerHTML = libCards(sortLibItems(libItems, libSortMode));
  applySelUI();
}
function sortLib(mode){ libSortMode=mode; renderLib(); }
/* ---- Library select-mode + bulk actions (Phase 1) ---- */
let libSelectMode=false; const libSelected=new Set();
function fmtSize(b){ b=+b||0; if(b<=0) return ""; const u=["B","KB","MB","GB","TB"]; let i=0;
  while(b>=1024&&i<u.length-1){ b/=1024; i++; } return (i<=1?Math.round(b):(b>=100?Math.round(b):b.toFixed(1)))+" "+u[i]; }
function applySelUI(){
  const grid=$("#libGrid"); if(grid){ grid.classList.toggle("selmode", libSelectMode);
    grid.querySelectorAll(".libcard").forEach(c=>c.classList.toggle("sel", libSelected.has(c.dataset.name))); }
  const bar=$("#libBulk"); if(bar) bar.hidden=!libSelectMode;
  const n=libSelected.size; const cnt=$("#libBulkCount"); if(cnt) cnt.textContent=n+" selected";
  const sb=$("#selectLib"); if(sb){ sb.classList.toggle("on", libSelectMode); sb.textContent=libSelectMode?"✕ Done":"☑ Select"; }
  ["libBulkDelete","libBulkSeen","libBulkPlay","libBulkConvert","libBulkMerge","libBulkUpdate"].forEach(id=>{ const b=$("#"+id); if(b) b.disabled=(n===0); });
}
function enterSelect(){ libSelectMode=true; applySelUI(); }
function exitSelect(){ libSelectMode=false; libSelected.clear(); applySelUI(); }
function toggleSelectMode(){ libSelectMode?exitSelect():enterSelect(); }
function toggleLibSel(name, el){ if(libSelected.has(name)){ libSelected.delete(name); el&&el.classList.remove("sel"); }
  else { libSelected.add(name); el&&el.classList.add("sel"); } applySelUI(); }
function libSelectAll(){ libItems.forEach(x=>libSelected.add(x.name)); applySelUI(); }
function libSelectClear(){ libSelected.clear(); applySelUI(); }
async function libBulkSeen(){ const names=[...libSelected]; if(!names.length) return;
  try{ await fetch("/dl/library/seen",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names})}); }catch(e){}
  await loadLibrary(); exitSelect(); toast("Marked "+names.length+" as seen"); }
async function libBulkDelete(){ const names=[...libSelected]; if(!names.length) return;
  if(!(await ask("Move "+names.length+" series to Trash?", "You can undo right after — nothing is permanently erased.", {ok:"Move to Trash", danger:true}))) return;
  let j; try{ j=await (await fetch("/dl/library/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names})})).json(); }
  catch(e){ toast("Delete failed",true); return; }
  const moved=(j&&j.moved)||[]; await loadLibrary(); exitSelect();
  if(moved.length) showUndo(moved.length+" moved to Trash", moved.map(m=>m.token));
  else toast("Nothing deleted",true);
}
function libBulkPlay(){ const names=[...libSelected]; if(!names.length) return; exitSelect();
  openPlayer(names[0], null, names.slice(1)); }   // play them back-to-back (rest queued after the first)
function libBulkConvert(){ const names=[...libSelected]; if(!names.length) return; convertNames(names); }   // opens the convert dialog for all selected
async function libBulkUpdate(){ const names=[...libSelected]; if(!names.length) return;
  try{ const j=await (await fetch("/dl/library/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names,...dlSettings()})})).json();
    if(j.ok) _jobAccepted();
    toast(j.ok?("Checking "+names.length+" series for new episodes…"):(j.error||"Couldn't start update"), !j.ok);
  }catch(e){ toast("Update failed",true); }
  exitSelect(); }
async function libBulkMerge(){ const names=[...libSelected]; if(!names.length) return; exitSelect();
  let ok=0;
  for(let k=0;k<names.length;k++){ const r=await mergeOnce(names[k], "("+(k+1)+"/"+names.length+") "); if(r.ok) ok++; }
  showMerge("✓ Merged "+ok+" of "+names.length+" series", {autohide:9000}); loadLibrary(); }
let _undoT;
function showUndo(msg, tokens){ const el=$("#libUndo"); if(!el){ toast(msg); return; }
  $("#libUndoMsg").textContent=msg; el.hidden=false; requestAnimationFrame(()=>el.classList.add("show"));
  clearTimeout(_undoT); _undoT=setTimeout(()=>{ el.classList.remove("show"); setTimeout(()=>{el.hidden=true;},300); }, 7000);
  $("#libUndoBtn").onclick=async()=>{ clearTimeout(_undoT); el.classList.remove("show"); setTimeout(()=>{el.hidden=true;},300);
    let ok=0; for(const t of tokens){ try{ const r=await (await fetch("/dl/library/restore",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:t})})).json(); if(r&&r.ok) ok++; }catch(e){} }
    await loadLibrary(); toast(ok?("Restored "+ok):"Restore failed", !ok); };
}
/* ---- Library merge (Phase 2): combine a series into one MP4 with chapters ---- */
let _mergePoll, _mergeHideT;
function showMerge(msg, opts){ opts=opts||{}; const el=$("#libMerge"); if(!el){ toast(msg); return; }
  $("#libMergeMsg").textContent=msg;
  const btn=$("#libMergeBtn"); btn.hidden=!opts.openName;
  if(opts.openName){ btn.textContent = opts.openSub ? "Open H.264 folder" : "Open folder";
    btn.onclick=()=> opts.openSub ? openH264Folder(opts.openName) : openSeries(opts.openName); }
  el.hidden=false; requestAnimationFrame(()=>el.classList.add("show"));
  clearTimeout(_mergeHideT);
  if(opts.autohide) _mergeHideT=setTimeout(()=>{ el.classList.remove("show"); setTimeout(()=>{el.hidden=true;},300); }, opts.autohide);
}
/* Merge progress shown as the iOS clockwork poster-reveal on the card (like Update) + a % chip. */
function _libCardByName(name){ return [...document.querySelectorAll('#libGrid .libcard')].find(c=>c.dataset.name===name); }
function _mergeCard(name, pct){ const c=_libCardByName(name); if(!c) return;
  c.classList.add('act','st-merging'); c.classList.remove('st-done','st-error','st-downloading','st-queued');
  const dim=c.querySelector('.dim'); if(dim) dim.style.setProperty('--rev',(Math.max(0,Math.min(100,pct))/100*360).toFixed(1)+'deg');
  const ds=c.querySelector('.dlstate'); if(ds) ds.textContent=(pct||0)+'%'; }
function _mergeCardDone(name){ const c=_libCardByName(name); if(!c) return;
  c.classList.remove('act','st-merging'); const dim=c.querySelector('.dim'); if(dim) dim.style.removeProperty('--rev');
  const ds=c.querySelector('.dlstate'); if(ds) ds.textContent=''; }
function mergeOnce(name, prefix, variant){   // resolves {ok, file?, error?} when this series' merge finishes
  prefix = prefix||""; variant = variant||"original";
  const verb = variant==="h264" ? "Merging H.264" : "Merging";
  return new Promise(async(resolve)=>{
    let s; try{ s=await (await fetch("/dl/library/merge",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name, variant})})).json(); }
    catch(e){ resolve({ok:false,error:"network error"}); return; }
    if(!s.ok){ resolve({ok:false,error:s.error||"couldn't start"}); return; }
    showMerge(prefix+verb+" “"+name+"” … 0%"); _mergeCard(name, 0);
    const iv=setInterval(async()=>{
      let st; try{ st=await (await fetch("/dl/library/merge-status")).json(); }catch(e){ return; }
      if(st.running){ showMerge(prefix+verb+" “"+(st.name||name)+"” … "+(st.pct||0)+"%"); _mergeCard(name, st.pct||0); return; }
      clearInterval(iv); _mergeCardDone(name);
      resolve(st.error? {ok:false,error:st.error} : {ok:true, file:st.file});
    }, 800);
  });
}
async function mergeSeries(name){
  const r=await mergeOnce(name);
  if(r.ok) showMerge("✓ Merged into “"+(r.file||"one file")+"”", {openName:name, autohide:12000});
  else showMerge("Merge failed: "+(r.error||""), {autohide:7000});
}
async function mergeH264Series(name){   // merge the converted copies in <series>/H264/
  const r=await mergeOnce(name, "", "h264");
  if(r.ok) showMerge("✓ Merged H.264 into “"+(r.file||"one file")+"”", {openName:name, openSub:"H264", autohide:12000});
  else showMerge("H.264 merge failed: "+(r.error||""), {autohide:7000});
  loadLibrary();
}
function mergeH264Names(names){ if(!names.length) return; if(libSelectMode) exitSelect(); mergeH264Series(names[0]); }
async function openH264Folder(name){
  try{ const j=await (await fetch("/dl/library/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name, sub:"H264"})})).json();
    if(!j.ok) toast(j.error||"No converted files yet", true);
  }catch(e){ toast("Open failed",true); }
}
/* ---- Library in-app player: resume + auto-play next (Phase 3) ---- */
const WATCH_KEY="hg_watch";
function loadWatch(){ try{ return JSON.parse(localStorage.getItem(WATCH_KEY)||"{}"); }catch(e){ return {}; } }
function saveWatch(w){ try{ localStorage.setItem(WATCH_KEY, JSON.stringify(w)); }catch(e){} }
function getResume(name){ const w=loadWatch(); return w[name]||null; }
function setResume(name, ep, t){ if(!name) return; const w=loadWatch(); w[name]={ep:ep, t:Math.floor(t||0), updated:Date.now()}; saveWatch(w); }
let _lp={ name:"", eps:[], ep:0, title:"", saveT:0, followUp:[], act:0, speed:1 };
function _vids(){ return [$("#lpVidA"), $("#lpVidB")]; }
function _cur(){ return _vids()[_lp.act]; }
function _pre(){ return _vids()[1-_lp.act]; }
function _epUrl(name,ep){ return "/dl/library/file?name="+encodeURIComponent(name)+"&ep="+ep; }
let _lpSeq=0;           // only the newest openPlayer() may draw; closePlayer() bumps it too
async function openPlayer(name, ep, followUp){
  followUp = followUp||[];
  const seq=++_lpSeq;
  let j; try{ j=await (await fetch("/dl/library/episodes?name="+encodeURIComponent(name))).json(); }
  catch(e){ if(seq===_lpSeq) toast("Couldn't load episodes",true); return; }
  if(seq!==_lpSeq) return;             // another series was opened (or the player closed) while this loaded
  const eps=(j.downloaded||[]).slice().sort((a,b)=>a-b);
  if(!eps.length){ if(followUp.length){ openPlayer(followUp[0], null, followUp.slice(1)); return; } toast("No episodes downloaded yet",true); return; }
  const r=getResume(name); let startT=0;
  if(ep==null && r){ ep=r.ep; startT=r.t||0; }
  if(ep==null || !eps.includes(ep)) ep=eps[0];
  _lp={ name:name, eps:eps, ep:ep, title:(j.title||name), saveT:0, followUp:followUp, act:0, speed:(_lp.speed||1) };
  _vids().forEach((vd,i)=>{ try{ vd.pause(); }catch(e){} vd.hidden=(i!==0); vd.removeAttribute("src"); vd.dataset.ep=""; vd.dataset.name=""; });
  $("#libPlayer").hidden=false;
  _lpPlay(ep, startT);
}
function _lpPlay(ep, seekTo){                          // load + play `ep` in the ACTIVE video
  _lp.ep=ep; const v=_cur();
  if(String(v.dataset.ep)!==String(ep) || v.dataset.name!==_lp.name){
    v.dataset.ep=String(ep); v.dataset.name=_lp.name; v.src=_epUrl(_lp.name,ep); v.load();
  }
  v.hidden=false; _pre().hidden=true; v.playbackRate=_lp.speed||1;
  const go=()=>{ if(seekTo>2 && (!v.duration||seekTo<v.duration-3)){ try{ v.currentTime=seekTo; }catch(e){} } v.play().catch(()=>{}); };
  if(v.readyState>=1) go(); else { const onMeta=()=>{ v.removeEventListener("loadedmetadata",onMeta); go(); }; v.addEventListener("loadedmetadata",onMeta); }
  _lpAfter(ep, seekTo||0);
}
function _lpAfter(ep, pos){                             // update chrome + preload the NEXT episode
  const posn=_lp.eps.indexOf(ep)+1;
  const queued=(_lp.followUp&&_lp.followUp.length)?("  ·  "+_lp.followUp.length+" more queued"):"";
  $("#lpTitle").textContent=_lp.title;
  $("#lpSub").textContent="Episode "+ep+"  ·  "+posn+" / "+_lp.eps.length+queued;
  $("#lpPrev").disabled=(posn<=1);
  $("#lpNext").disabled=(posn>=_lp.eps.length && !(_lp.followUp&&_lp.followUp.length));
  setResume(_lp.name, ep, pos||0);
  _lpPreloadNext();
}
function _lpPreloadNext(){                              // buffer the next episode into the hidden video -> seamless jump
  const i=_lp.eps.indexOf(_lp.ep); const pv=_pre();
  if(i>=0 && i<_lp.eps.length-1){
    const ne=_lp.eps[i+1];
    if(String(pv.dataset.ep)!==String(ne) || pv.dataset.name!==_lp.name){
      pv.dataset.ep=String(ne); pv.dataset.name=_lp.name; pv.preload="auto"; pv.src=_epUrl(_lp.name,ne);
      pv.playbackRate=_lp.speed||1; try{ pv.load(); pv.pause(); }catch(e){}
    }
  } else { pv.removeAttribute("src"); pv.dataset.ep=""; }
}
function lpNext(){
  const i=_lp.eps.indexOf(_lp.ep);
  if(i>=0 && i<_lp.eps.length-1){
    try{ if(_cur().currentTime>0) setResume(_lp.name,_lp.ep,_cur().currentTime); }catch(e){}
    const ne=_lp.eps[i+1], pv=_pre();
    if(String(pv.dataset.ep)===String(ne) && pv.dataset.name===_lp.name){   // SEAMLESS: hidden video already buffered
      const old=_cur(); try{ old.pause(); }catch(e){}
      _lp.act=1-_lp.act; _lp.ep=ne; const nv=_cur();
      nv.hidden=false; old.hidden=true; nv.playbackRate=_lp.speed||1;
      try{ nv.currentTime=0; }catch(e){} nv.play().catch(()=>{});
      _lpAfter(ne,0);
    } else { _lpPlay(ne,0); }
  } else if(_lp.followUp&&_lp.followUp.length){ openPlayer(_lp.followUp[0], null, _lp.followUp.slice(1)); }
}
function lpPrev(){ const i=_lp.eps.indexOf(_lp.ep); if(i>0){ try{ if(_cur().currentTime>0) setResume(_lp.name,_lp.ep,_cur().currentTime); }catch(e){} _lpPlay(_lp.eps[i-1],0); } }
function lpSetSpeed(x){ _lp.speed=+x||1; _vids().forEach(v=>{ try{ v.playbackRate=_lp.speed; }catch(e){} }); }
async function lpPip(){ try{ if(document.pictureInPictureElement) await document.exitPictureInPicture(); else await _cur().requestPictureInPicture(); }catch(e){ toast("Picture-in-picture isn't available here",true); } }
function closePlayer(){ _lpSeq++; try{ const v=_cur(); if(v.currentTime>0) setResume(_lp.name,_lp.ep,v.currentTime); }catch(e){}
  _vids().forEach(vd=>{ try{ vd.pause(); vd.removeAttribute("src"); vd.load(); }catch(e){} });
  $("#libPlayer").hidden=true; loadLibrary(); }
function lpOpenSystem(){ try{ fetch("/dl/library/play",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:_lp.name,ep:_lp.ep})}); toast("Opening in your system player…"); }catch(e){} }
(function initLibPlayer(){
  _vids().forEach(v=>{ if(!v) return;
    v.addEventListener("timeupdate", function(){ if(this!==_cur()) return; const now=Date.now(); if(now-_lp.saveT>4000){ _lp.saveT=now; try{ setResume(_lp.name,_lp.ep,this.currentTime); }catch(e){} } });
    v.addEventListener("ended", function(){ if(this!==_cur()) return; setResume(_lp.name,_lp.ep,0);
      const i=_lp.eps.indexOf(_lp.ep); const hasNext=(i>=0 && i<_lp.eps.length-1); const auto=$("#lpAuto").checked; const hasQueue=(_lp.followUp&&_lp.followUp.length);
      if(auto && (hasNext||hasQueue)){ lpNext(); }
      else if(!hasNext && !hasQueue){ toast("Finished — that's the last downloaded episode"); } });
    v.addEventListener("error", function(){ if(this!==_cur()) return; if(!$("#libPlayer").hidden && this.getAttribute("src")){ toast("Can't play this episode in-app — use “Open in player ↗”", true); } });
  });
  $("#lpClose").onclick=closePlayer; $("#lpPrev").onclick=lpPrev; $("#lpNext").onclick=lpNext; $("#lpSystem").onclick=lpOpenSystem; $("#lpPip").onclick=lpPip;
  const sp=$("#lpSpeed"); if(sp) sp.onchange=()=>lpSetSpeed(sp.value);
  $("#libPlayer").addEventListener("click",e=>{ if(backdropClick(e)) closePlayer(); });
  // keyboard: ← prev episode, → next episode, space play/pause, Esc close (capture beats the video's default ±5s arrow-seek)
  document.addEventListener("keydown", e=>{
    if($("#libPlayer").hidden) return;
    if(e.key==="Escape"){ e.preventDefault(); closePlayer(); return; }      // always, whichever control has focus
    // Only a text field keeps its keys, and a focused dropdown (⏩ speed) keeps its own ←/→ -- touching the
    // speed or the Auto-play checkbox used to switch the player's arrows and Space off until a click elsewhere.
    const t=e.target||{}, tag=t.tagName||"";
    if(tag==="TEXTAREA" || t.isContentEditable || (tag==="INPUT" && !/^(checkbox|radio|button)$/i.test(t.type||""))) return;
    if(tag==="SELECT" && e.key!==" ") return;
    if(e.key==="ArrowRight"){ e.preventDefault(); e.stopPropagation(); lpNext(); }
    else if(e.key==="ArrowLeft"){ e.preventDefault(); e.stopPropagation(); lpPrev(); }
    else if(e.key===" "){ e.preventDefault(); e.stopPropagation(); const v=_cur(); if(v.paused) v.play().catch(()=>{}); else v.pause(); }
  }, true);
})();
async function loadLibrary(){
  if(DEMO || ALLOW_DEMO) return;
  try{
    const j = await (await fetch("/dl/library")).json();
    libItems = j.items||[];
    renderLib();
  }catch(e){}
}
let _libEpName="";
const LIBEP_MAX_CELLS=3000;                        // episode cells the series-detail grid draws at most
function sdSetH264(h){ h=h||0;                    // show Merge H.264 in the detail panel only once ≥2 converted
  const mh=$("#sdMergeH264"); if(mh) mh.hidden = h<2;
}
async function openLibEpisodes(name){
  _libEpName=name;
  const modal=$("#libEpModal"), grid=$("#libEpGrid");
  const it=(libItems||[]).find(x=>x.name===name)||{};
  $("#libEpTitle").textContent=it.title||name; $("#libEpSub").textContent='';
  // cover: local poster -> catalog cover -> gradient
  const cov=$("#sdCover");
  let cimg=''; if(it.poster) cimg='<img src="/dl/poster?name='+encodeURIComponent(name)+'" alt="" onerror="this.remove()">';
  else if(it.cover) cimg='<img '+covAttr("/img?url="+encodeURIComponent(it.cover))+' alt="" onerror="this.remove()">';
  cov.innerHTML='<div class="grad" style="'+(typeof gradFor==='function'?gradFor(it.title||name):'')+'"></div>'+cimg;
  // play/resume label
  const rw=(typeof getResume==='function')?getResume(name):null;
  const pl=$("#sdPlayLbl"); if(pl) pl.textContent = rw ? ('Resume E'+rw.ep) : 'Play';
  // initial meta from the library card data (refined after episodes load)
  const _sz=(typeof fmtSize==='function')?fmtSize(it.size):'';
  $("#sdMeta").textContent = (it.total?((it.local||0)+'/'+it.total+' episodes'):((it.local||0)+' episodes'))+(_sz?('  ·  '+_sz):'')+(it.score?('  ·  ★ '+it.score):'');
  sdSetH264(it.h264);                              // instant hint from the library card; refined after episodes load
  grid.innerHTML='<div class="sm" style="grid-column:1/-1;color:var(--muted);padding:24px;text-align:center">Loading episodes…</div>';
  modal.hidden=false;
  let j; try{ j=await (await fetch("/dl/library/episodes?name="+encodeURIComponent(name))).json(); }
  catch(e){ if(_libEpName!==name || modal.hidden) return; grid.innerHTML='<div class="sm" style="grid-column:1/-1;padding:24px">Couldn\'t load episodes.</div>'; return; }
  // closed, or reopened for another series, while this loaded: its Play/Delete/Convert act on _libEpName, so don't draw
  if(_libEpName!==name || modal.hidden) return;
  if(j.error){ grid.innerHTML='<div class="sm" style="grid-column:1/-1;padding:24px">'+esc(j.error)+'</div>'; return; }
  $("#libEpTitle").textContent=j.title||name;
  // odd data (a non-number total, a non-list downloaded / episodes) reads as none; episode numbers are whole numbers >= 1
  const dls=(Array.isArray(j.downloaded)?j.downloaded:[]).filter(n=>Number.isInteger(n) && n>0);
  const tn=Number(j.total), total=Number.isFinite(tn) && tn>0 ? Math.floor(tn) : 0;
  const have=new Set(dls), freshSet=new Set((Array.isArray(j.episodes)?j.episodes:[]).filter(e=>e && e.fresh).map(e=>e.index));
  const max = total || dls.reduce((a,n)=>n>a?n:a, 0);   // a loop, not Math.max(...list): a huge list can't overflow the stack
  $("#libEpSub").textContent = dls.length+' of '+(total||max||'?')+' downloaded'+(j.fresh?('  ·  '+j.fresh+' new'):'');
  const _sz2=(typeof fmtSize==='function')?fmtSize(it.size):'';
  $("#sdMeta").textContent = dls.length+'/'+(total||max||'?')+' episodes'+(_sz2?('  ·  '+_sz2):'')+(it.score?('  ·  ★ '+it.score):'')+(j.fresh?('  ·  '+j.fresh+' new'):'');
  sdSetH264(j.h264);                               // authoritative count from the H264 subfolder scan
  let html='';
  const cells=Math.min(max, LIBEP_MAX_CELLS);      // an absurd total can't build a grid big enough to freeze the page
  for(let i=1;i<=cells;i++){ const dl=freshSet.has(i)||have.has(i); const cls = freshSet.has(i)?'libep fresh':(have.has(i)?'libep have':'libep miss'); html+='<div class="'+cls+'"'+(dl?(' data-i="'+i+'" title="Play episode '+i+'"'):'')+'>'+i+'</div>'; }
  if(max>cells) html+='<div class="sm" style="grid-column:1/-1;color:var(--muted);padding:12px;text-align:center">Showing episodes 1–'+cells+' of '+max+'.</div>';
  grid.innerHTML = html || '<div class="sm" style="grid-column:1/-1;padding:24px">No episodes found.</div>';
  if(j.fresh){ try{ await fetch("/dl/library/seen",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})}); }catch(e){} loadLibrary(); }
}
function closeLibEp(){ $("#libEpModal").hidden=true; _libEpName=""; }
async function scanLib(){ const b=$("#scanLib"); b.disabled=true; await loadLibrary(); b.disabled=false; toast("Library scanned"); }
/* Library Update runs on the same engine as Download, with the download bar's Quality / Series / Episodes
   (dlSettings()). */
async function updateAll(){
  try{ const j=await (await fetch("/dl/library/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(dlSettings())})).json();
    if(j.ok) _jobAccepted();
    toast(j.ok?"Checking your whole library for new episodes…":(j.error||"Couldn't start"), !j.ok);
  }catch(e){ toast("Update failed: "+e, true); }
}

/* Live per-card progress during a Library update: the iOS clockwork poster reveal + state chip.
   Updates cards in place (no re-render) so the reveal animates smoothly across polls. */
function applyLiveToLibrary(status){
  const grid=$("#libGrid"); if(!grid) return;
  (status.series||[]).forEach(s=>{
    const sid=String(s.sid||""); if(!sid) return;
    const card=grid.querySelector('.libcard[data-sid="'+(window.CSS&&CSS.escape?CSS.escape(sid):sid)+'"]');
    if(!card) return;
    card.classList.add('act');
    const dim=card.querySelector('.dim');
    if(dim) dim.style.setProperty('--rev',(Math.max(0,Math.min(1,s.frac||0))*360).toFixed(1)+'deg');
    const st=s.state||s.status||'';
    ['st-queued','st-downloading','st-waiting','st-done','st-error','st-recheck','st-checked'].forEach(c=>card.classList.remove(c));
    if(st) card.classList.add('st-'+st);
    const total=Number(card.dataset.total)||s.total||0;
    const ds=card.querySelector('.dlstate');
    if(ds) ds.textContent = st==='downloading' ? (s.done+' / '+(total||'?'))
                          : st==='queued' ? 'Queued'
                          : st==='waiting' ? 'Retrying soon'   // failed episodes wait for their retry round
                          : st==='done' ? '✓ Updated'
                          : st==='recheck' ? 'Re-check'        // complete by the website's list only: re-read later
                          : st==='checked' ? 'Up to date'      // re-read from the signed list: nothing missing
                          : st==='error' ? 'Failed' : st;
    const epsEl=card.querySelector('.eps > span');
    if(epsEl && total) epsEl.textContent = s.done+'/'+total;
  });
}
async function openSeries(name){
  try{ const j=await (await fetch("/dl/library/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})})).json();
    if(!j.ok) toast(j.error||"Couldn't open the folder", true);
  }catch(e){ toast("Open failed: "+e, true); }
}
/* Play now opens the in-app player (resume + auto-play next). "Open in player ↗" inside it
   still hands off to the system player for anyone who prefers VLC etc. */
function playSeries(name){ openPlayer(name, null); }

/* ---- Library right-click context menu: one action layer for click / right-click / bulk ---- */
var _ctxNames=[];
function libCtxTarget(card){
  // right-clicking a selected card (in select mode) acts on the whole selection; else just this card
  if(libSelectMode && card && libSelected.has(card.dataset.name) && libSelected.size) return [...libSelected];
  return card ? [card.dataset.name] : [];
}
function openLibCtx(x,y,names){
  const m=$("#libCtx"); if(!m||!names.length) return; _ctxNames=names;
  let head=m.querySelector('.lcx-head');
  if(names.length>1){ if(!head){ head=document.createElement('div'); head.className='lcx-head'; m.prepend(head); } head.textContent=names.length+' selected'; head.hidden=false; }
  else if(head){ head.hidden=true; }
  const rw = (names.length===1 && typeof getResume==="function") ? getResume(names[0]) : null;
  const lbl=m.querySelector('[data-lcx="play"] .lcx-lbl'); if(lbl) lbl.textContent = rw ? ('Resume E'+rw.ep) : 'Play';
  const mh=m.querySelector('[data-lcx="mergeh264"]');          // only when this series has ≥2 converted episodes
  if(mh){ const it=(names.length===1)?(libItems||[]).find(x=>x.name===names[0]):null; mh.hidden = !(it && (it.h264||0) >= 2); }
  m.hidden=false;                                              // measure, then position with edge-flip
  const r=m.getBoundingClientRect(), vw=innerWidth, vh=innerHeight;
  let L=(x+r.width>vw-8)?x-r.width:x, T=(y+r.height>vh-8)?y-r.height:y;   // screen px, like the pointer
  L=Math.max(8,Math.min(L,vw-r.width-8)); T=Math.max(8,Math.min(T,vh-r.height-8));
  // Display size scales the page with CSS zoom, which also scales left/top: divide it back out, or at 125%
  // the menu opened a quarter further right/down than the pointer (partly off-screen).
  const z=parseFloat(document.documentElement.style.zoom)||1;
  m.style.left=(L/z)+'px';
  m.style.top =(T/z)+'px';
}
function closeLibCtx(){ const m=$("#libCtx"); if(m&&!m.hidden){ m.hidden=true; } _ctxNames=[]; }
/* name-list variants of the per-series actions (reused by the menu; single or many) */
function libPlayNames(names){ if(!names.length) return; if(libSelectMode) exitSelect(); openPlayer(names[0], null, names.slice(1)); }
async function updateNames(names){ if(!names.length) return;
  try{ const j=await (await fetch("/dl/library/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names,...dlSettings()})})).json();
    if(j.ok) _jobAccepted();
    toast(j.ok?("Checking "+names.length+" series for new episodes…"):(j.error||"Couldn't start update"), !j.ok);
  }catch(e){ toast("Update failed",true); } if(libSelectMode) exitSelect(); }
async function mergeSeriesNames(names){ if(!names.length) return; if(names.length===1) return mergeSeries(names[0]);
  if(libSelectMode) exitSelect(); let ok=0;
  for(let k=0;k<names.length;k++){ const r=await mergeOnce(names[k], "("+(k+1)+"/"+names.length+") "); if(r.ok) ok++; }
  showMerge("✓ Merged "+ok+" of "+names.length+" series", {autohide:9000}); loadLibrary(); }
async function libSeenNames(names){ if(!names.length) return;
  try{ await fetch("/dl/library/seen",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names})}); }catch(e){}
  await loadLibrary(); if(libSelectMode) exitSelect(); toast("Marked "+names.length+" as seen"); }
async function libDeleteNames(names){ if(!names.length) return;
  // one series: name it (plain text; line breaks + bidi overrides folded so a title can't forge or reorder the prompt)
  const one=names.length===1 ? ((libItems||[]).find(x=>x.name===names[0])||{}) : null;
  const fold=s=>String(s||"").replace(/[\u0000-\u001f\u007f-\u009f\u200e\u200f\u2028-\u202e\u2066-\u2069]+/g," ").trim().slice(0,120);
  const what=one ? "“"+(fold(one.title)||fold(names[0]))+"”" : names.length+" series";
  if(!(await ask("Move "+what+" to Trash?", "You can undo right after — nothing is permanently erased.", {ok:"Move to Trash", danger:true}))) return;
  let j; try{ j=await (await fetch("/dl/library/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names})})).json(); }
  catch(e){ toast("Delete failed",true); return; }
  const moved=(j&&j.moved)||[]; await loadLibrary(); if(libSelectMode) exitSelect();
  if(moved.length) showUndo(moved.length+" moved to Trash", moved.map(m=>m.token)); else toast("Nothing deleted",true); }
var _convNames=[];
function convertNames(names){ if(!names.length) return; if(libSelectMode) exitSelect();
  _convNames=names.slice();
  const sub=$("#convSub"); if(sub) sub.textContent = (names.length>1 ? (names.length+" series") : ("“"+names[0]+"”")) + " → editor-friendly H.264 (Premiere-ready)";
  let mode="auto"; try{ mode = localStorage.getItem("hg_convert_mode")||"auto"; }catch(e){}
  const mc=$("#convMode"); if(mc) mc.value=mode;
  let speed="quality"; try{ speed = localStorage.getItem("hg_convert_speed")||"quality"; }catch(e){}
  const sp=$("#convSpeed"); if(sp) sp.value=speed;
  let cpu="0"; try{ cpu = localStorage.getItem("hg_convert_cpu")||"0"; }catch(e){}
  const cp=$("#convCpu"); if(cp) cp.value=cpu;
  convCpuRowSync();
  $("#convModal").hidden=false;
}
function convCpuRowSync(){ const r=$("#convCpuRow"); if(r) r.style.display = ($("#convMode").value==="gpu") ? "none" : "flex"; }
function convThreads(){ const v=$("#convCpu").value; if(v==="half"){ const c=navigator.hardwareConcurrency||4; return Math.max(1,Math.floor(c/2)); } const n=parseInt(v,10); return isNaN(n)?0:n; }
async function startConvert(names, mode, speed, threads){
  let j; try{ j=await (await fetch("/dl/library/convert",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({names, mode:(mode||"auto"), speed:(speed||"quality"), threads:(threads||0)})})).json(); }
  catch(e){ toast("Convert failed to start",true); return; }
  if(!j.ok){ toast(j.error||"Couldn't start convert", true); return; }
  const cx=$("#libConvCancel"); if(cx){ cx.hidden=false; cx.onclick=cancelConvert; }
  showMerge("Converting to H.264 … 0%");
  let last="";
  const iv=setInterval(async()=>{
    let st; try{ st=await (await fetch("/dl/library/convert-status")).json(); }catch(e){ return; }
    if(st.running){
      if(last && last!==st.name) _mergeCardDone(last);
      last=st.name; _mergeCard(st.name, st.pct||0);
      const scope = st.total>1 ? (" ("+((st.series_done||0)+1)+"/"+st.total+")") : "";
      showMerge("Converting “"+(st.name||"")+"”"+scope+" … "+(st.pct||0)+"%"+(st.encoder?("  · "+st.encoder):""));
      return;
    }
    clearInterval(iv); if(last) _mergeCardDone(last); if(cx) cx.hidden=true;
    const cancelled = (st.error==="cancelled");
    const msg = cancelled
      ? ("Convert cancelled"+(st.converted?(" — "+st.converted+" done"):""))
      : (st.failed>0)
        ? ("Converted "+st.converted+", "+st.failed+" failed"+(st.error?(": "+st.error):""))
        : ("✓ Converted "+st.converted+" to H.264"+(st.skipped?(" · "+st.skipped+" already H.264"):""));
    showMerge(msg+(st.encoder&&!cancelled?("  · "+st.encoder):""), {autohide:cancelled?6000:10000});
    loadLibrary();
  }, 800);
}
function cancelConvert(){ try{ fetch("/dl/library/convert-cancel",{method:"POST"}); }catch(e){}
  const cx=$("#libConvCancel"); if(cx) cx.hidden=true; showMerge("Cancelling…"); }
function libCtxDo(act){
  const names=_ctxNames.slice(); closeLibCtx(); if(!names.length) return;
  ({ play:libPlayNames, merge:mergeSeriesNames, update:updateNames, convert:convertNames,
     mergeh264:mergeH264Names, open:(ns)=>ns.forEach(openSeries), seen:libSeenNames, delete:libDeleteNames }[act]||(()=>{}))(names);
}

/* ---------- Library: new seasons ----------
   Update all's second step finds other seasons of the series it checked; its result comes with /dl/status in library
   mode (`seasons`) and stays on screen after the job. Newer seasons download on their own (their progress is shown
   here) -- except a drama whose new seasons add up to 1,500+ episodes or ~20+ GB, or one with a season that couldn't
   be checked: it waits in a card of its own (per-season Add, "Download all", "Not now"; `why` says which). Older,
   removed, held and skipped seasons and same-story series are suggestions with Add;
   announced ones are "coming soon". Add and "Download all" send series ids to /dl/submit -- the Download button's own
   route (licence gate included); "Not now" sends them to /dl/library/seasons/decline (remembered, nothing downloaded).
   Every server string goes through esc(); the buttons carry only a checked id. */
let _lsn=null, _lsnRun=null, _lsnHide=false, _lsnMore=false, _lsnAdded={}, _lsnDeclined={}, _lsnLoad=null, _lsnRows={};
const LSN_SUG_SHOW=12;                        // suggestions shown before "+N more"
const LSN_ID=/^[0-9]{15,20}$/;
function lsnTake(st){                         // poll(): keep the latest Update's result
  if(!st || st.mode!=="library") return;
  if(st.started!==_lsnRun){ _lsnRun=st.started; _lsn=null; _lsnHide=false; _lsnMore=false; _lsnAdded={}; _lsnDeclined={}; _lsnRows={}; }
  (st.series||[]).forEach(r=>{ if(r && LSN_ID.test(String(r.sid))) _lsnRows[String(r.sid)]=r; });   // last known progress
  if(st.seasons && typeof st.seasons==="object"){
    _lsn=st.seasons;
    // newer seasons started: refresh the Library once, so their new cards appear (and reveal) while they download
    if(st.running && lsnList("auto").length && _lsnLoad!==st.started){ _lsnLoad=st.started; setTimeout(loadLibrary,1500); }
  }
}
function lsnItems(v){ return Array.isArray(v) ? v.filter(x=>x && typeof x==="object" && LSN_ID.test(String(x.sid))) : []; }
function lsnList(k){ return lsnItems(_lsn && _lsn[k]); }
function lsnN(n, word){ n=num(n); return n.toLocaleString("en-US")+" "+word+(n===1 ? "" : "s"); }   // 1 season / 1,543 episodes
function lsnEps(n){ n=num(n); return n.toLocaleString("en-US")+(n===1 ? " ep" : " eps"); }
function lsnName(x){ const s=num(x.season); return (x.short===true && s>0) ? "S"+s : String(x.title||x.sid); }
function lsnMeta(x, note){ return lsnEps(x.eps)+(x.score ? " · ★"+x.score : "")+(note ? " · "+note : ""); }
function lsnBigAll(){                         // every season of the dramas waiting for an OK, as the server listed them
  const b=_lsn && _lsn.big;
  return (b && Array.isArray(b.albums)) ? [].concat(...b.albums.map(g=>lsnItems(g && g.items))) : lsnItems(b && b.items);
}
function lsnBigAlbums(){                      // those dramas: [{album, base, items}], minus what "Not now" moved away here
  const b=_lsn && _lsn.big, out=[];
  ((b && Array.isArray(b.albums)) ? b.albums : []).forEach(g=>{
    if(!g || typeof g!=="object") return;
    const items=lsnItems(g.items).filter(x=>!_lsnDeclined[x.sid]);
    if(items.length) out.push({album:String(g.album||""), base:String(g.base||""), items, kept:g.why==="offered",
                               why:String(g.why||""), gb:num(g.gb)});
  });
  return out;
}
function lsnGroups(items, pill){               // one group per album title, in the server's order
  const gs=[], at=new Map();
  items.forEach(x=>{ const b=String(x.base||""); if(!at.has(b)){ at.set(b, gs.length); gs.push({b, h:[]}); } gs[at.get(b)].h.push(pill(x)); });
  return gs.map(g=>'<span class="lsn-grp">'+(g.b ? '<span class="lsn-gt" title="'+esc(g.b)+'">'+esc(g.b)+'</span>' : '')+g.h.join("")+'</span>').join("");
}
function lsnBusy(){ return lastStatus.running ? ' disabled title="Available when the current job finishes"' : ''; }
function lsnDockNote(j){                       // the dock's end line: seasons still waiting for their OK
  const b=(j && j.mode==="library" && j.seasons && j.seasons.big) ? j.seasons.big : null;
  const n=lsnItems(b && b.items).filter(x=>!_lsnAdded[x.sid] && !_lsnDeclined[x.sid]).length;
  return n ? " · "+lsnN(n,"new season")+(n===1 ? " waits" : " wait")+" for your OK" : "";
}
function lsnSugPill(x, meta, tag){             // a suggestion: [tag] name · meta [+ Add]
  const add=_lsnAdded[x.sid] ? '<span class="lsn-done">✓ Added</span>'
    : '<button class="lsn-add" data-lsn="add" data-sid="'+esc(x.sid)+'"'+lsnBusy()+' aria-label="Add '+esc(x.title)+'">+ Add</button>';
  return '<span class="lsn-pill'+(tag ? ' rel' : '')+'">'+(tag ? '<span class="lsn-tag">'+esc(tag)+'</span>' : '')
       + '<span class="lsn-t" title="'+esc(x.title)+'">'+esc(tag ? String(x.title||x.sid) : lsnName(x))+'</span>'
       + '<span class="lsn-m">'+esc(meta)+'</span>'+add+'</span>';
}
function lsnPlain(x, meta, cls){
  return '<span class="lsn-pill plain'+(cls?' '+cls:'')+'"><span class="lsn-t" title="'+esc(x.title)+'">'+esc(lsnName(x))+'</span>'
       + (meta ? '<span class="lsn-m">'+esc(meta)+'</span>' : '')+'</span>';
}
function lsnAutoPill(x, rows){                 // live progress from the job's own rows (library mode)
  const r=rows[String(x.sid)];
  if(!r) return lsnPlain(x, lsnEps(x.eps), "");
  const t=num(r.total), d=num(r.done), st=r.state||r.status||"";
  if(st==="done" || (t>0 && d>=t)) return lsnPlain(x, "✓ "+lsnEps(t||d), "ok");
  if(st==="cancelled") return lsnPlain(x, "stopped · "+d+"/"+t, "");
  return lsnPlain(x, st==="queued" ? "queued · "+lsnEps(t) : d+"/"+lsnEps(t), "dl");
}
function lsnRender(){
  const el=$("#libSeasons"); if(!el) return;
  const auto=lsnList("auto"), locked=lsnList("locked"), soon=lsnList("soon"), bigs=lsnBigAlbums();
  const stoppedAll=lsnList("stopped");        // found / queued, but Stop came before they started: they start with the next Update all (or + Add now)
  const stopped=stoppedAll.filter(x=>!_lsnAdded[x.sid]), addedNow=stoppedAll.filter(x=>_lsnAdded[x.sid]);   // + Added: in the Added row
  const related=lsnList("related"), seen=new Set(), sug=[];
  [[lsnList("older"),"older season"], [lsnList("removed"),"removed earlier"], [lsnList("held"),"new season"],
   [lsnList("declined"),"skipped"], [lsnBigAll().filter(x=>_lsnDeclined[x.sid]),"skipped"], [lsnList("failed"),"couldn't start"],
   [related,""]].forEach(([xs,note])=>xs.forEach(x=>{ const k=String(x.sid); if(!seen.has(k)){ seen.add(k); sug.push([x,note]); } }));
  if(!_lsn || _lsnHide || !(auto.length||stoppedAll.length||locked.length||soon.length||bigs.length||sug.length)){ el.hidden=true; return; }
  const rows=_lsnRows;                        // the Update's own rows (kept after it: a later job's mode has none)
  const live=!!(lastStatus.running && lastStatus.mode==="library"), rel=new Set(related);
  const nBig=bigs.reduce((a,g)=>a+g.items.length,0), waiting=bigs.reduce((a,g)=>a+g.items.filter(x=>!_lsnAdded[x.sid]).length,0);
  const nAuto=auto.length+addedNow.length;
  const say=[nAuto ? nAuto+(live ? " downloading" : " added") : "",
             stopped.length ? stopped.length+" not started" : "",
             waiting ? waiting+" waiting for your OK" : (nBig ? nBig+" started" : ""),
             locked.length ? locked.length+(locked.length===1 ? " needs a license" : " need a license") : "",
             sug.length ? sug.length+" suggested" : "", soon.length ? soon.length+" coming soon" : ""].filter(Boolean).join(" · ");
  let h='<div class="lsn-head"><span class="lsn-title">🆕 New seasons</span><span class="lsn-sub">'+esc(say)+'</span>'
       +'<button class="x" data-lsn="close" title="Hide" aria-label="Hide new seasons">✕</button></div>';
  bigs.forEach(g=>{                           // a drama with 1,500+ new episodes / ~20+ GB / a season it couldn't check: its own card, nothing starts without you
    const rest=g.items.filter(x=>!_lsnAdded[x.sid]), eps=rest.reduce((a,x)=>a+num(x.eps),0), all=g.items.reduce((a,x)=>a+num(x.eps),0);
    const alb=LSN_ID.test(g.album) ? g.album : "";
    const why=g.kept ? ': still waiting for your OK.'                          // kept = offered on an earlier Update
      : g.why==="partial" ? ': some seasons could not be checked, so nothing starts on its own.'
      : g.why==="size" ? ': about '+g.gb.toLocaleString("en-US",{maximumFractionDigits:1})+' GB, too large to start on their own.'
      : ': too many to start on their own.';
    h+='<div class="lsn-big"><div class="lsn-bhead"><div class="lsn-bt"><b>'+esc(g.base||String(g.items[0].title||""))+'</b> · '
      +lsnN(g.items.length,"new season")+' · '+lsnN(all,"episode")+esc(why)+'</div>'
      +(!rest.length ? '<span class="lsn-done">✓ Started</span>' : !alb ? '' :
        '<div class="lsn-bact"><button class="btn ghost sm" data-lsn="decline" data-alb="'+alb+'">Not now</button>'
        +'<button class="btn primary sm" data-lsn="big" data-alb="'+alb+'"'+lsnBusy()+'>'
        +(rest.length<g.items.length ? 'Download the rest' : 'Download all')+' ('+lsnN(eps,"episode")+')</button></div>')
      +'</div><div class="lsn-items">'+g.items.map(x=>lsnSugPill(x, lsnMeta(x,""))).join("")+'</div></div>';
  });
  if(nAuto) h+='<div class="lsn-row"><span class="lsn-k">'+(live ? "Downloading" : "Added")+'</span><div class="lsn-items">'
      +lsnGroups(auto.concat(addedNow), x=>addedNow.includes(x) ? lsnPlain(x, "✓ Added · "+lsnEps(x.eps), "") : lsnAutoPill(x, rows))+'</div></div>';
  if(stopped.length) h+='<div class="lsn-row"><span class="lsn-k">Not started</span><div class="lsn-items">'
      +lsnGroups(stopped, x=>lsnSugPill(x, lsnEps(x.eps)+" · starts with the next Update all"))+'</div></div>';
  if(locked.length) h+='<div class="lsn-row"><span class="lsn-k">Needs license</span><div class="lsn-items">'
      +lsnGroups(locked, x=>lsnPlain(x, lsnEps(x.eps), ""))+'<button class="btn ghost sm" data-lsn="lic">Get a license</button></div></div>';
  if(sug.length){
    const show=_lsnMore ? sug : sug.slice(0, LSN_SUG_SHOW), note=new Map(sug);
    h+='<div class="lsn-row"><span class="lsn-k">Suggestions</span><div class="lsn-items">'
      +lsnGroups(show.map(p=>p[0]), x=>rel.has(x) ? lsnSugPill(x, lsnMeta(x,""), "Same story") : lsnSugPill(x, lsnMeta(x, note.get(x))))
      +(sug.length>LSN_SUG_SHOW ? '<button class="lsn-more" data-lsn="more">'+(_lsnMore ? "Show fewer" : "+"+(sug.length-LSN_SUG_SHOW)+" more")+'</button>' : '')
      +'</div></div>';
  }
  if(soon.length) h+='<div class="lsn-row"><span class="lsn-k">Coming soon</span><div class="lsn-items">'+lsnGroups(soon, x=>lsnPlain(x, "", "soon"))+'</div></div>';
  el.hidden=false;
  _html(el, h);
}
function lsnScores(ids){                       // the lists' ★ of these ids, sent like the Download button's click scores
  const m={}, want=new Set(ids);
  ["auto","stopped","locked","older","removed","held","declined","failed","related","soon"].map(lsnList).concat([lsnBigAll()])
    .forEach(xs=>xs.forEach(x=>{ const s=String(x.score||""); if(want.has(String(x.sid)) && /^[0-9]{1,2}(\.[0-9]{1,2})?$/.test(s)) m[String(x.sid)]=s; }));
  return m;
}
async function lsnSubmit(ids, btn){            // Add / "Download all": the Download button's route
  if(lastStatus.running){ toast("Wait for the current job to finish", true); return; }
  if(btn) btn.disabled=true;
  let j; try{ j=await (await fetch("/dl/submit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({series_ids:ids, scores:lsnScores(ids), ...dlSettings()})})).json(); }
  catch(e){ j={ok:false, error:"Couldn't start: "+e}; }
  if(j && j.ok){
    const held=new Set((Array.isArray(j.blocked)?j.blocked:[]).map(String));
    ids.forEach(id=>{ if(!held.has(id)) _lsnAdded[id]=1; });
    _jobAccepted();
    if(j.need_license) promptActivate(j);
    else toast(ids.length>1 ? "Downloading "+lsnN(ids.length,"new season") : "Added: downloading now");
    refreshAccount(); setTimeout(loadLibrary,1200); setTimeout(loadLibrary,3500);
  } else if(j && j.reason==="free_limit") promptActivate(j);
  else toast((j && j.error) || "Couldn't start", true);
  lsnRender();
}
async function lsnDecline(alb, btn){           // "Not now": remembered for this library folder, nothing downloads
  const g=lsnBigAlbums().find(x=>x.album===alb);
  const ids=g ? g.items.filter(x=>!_lsnAdded[x.sid]).map(x=>String(x.sid)) : [];
  if(!ids.length) return;
  if(btn) btn.disabled=true;
  let j; try{ j=await (await fetch("/dl/library/seasons/decline",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({series_ids:ids})})).json(); }
  catch(e){ j={ok:false, error:"Couldn't save: "+e}; }
  if(j && j.ok){ ids.forEach(id=>{ _lsnDeclined[id]=1; }); toast("Not now: "+(ids.length===1 ? "it stays" : "they stay")+" under Suggestions"); }
  else{ toast((j && j.error) || "Couldn't save", true); if(btn) btn.disabled=false; }
  lsnRender();
}
function lsnClick(e){
  const b=e.target.closest("[data-lsn]"); if(!b || b.disabled) return;
  const act=b.dataset.lsn;
  if(act==="close"){ _lsnHide=true; lsnRender(); }
  else if(act==="more"){ _lsnMore=!_lsnMore; lsnRender(); }
  else if(act==="lic"){ refreshAccount().then(openAccount); }
  else if(act==="add"){ const sid=String(b.dataset.sid||""); if(LSN_ID.test(sid)) lsnSubmit([sid], b); }
  else if(act==="big"){ const g=lsnBigAlbums().find(x=>x.album===String(b.dataset.alb||""));
    const ids=g ? g.items.filter(x=>!_lsnAdded[x.sid]).map(x=>String(x.sid)) : []; if(ids.length) lsnSubmit(ids, b); }
  else if(act==="decline"){ const alb=String(b.dataset.alb||""); if(LSN_ID.test(alb)) lsnDecline(alb, b); }
}

/* ---------- poll ---------- */
let _wasRunning=false;
let _dlTick=0;
let _runGen=0;          // bumped by start(): Download pressed, and again once /dl/submit accepted the run
async function poll(){
  const gen=_runGen;
  try{
    const st = DEMO ? demoStatus() : await (await fetch("/dl/status")).json();
    if(gen!==_runGen) return;                    // asked before a new run was submitted: its "idle" isn't that run's end
    const ended = _wasRunning && !st.running;
    if(ended) dockEnded(st);                     // before the render below: the dock goes straight to the final numbers
    if(st.started!==_hwStarted){ _hwStarted=st.started; _hwReset(); }   // another run: its bars start from 0
    lastStatus = st;
    srcRender(st.source, st.paused===true && num(st.active)===0);   // the backup-source pill (the signed API is down)
    lsnTake(st);                                 // an Update's new-season result (kept after the job)
    renderQueue();
    // Immediate Library: while a queue download runs, refresh the Library so series pop up as their
    // folders/episodes land on disk (throttled so we don't rescan on every poll).
    if(lastStatus.running && lastStatus.mode==="download"){ if(++_dlTick % 4 === 0) loadLibrary(); } else { _dlTick=0; }
    // Library update: live poster clock-reveal + scan notice board (re-drawn only when its text changes, so the
    // pulsing dot isn't restarted on every poll)
    const libScan=$("#libScan");
    if(lastStatus.mode==="library" && lastStatus.running){
      applyLiveToLibrary(lastStatus);
      if(libScan){ libScan.hidden=false;
        const chk='<b>'+num(lastStatus.checked)+'/'+num(lastStatus.to_check)+'</b>', fnd='<b>'+num(lastStatus.found)+'</b>';
        const ss=lastStatus.seasons, na=(ss && Array.isArray(ss.auto)) ? ss.auto.length : 0;
        const sx=(ss && ss.state==="checking") ? ' · looking for new seasons…' : (na>0 ? ' · <b>'+na+'</b> new season'+(na>1?'s':'') : '');
        _html(libScan, lastStatus.phase==="downloading"
          ? '<span class="lsdot"></span>Library checked '+chk+' · '+fnd+' with new episodes'+(num(lastStatus.found)>0 ? ' · downloading them' : '')+sx
          : '<span class="lsdot"></span>Checking library…'+(num(lastStatus.to_check)>0 ? ' '+chk+' checked · '+fnd+' with new episodes' : '')); }
    } else if(libScan){ libScan.hidden=true; }
    lsnRender();
    const log=(lastStatus.log||[]);
    $("#log").textContent = log.join("\n")||"—"; $("#log").scrollTop=$("#log").scrollHeight;
    $("#logHint").textContent = lastStatus.running ? "running" : (log.length?log.length+" lines":"");
    $("#cancelBtn").disabled=!lastStatus.running;
    const running=!!lastStatus.running;                        // background-activity animation
    $("#bgWork").classList.toggle("on", running);
    $("#bgBar").hidden = !running;
    if(ended){                                                // a download/update just finished ->
      if(lastStatus.mode==="library"){                         //   an update: the posters first finish their reveal
        applyLiveToLibrary(lastStatus); setTimeout(loadLibrary, 1200);   // (the final numbers), then the library
      } else loadLibrary();                                    //   is refreshed; a download: refresh the library now,
      refreshAccount();                                        //   the Free n/2 / licence chip (it stayed stale),
      if(lastStatus.mode==="download") clearFinishedFromQueue(); // and drop finished series from the queue
    }
    _wasRunning = !!lastStatus.running;
  }catch(e){ if(!DEMO && ALLOW_DEMO){ DEMO=true; seedDemo(); } }   // localhost: keep retrying the real backend
}

/* ---------- events ---------- */
document.addEventListener("click", e=>{
  if(libSelectMode){ const lc=e.target.closest("#libGrid .libcard"); if(lc){ toggleLibSel(lc.dataset.name, lc); return; } }
  const pv=e.target.closest(".prev"); if(pv){ const pp=pv.closest(".poster"); if(pp&&pp.dataset.id) openPreview(pp); return; }   // ▶ centre = preview (not add-to-cart)
  const p=e.target.closest(".poster"); const rm=e.target.closest("[data-rm]"); const ep=e.target.closest("[data-ep]");
  if(ep){ openEpModal(ep.dataset.ep); return; }
  if(p && p.classList.contains("libcard")){ openLibEpisodes(p.dataset.name); return; }   // click cover -> series detail
  if(p && !p.classList.contains("libcard")){ const id=p.dataset.id; if(cart[id]) removeFromCart(id); else addToCart(id,p.dataset.t,Number(p.dataset.n),p.dataset.cov,false,p.dataset.sc); }
  if(rm){ removeFromCart(rm.dataset.rm); }
});

/* One-click preview: play a series' free episodes (Ep 1-3) in-app, straight from hongguoduanju's OWN web
   player (its public MP4s, resolved by /dl/preview). No download / signer / decrypt -- every card already
   carries the hongguoduanju series_id. The <video> lives in a tiny srcdoc frame that sends no Referer:
   the site's video CDN refuses requests that carry this app's address. The frame is sandboxed with no
   scripts (allow-same-origin only, so this page can still drive the video + hear ended/error). */
const _pv={card:null, id:"", ep:1, free:3, total:0, seq:0, retried:false, wd:0, noting:false};
const PV_STALL_MS=10000;                 // no data at the start / no progress while playing this long = stuck (a CDN reset)
function _pvVideo(){ try{ return $("#pvFrame").contentDocument.querySelector("video"); }catch(e){ return null; } }
function _pvMsg(html){ const m=$("#pvMsg"); if(html==null){ m.hidden=true; m.innerHTML=""; } else { m.innerHTML=html; m.hidden=false; } }
function _pvStop(){ const f=$("#pvFrame"), v=_pvVideo(); f.onload=null; clearInterval(_pv.wd); _pv.wd=0;
  if(v){ try{ v.pause(); v.removeAttribute("src"); v.load(); }catch(e){} }
  f.srcdoc=""; }
// A reset / stalled CDN connection leaves a black frame and no error: when the video has no data ~10 s after it was
// mounted, or stops moving for ~10 s while it plays, say "Still loading…" and resolve the episode once more (a fresh
// play url); still stuck after that -> Try again. A pause by the user is never "stuck". (And an autoplay that never
// started -- data there, still at 0 and paused ~2 s later -- is asked to play once more.)
function _pvWatch(seq){
  clearInterval(_pv.wd);
  let last=-1, moved=Date.now(), data=0, kicked=false, played=false;
  _pv.wd=setInterval(()=>{
    if(seq!==_pv.seq || $("#pvPlayer").hidden){ clearInterval(_pv.wd); return; }
    const v=_pvVideo(); if(!v) return;
    const now=Date.now(), t=+v.currentTime||0, wants=v.readyState<2 || (!v.paused && !v.ended);
    if(_pv.noting && v.readyState>=2){ _pv.noting=false; _pvMsg(null); }   // the re-resolved episode has data: note off
    if(v.readyState>=2 && !data) data=now;
    if(t>0) played=true;
    if(!kicked && !played && data && now-data>=2000 && v.paused && !v.ended){   // never started (not a pause of yours)
      kicked=true; v.play().catch(()=>{ v.muted=true; v.play().catch(()=>{}); });
    }
    if(!wants || t!==last){ last=t; moved=now; return; }
    if(now-moved<PV_STALL_MS) return;
    clearInterval(_pv.wd); _pv.wd=0;
    if(!_pv.retried){ _pv.retried=true; pvLoad(_pv.ep, true, "Still loading…", played ? t : 0); }   // (it goes on where it stopped)
    else _pvMsg(`Episode ${esc(_pv.ep)} isn't loading right now.<button class="btn sm ghost" data-pvretry>Try again</button>`);
  }, 1000);
}
function _pvAddLabel(){ return cart[_pv.id] ? "✓ In downloads" : "⬇ Add to downloads"; }
function _pvAddBtn(){ const b=$("#pvAdd"), on=!!cart[_pv.id]; b.textContent=_pvAddLabel();
  b.title=on?"Click to remove it from downloads":"Queue the whole series for download";
  b.classList.toggle("primary",!on); b.classList.toggle("ghost",on);
  const e=document.querySelector("#pvMsg [data-pvadd]"); if(e) e.textContent=_pvAddLabel(); }
function _pvTabs(){ let h="";
  for(let i=1;i<=_pv.free;i++) h+=`<button class="epchip" role="tab" data-pvep="${i}" aria-pressed="${i===_pv.ep}" aria-selected="${i===_pv.ep}">Ep ${i}</button>`;
  $("#pvTabs").innerHTML=h+`<span class="pvfree">${_pv.total?`${_pv.free} free of ${_pv.total}`:"free preview"}</span>`; }
function _pvShape(w,h){ w=+w||720; h=+h||1280; const st=$("#pvStage");
  st.style.setProperty("--pv-ar", w+"/"+h); st.style.setProperty("--pv-arn", (w/h).toFixed(4));
  $("#pvPlayer .pvcard").classList.toggle("land", w>h); }   // animated series are 16:9, live-action 9:16
function _pvMount(j, at){ const f=$("#pvFrame"), seq=_pv.seq;
  f.onload=()=>{ const v=_pvVideo(); if(!v || seq!==_pv.seq) return;
    if(at>0){ const go=()=>{ try{ if(seq===_pv.seq && at<(+v.duration||0)) v.currentTime=at; }catch(e){} };   // a stall mid-episode:
      if(v.readyState>=1) go(); else v.addEventListener("loadedmetadata", go, {once:true}); }        //   back where it was
    v.addEventListener("error",()=>{ if(seq!==_pv.seq) return;
      if(!_pv.retried){ _pv.retried=true; pvLoad(_pv.ep,true); }          // play url expired -> re-resolve once
      else _pvMsg(`Couldn't play episode ${_pv.ep} right now.<button class="btn sm ghost" data-pvretry>Try again</button>`); });
    v.addEventListener("ended",()=>{ if(seq!==_pv.seq) return;
      if(_pv.ep<_pv.free) pvLoad(_pv.ep+1);                               // roll into the next free episode
      else _pvMsg(`That's the free preview${_pv.total?` · ${_pv.total} episodes in all`:""}.<button class="btn sm primary" data-pvadd>${_pvAddLabel()}</button>`); });
    try{ f.contentWindow.addEventListener("keydown",_pvKey,true); }catch(e){}
    v.play().catch(()=>{ v.muted=true; v.play().catch(()=>{}); });          // autoplay blocked -> start muted
  };
  f.srcdoc='<!doctype html><meta name="referrer" content="no-referrer">'
    +'<style>html,body{margin:0;height:100%;background:#000}video{width:100%;height:100%;display:block;background:#000;object-fit:contain}</style>'
    +'<video src="'+esc(j.url)+'"'+(j.poster?' poster="'+esc(j.poster)+'"':'')+' controls playsinline preload="auto"></video>';
  _pvWatch(seq);
}
async function pvLoad(ep, fresh, note, at){
  _pv.ep=ep; const seq=++_pv.seq; if(!fresh) _pv.retried=false;
  _pv.noting=!!note;                                                        // the watchdog's "Still loading…" stays
  _pvTabs(); _pvStop(); _pvMsg('<div class="spin"></div>'+esc(note || ('Loading episode '+ep+'…')));   // until data comes
  $("#pvSub").textContent=`Episode ${ep}${_pv.total?` of ${_pv.total}`:""} · free preview`;
  let j=null;
  try{ j=await (await fetch(`/dl/preview?series_id=${encodeURIComponent(_pv.id)}&ep=${ep}${fresh?"&fresh=1":""}`,{cache:"no-store"})).json(); }catch(e){}
  if(seq!==_pv.seq || $("#pvPlayer").hidden) return;                      // superseded by another tab / closed
  if(!j || !j.ok){
    const err=j&&j.error;
    if(err==="unavailable") _pvMsg("This series has no free preview on hongguoduanju.");
    else if(err==="locked") _pvMsg(`Episode ${ep} isn't part of the free preview.`);
    else _pvMsg('Couldn\'t load the preview. Check your connection and try again.<button class="btn sm ghost" data-pvretry>Try again</button>');
    return;
  }
  _pv.free=Math.max(1,Math.min(3,num(j.free)||1)); _pv.total=num(j.episode_cnt)||_pv.total;   // both reach the tabs' innerHTML
  if(j.title) $("#pvTitle").textContent=j.title;
  $("#pvSub").textContent=`Episode ${ep}${_pv.total?` of ${_pv.total}`:""} · free preview`;
  _pvTabs(); _pvShape(j.width,j.height); _pvMsg(_pv.noting ? '<div class="spin"></div>'+esc(note) : null); _pvMount(j, +at||0);
}
function openPreview(card){
  if(!card || !card.dataset.id) return;
  _pv.card=card; _pv.id=card.dataset.id; _pv.free=3; _pv.total=+card.dataset.n||0;
  $("#pvTitle").textContent=card.dataset.t||"Preview"; _pvAddBtn(); _pvShape(720,1280);
  $("#pvPlayer").hidden=false; pvLoad(1);
  setTimeout(()=>{ try{ $("#pvClose").focus(); }catch(e){} },0);
}
function closePreview(){ if($("#pvPlayer").hidden) return; _pv.seq++; _pvStop(); _pvMsg(null); $("#pvPlayer").hidden=true;
  try{ if(_pv.card && _pv.card.isConnected) _pv.card.focus({preventScroll:true}); }catch(e){} }
function pvToggleCart(){ const c=_pv.card; if(!c) return; const id=_pv.id;
  if(cart[id]) removeFromCart(id); else addToCart(id,c.dataset.t,Number(c.dataset.n),c.dataset.cov,false,c.dataset.sc);
  _pvAddBtn(); }
function _pvKey(e){ if($("#pvPlayer").hidden || e.key!=="Escape") return; e.preventDefault(); e.stopPropagation(); closePreview(); }
(function initPreview(){
  $("#pvClose").onclick=closePreview; $("#pvAdd").onclick=pvToggleCart;
  $("#pvPlayer").addEventListener("click",e=>{
    if(e.target===e.currentTarget){ if(backdropClick(e)) closePreview(); return; }   // click outside the card closes
    const t=e.target.closest("[data-pvep]"); if(t){ const n=+t.dataset.pvep; if(n!==_pv.ep || !_pvVideo()) pvLoad(n); return; }
    if(e.target.closest("[data-pvretry]")){ pvLoad(_pv.ep,true); return; }
    if(e.target.closest("[data-pvadd]")) pvToggleCart();
  });
  document.addEventListener("keydown",_pvKey,true);
})();

/* right-click a library cover -> Windows-style actions menu (single card or whole selection) */
document.addEventListener("contextmenu", e=>{
  const card=e.target.closest("#libGrid .libcard"); if(!card) return;   // native menu everywhere else
  e.preventDefault();
  const names=libCtxTarget(card); if(!names.length) return;
  openLibCtx(e.clientX, e.clientY, names);
});
document.addEventListener("click", e=>{ if(!e.target.closest("#libCtx")) closeLibCtx(); }, true);
document.addEventListener("keydown", e=>{ if(e.key==="Escape") closeLibCtx(); });
// The Diagnostics console (Ctrl+Shift+D) sits above every dialog and player, so Esc closes it FIRST and
// nothing else: a window capture listener runs before all the document-level Esc handlers below/above.
window.addEventListener("keydown", e=>{
  if(e.key!=="Escape" || $("#diagModal").hidden) return;
  e.preventDefault(); e.stopPropagation(); $("#diagModal").hidden=true;
}, true);
// Esc closes the top-most open dialog by pressing its own ✕ (wired to the same function as its
// Cancel / Close / Later), so each dialog's cleanup still runs. The preview and the library player
// handle Esc themselves (capture phase), which is why they're skipped and defaultPrevented is honoured.
document.addEventListener("keydown", e=>{
  if(e.key!=="Escape" || e.defaultPrevented) return;
  const open=[...document.querySelectorAll(".modal:not([hidden])")].filter(m=>m.id!=="pvPlayer" && m.id!=="libPlayer");
  if(!open.length) return;
  const z=m=>parseInt(getComputedStyle(m).zIndex,10)||0;
  const top=open.reduce((a,b)=> z(b)>=z(a) ? b : a);
  const x=top.querySelector(".modal-head .x");
  if(x){ e.preventDefault(); x.click(); }
});
window.addEventListener("scroll", closeLibCtx, true);
window.addEventListener("resize", closeLibCtx);
$("#libCtx").addEventListener("click", e=>{ const b=e.target.closest("[data-lcx]"); if(b) libCtxDo(b.dataset.lcx); });
/* convert-to-H.264 options modal */
$("#convX").onclick=$("#convCancel").onclick=()=>{ $("#convModal").hidden=true; };
$("#convModal").addEventListener("click", e=>{ if(backdropClick(e)) $("#convModal").hidden=true; });
$("#convMode").onchange=convCpuRowSync;
$("#convGo").onclick=()=>{ const mode=$("#convMode").value||"auto";
  const speed=$("#convSpeed").value||"quality"; const cpu=$("#convCpu").value||"0"; const threads=convThreads();
  try{ localStorage.setItem("hg_convert_mode", mode);
       localStorage.setItem("hg_convert_speed", speed); localStorage.setItem("hg_convert_cpu", cpu); }catch(e){}
  $("#convModal").hidden=true; startConvert(_convNames, mode, speed, threads); };

/* #2 diagnostics / troubleshoot console (Ctrl+Shift+D) */
async function openDiag(){
  const m=$("#diagModal"), body=$("#diagBody"); m.hidden=false; body.textContent="Loading…";
  try{
    const d=await (await fetch("/dl/diag")).json();
    const lines=[
      "Hongguo Downloader — diagnostics", "time: "+new Date().toISOString(),
      "server pid: "+d.pid+"   web port: "+d.web_port+" ("+(d.bind_host||"?")+")   python: "+d.python,
      "signer: "+(d.sign_server||"?")+"   healthy: "+(d.signer_healthy?"YES":"NO"),
      "output dir: "+d.output_dir,
      "output writable: "+(d.output_writable?"YES":"NO — "+(d.output_write_error||"read-only?")),
      "state dir: "+d.state_dir, "data dir: "+d.data_dir,
      "download running: "+(d.running?("yes ("+(d.mode||"")+")"):"no"),
      "", "── launch / app.log ──", ...((d.app_log)||[]),
      "", "── download log ──", ...((d.dl_log)||[]),
    ];
    body.textContent=lines.join("\n");
  }catch(e){ body.textContent="Couldn't load diagnostics: "+e; }
}
$("#diagClose").onclick=()=>{ $("#diagModal").hidden=true; };
$("#diagModal").addEventListener("click", e=>{ if(backdropClick(e)) $("#diagModal").hidden=true; });
$("#diagRefresh").onclick=openDiag;
// writeText is async: a refused write rejects the promise (it doesn't throw), so wait for it before saying "copied"
$("#diagCopy").onclick=async()=>{ try{ await navigator.clipboard.writeText($("#diagBody").textContent); toast("Diagnostics copied"); }catch(e){ toast("Copy failed",true); } };
document.addEventListener("keydown",e=>{ if((e.ctrlKey||e.metaKey)&&e.shiftKey&&(e.key==="D"||e.key==="d")){ e.preventDefault(); openDiag(); } });
$("#startBtn").onclick=start; $("#cancelBtn").onclick=cancel;
$("#openDir").onclick=openDir; $("#setFolderToggle").onclick=pickDir;
$("#scanLib").onclick=scanLib; $("#updateLib").onclick=updateAll;
$("#libSeasons").addEventListener("click", lsnClick);   // Add / Download all / Not now / license / hide (data-lsn, no inline handlers)
$("#selectLib").onclick=toggleSelectMode;
$("#libSelectAll").onclick=libSelectAll; $("#libSelectNone").onclick=libSelectClear;
$("#libBulkSeen").onclick=libBulkSeen; $("#libBulkDelete").onclick=libBulkDelete;
$("#libBulkPlay").onclick=libBulkPlay; $("#libBulkConvert").onclick=libBulkConvert; $("#libBulkMerge").onclick=libBulkMerge; $("#libBulkUpdate").onclick=libBulkUpdate;
$("#libSort").onchange=e=>sortLib(e.target.value);
$("#libEpClose").onclick=$("#libEpCloseB").onclick=closeLibEp;
$("#libEpModal").addEventListener('click',e=>{ if(backdropClick(e)) closeLibEp(); });
/* click a downloaded episode number -> play it in the in-app player */
$("#libEpGrid").addEventListener('click',e=>{ const c=e.target.closest('[data-i]'); if(!c||!_libEpName) return;
  const name=_libEpName; closeLibEp(); openPlayer(name, parseInt(c.dataset.i,10)); });
/* series-detail action row -> same one action layer as the right-click menu */
function sdActionClick(e){
  const b=e.target.closest('[data-sd]'); if(!b||!_libEpName) return;
  const act=b.dataset.sd, name=_libEpName, ns=[name];
  closeLibEp();
  if(act==='play'){ playSeries(name); }
  else if(act==='convert'){ convertNames(ns); }
  else if(act==='mergeh264'){ mergeH264Names(ns); }
  else if(act==='merge'){ mergeSeriesNames(ns); }
  else if(act==='update'){ updateNames(ns); }
  else if(act==='open'){ openSeries(name); }
  else if(act==='delete'){ libDeleteNames(ns); }
}
$("#sdActions").addEventListener('click', sdActionClick);
$("#clearQueue").onclick=()=>{ cart={}; saveCart(); renderQueue(); syncResultButtons(); };
/* Clear button removed from the Trending head bar */
document.querySelectorAll("#boardTabs .tab").forEach(t=>t.onclick=()=>{ if(t.dataset.board==="explorer") loadExplorer(1); else loadTrending(); });
document.querySelectorAll("#trendCats .exchip").forEach(c=>c.onclick=()=>{        // leaderboard category switch
  if(c.dataset.cat===trendCategory) return;
  trendCategory=c.dataset.cat; trendPage=1; trendOffsets={1:0};
  loadTrending().then(()=>{ if(trendExpanded) trendTop(); });
});
$("#backHome").onclick=()=>{ $("#omni").value=""; $("#omniMode").textContent="Search"; $("#omniMode").classList.remove("link"); loadTrending(); };  // return from search results to the Trending home
$("#expPrev").onclick=()=>{ if(expPage>1) loadExplorer(expPage-1); };
$("#expNext").onclick=()=>{ if(expPage<expPages) loadExplorer(expPage+1); };
function expGoto(){ let n=parseInt($("#expPage").value,10); if(!n||n<1)n=1; if(n>expPages)n=expPages; loadExplorer(n); }
$("#expGo").onclick=expGoto;
$("#expPage").addEventListener("keydown",e=>{ if(e.key==="Enter"){ e.preventDefault(); expGoto(); } });
/* Rows selector removed — Catalog is a fixed 100 cards/page. */
let exQTimer=null;
$("#exQ").addEventListener("input",e=>{ exQ=e.target.value.trim(); clearTimeout(exQTimer); exQTimer=setTimeout(()=>loadExplorer(1),300); });
$("#exQ").addEventListener("keydown",e=>{ if(e.key==="Enter"){ e.preventDefault(); clearTimeout(exQTimer); loadExplorer(1); } });
$("#exSort").addEventListener("change",e=>{ exSort=e.target.value; loadExplorer(1); });
$("#exStatus").addEventListener("change",e=>{ exStatus=e.target.value; loadExplorer(1); });
// Collapsed Leaderboard = exactly 2 rows, so a width / Display-size change re-draws it when the card count no longer
// matches. The Leaderboard is on screen when its category chips are (the label text is not a reliable test).
window.addEventListener("resize",()=>{ clearTimeout(window._trTimer); window._trTimer=setTimeout(()=>{
  if(!trendExpanded && trendData.length && !DEMO && !$("#resultsSec").hidden && !$("#trendCats").hidden
     && $("#results").querySelectorAll(".poster").length!==Math.min(trendRows(), trendData.length)) renderTrending(); },200); });

/* ============ DEMO MODE (self-contained; used when /dl backend is unreachable, e.g. shared preview) ============ */
const SAMPLE=[
  {series_id:"d1",title:"错嫁豪门：夫人马甲藏不住",episode_cnt:98,score:"8.6"},
  {series_id:"d2",title:"重生之最强千金归来",episode_cnt:76,score:"8.4"},
  {series_id:"d3",title:"龙王殿：都市至尊归来",episode_cnt:120,score:"8.9"},
  {series_id:"d4",title:"闪婚老公竟是隐形首富",episode_cnt:64,score:"8.2"},
  {series_id:"d5",title:"天降萌宝：总裁爹地宠上天",episode_cnt:110,score:"8.7"},
  {series_id:"d6",title:"我在古代当神医",episode_cnt:88,score:"8.5"},
  {series_id:"d7",title:"顾少的隐婚新娘",episode_cnt:70,score:"8.3"},
  {series_id:"d8",title:"离婚后前妻惊艳全球",episode_cnt:82,score:"8.1"},
];
let demoState={running:false, series:[], log:["[demo] preview mode — backend not connected"]};
let demoTimer=null;
function demoSearch(q){ const s=(q||"").toLowerCase();
  return {results: SAMPLE.filter(x=> !s || x.title.toLowerCase().includes(s) || true).slice(0,8)}; }
function demoResolve(text){ const pick=SAMPLE[Math.floor(Math.random()*SAMPLE.length)];
  return {resolved:[{series_id:pick.series_id,title:pick.title,total:pick.episode_cnt}]}; }
function demoStatus(){       // + the live fields the app's server adds (MB/s, bytes, episodes), from the sample rows (~35 MB an episode)
  const EP=35e6, on=demoState.running;
  const series=demoState.series.map(s=>{ const dl=on && s.status==="downloading";
    return Object.assign({}, s, {need:s.total, dl_done:s.done, bytes:s.done*EP, bytes_total:s.total*EP, active:dl?4:0, rate:dl?6.4:0}); });
  const sum=k=>series.reduce((a,s)=>a+s[k],0);
  return Object.assign({}, demoState, {series, rate:sum("rate"), active:sum("active"), eps_done:sum("dl_done"), eps_need:sum("need"),
                                       bytes:sum("bytes"), bytes_total:sum("bytes_total")});
}
function demoStart(p){
  demoState.running=true;
  demoState.series=(p.series_ids||[]).map((id,i)=>{ const c=cart[id]||{};
    const tot=(c.sel&&c.sel.length)?c.sel.length:(c.total||60);
    return {sid:id,title:c.title||id,total:tot,done:i===0?Math.round(tot*0.34):0,status:i===0?"downloading":"queued"}; });
  demoState.log=["[demo] queued "+demoState.series.length+" dramas","[demo] downloading ("+String(p.quality||"1080p").replace(/[^0-9p]/g,"")
    +", "+(Number(p.series)||2)+" series × "+(Number(p.episodes)||4)+((Number(p.episodes)||4)===1 ? " episode" : " episodes")+" at once)"];
  if(demoTimer) clearInterval(demoTimer);
  demoTimer=setInterval(demoTick,650);
  return {ok:true};
}
function demoCancel(){ demoState.running=false; if(demoTimer) clearInterval(demoTimer);
  demoState.log.push("[demo] stopped"); }
function demoTick(){
  let active=demoState.series.find(s=>s.status==="downloading");
  if(!active){ const nx=demoState.series.find(s=>s.status==="queued"); if(nx){ nx.status="downloading"; active=nx; } }
  if(!active){ demoState.running=false; clearInterval(demoTimer); demoState.log.push("[demo] all done ✓"); poll(); return; }
  active.done=Math.min(active.total, active.done + Math.max(1,Math.round(active.total/28)));
  if(active.done>=active.total){ active.status="done"; demoState.log.push("[demo] ✓ "+active.title+" ("+active.total+" eps)"); }
  poll();
}
function seedDemo(){
  document.documentElement.setAttribute("data-demo","1");
  $("#dockEps").textContent="preview mode";
  /* no folder input in the new UI (folder is set via the native picker) */
  if(!Object.keys(cart).length){
    addToCart("d3","龙王殿：都市至尊归来",120); addToCart("d1","错嫁豪门：夫人马甲藏不住",98); addToCart("d6","我在古代当神医",88);
  }
  demoState.series=[
    {sid:"d3",title:"龙王殿：都市至尊归来",total:120,done:41,status:"downloading"},
    {sid:"d1",title:"错嫁豪门：夫人马甲藏不住",total:98,done:0,status:"queued"},
    {sid:"d6",title:"我在古代当神医",total:88,done:88,status:"done"},
  ];
  demoState.running=true;
  if(demoTimer) clearInterval(demoTimer); demoTimer=setInterval(demoTick,700);
  doSearch("");
  renderQueue();
  toast("Preview mode — sample data (backend not connected)");
}

/* ---------- license (key activation) ---------- */
function licReason(r){
  return ({
    not_found:"That key doesn't exist — check for typos.",
    not_bound_here:"This key isn't active on this PC (it was reset or moved). Activate it again here to continue.",
    revoked:"This key has been turned off. Contact the owner.",
    expired:"This key has expired.",
    bound_other:"This key is already active on another PC. Release it there first, or ask the owner to reset it.",
    network:"Couldn't reach the server. Check your internet connection.",
    not_configured:"Licensing isn't set up yet.",
    empty:"Enter your key.",
    no_key:"No key on this PC yet.",
    offline_no_grace:"You've been offline too long — connect to the internet to continue.",
    too_many_activations:"This key was activated too many times today. Try again tomorrow, or contact support if you didn't do this.",
    update_required:"Please update Hongguo Downloader to the latest version to use your key.",
    device_moved:"This key was activated on another PC. Activate it again here to continue.",
    needs_reactivate:"Please activate your key again on this PC."
  })[r] || ("Couldn't activate ("+(r||"unknown")+").");
}
function fmtDate(iso){ try{ return new Date(iso).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'}); }catch(e){ return iso; } }
async function licStatus(){ try{ return await (await fetch('/dl/license/status')).json(); }catch(e){ return null; } }
async function licUsage(){ try{ return await (await fetch('/dl/license/usage')).json(); }catch(e){ return null; } }
let LICENSED=false;
let _acctView=null;     // which view the panel last drew: "lic" / "free"
let _reactFail=null;    // the last "Re-activate this PC" failure reason, kept over background refreshes while still blocked

function renderAccount(u){
  const btn=$("#acctBtn");
  if(!u || u.configured===false){ btn.hidden=true; LICENSED=true; return; }  // dev/unconfigured -> unlimited, no chip
  btn.hidden=false;
  LICENSED = !!u.licensed;
  // The view flipped (Free <-> Licensed, e.g. right after Deactivate): drop the old view's result lines, so the
  // Free panel never shows a stale green "Activated — unlimited unlocked!" / "Payment received" note.
  const view = u.licensed ? "lic" : "free";
  if(_acctView && _acctView!==view){
    ["#licMsg","#acctMsg","#manageMsg"].forEach(s=>{ const m=$(s); m.textContent=''; m.className='lic-msg'; });
    if(!_buying){ const st=$("#buyStatus"); st.hidden=true; st.className='plan-note'; st.textContent=''; }
  }
  _acctView = view;
  $("#acctDevice").textContent = u.device_label || 'this PC';
  if(u.licensed){
    btn.textContent='Licensed';
    $("#acctSub").textContent='Licensed';
    $("#acctPlan").textContent='Licensed — unlimited';
    $("#rowUsed").hidden=true;
    $("#rowKey").hidden=false; $("#acctKey").textContent=u.key_masked||'—';
    $("#activateBox").hidden=true; $("#licensedBox").hidden=false; $("#acctDeact").hidden=false;
  } else {
    const used=(u.free_used==null?'?':u.free_used), lim=(u.free_limit==null?'?':u.free_limit);
    btn.textContent='Free '+used+'/'+lim;
    $("#acctSub").textContent='Free plan';
    $("#acctPlan").textContent='Free — '+lim+' series / day';
    $("#rowUsed").hidden=false; $("#acctUsed").textContent=used+' of '+lim+' used today';
    $("#rowKey").hidden=true;
    $("#activateBox").hidden=false; $("#licensedBox").hidden=true; $("#acctDeact").hidden=true;
  }
  // A key is saved but this PC isn't counted as licensed (e.g. its activation moved to another PC):
  // offer a one-click re-activate that reuses the saved key — never ask them to re-type it or buy again.
  const blocked = !u.licensed && u.has_key && u.blocked_reason;
  $("#reactivateBox").hidden = !blocked;
  if(blocked){
    // a fresher Re-activate failure (e.g. "activated too many times today") outranks the refresh's generic reason
    $("#reactMsg").textContent = licReason(_reactFail || u.blocked_reason);
    $("#activateBox").hidden=true;
  } else _reactFail=null;
  $("#plansBox").hidden = !!u.licensed || !!blocked;
  // expiry belongs to a licence: a released key's date must not linger on the Free view
  const rExp=$("#rowExpiry"); if(u.licensed && u.expires_at){ rExp.hidden=false; $("#acctExpiry").textContent=fmtDate(u.expires_at); } else { rExp.hidden=true; }
  const rDev=$("#rowDevices"), md=u.max_devices, du=(u.devices_used!=null?u.devices_used:u.device_count);
  if(u.licensed && md){ rDev.hidden=false; $("#acctDevices").textContent=(du!=null?(du+" of "+md):(md+" max")); } else { rDev.hidden=true; }
  if(u.licensed && u.plan){ $("#acctPlan").textContent=u.plan; }
}
// u.stale = the server answered from an old snapshot and is fetching a fresh one behind it: look again
// shortly (these looks read the app's own cache -- they don't call the licence server again). A slow licence
// server can still be mid-fetch at the next look, so back off 2.5 s -> 5 s -> 10 s and stop as soon as a fresh
// answer arrives. One retry chain at a time, and only the newest look may draw (an older reply that lands
// late -- or one that predates a Release -- can't put the old state back).
let _acctRetry=null, _acctSeq=0, _acctLast=null;
const _ACCT_BACKOFF=[2500,5000,10000];
async function _acctLook(step){
  const seq=++_acctSeq;
  const u=await licUsage();
  if(seq!==_acctSeq) return u;                     // superseded by a newer look
  if(u) _acctLast=u;
  renderAccount(u);
  if(u && u.stale){
    if(!_acctRetry && step<_ACCT_BACKOFF.length) _acctRetry=setTimeout(()=>{ _acctRetry=null; _acctLook(step+1); }, _ACCT_BACKOFF[step]);
  } else if(_acctRetry){ clearTimeout(_acctRetry); _acctRetry=null; }   // fresh now: nothing left to wait for
  return u;
}
function refreshAccount(){ return _acctLook(0); }
function openAccount(){ $("#licMsg").textContent=''; $("#licMsg").className='lic-msg'; $("#acctMsg").textContent=''; $("#acctMsg").className='lic-msg';
  $("#brMsg").textContent=''; $("#brMsg").className='lic-msg'; _reactFail=null; $("#acctModal").hidden=false;
  const sc=$("#acctModal .modal-scroll"); if(sc) sc.scrollTop=0; }      // always open at the top (plan + key box)
function closeAccount(){ $("#acctModal").hidden=true; }
// j = the /dl/submit reply: the limit comes from the server (not hard-coded), and when some series did
// start (j.ok) the message says how many were held back.
function promptActivate(j){
  const lim=(j && Number(j.free_limit)>0) ? Number(j.free_limit) : 0, cap=lim ? ` (${lim}/day)` : "";
  const held=(j && Array.isArray(j.blocked)) ? j.blocked.length : 0;
  toast(j && j.ok && held ? `Free limit reached${cap} — ${held} series not started. Activate for unlimited, or try again tomorrow`
                          : `Daily free limit reached${cap} — activate for unlimited, or try again tomorrow`, true);
  refreshAccount().then(()=>{ openAccount(); setTimeout(()=>$("#licKey").focus(),200); });
}

async function activateKey(){
  const key=$("#licKey").value.trim(), msg=$("#licMsg"); msg.className='lic-msg';
  if(!key){ msg.textContent='Enter your key.'; return; }
  const btn=$("#licGo"); btn.disabled=true; btn.textContent='Activating…';
  let r; try{ r=await (await fetch('/dl/license/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})})).json(); }
  catch(e){ r={ok:false,reason:'network'}; }
  btn.disabled=false; btn.textContent='Activate';
  // the inline line sits in the free-view box, which hides once the licensed view renders -> also toast it
  if(r.ok || r.active){ msg.className='lic-msg ok'; msg.textContent='Activated — unlimited unlocked!'; $("#licKey").value=''; await refreshAccount(); toast('✓ Activated — unlimited downloads unlocked'); }
  else { msg.textContent=licReason(r.reason); }
}
async function deactivateLicense(){
  if(!(await ask('Release this PC?', 'You can then activate the same key on another PC — but only once every 7 days.', {ok:'Release this PC', danger:true}))) return;
  const msg=$("#acctMsg"); msg.className='lic-msg'; const btn=$("#acctDeact"); btn.disabled=true;
  let r; try{ r=await (await fetch('/dl/license/deactivate',{method:'POST'})).json(); }
  catch(e){ r={ok:false,reason:'network'}; }
  // The server says this PC no longer holds the key at all (reset / moved / deleted / turned off): the app has
  // already removed it here, so the panel must revert to Free now too -- not stay on "Licensed".
  const gone = !r.ok && ["not_bound_here","not_found","revoked"].includes(r.reason);
  if(r.ok || gone){
    // Released: show the Free view right now (the last snapshot with every licence-only field dropped) instead
    // of "Licensed" + an enabled Deactivate for one more licence-server round trip; then draw the real state.
    // The button stays off until that has landed, so it can't be pressed again for a key that's already gone.
    _acctSeq++;                                      // a look already in flight predates the release: ignore it
    const p=_acctLast||{};
    renderAccount({configured:true, licensed:false, has_key:false, device_label:p.device_label||$("#acctDevice").textContent,
                   free_used:p.free_used, free_limit:p.free_limit, remaining:p.remaining});
    toast(r.ok ? "Released — you can now activate on another PC"
               : (r.reason==="revoked" ? "This key was turned off — it's been removed from this PC"
                                       : "This PC no longer held that key (it was reset or moved) — removed here"), !r.ok);
    await refreshAccount();
    btn.disabled=false;
    return;
  }
  btn.disabled=false;
  if(r.reason==='cooldown'){ msg.textContent='You can move to another PC on '+fmtDate(r.next_move_allowed_at)+'.'; }
  else { msg.textContent=licReason(r.reason); }
}
async function manageBilling(){
  const btn=$("#licManage"), msg=$("#manageMsg"); msg.className='lic-msg';
  btn.disabled=true; const t=btn.textContent; btn.textContent='Opening…';
  let r; try{ r=await (await fetch('/dl/license/manage',{method:'POST'})).json(); }
  catch(e){ r={ok:false,reason:'network'}; }
  btn.disabled=false; btn.textContent=t;
  if(r.ok){ msg.className='lic-msg ok'; msg.textContent='Opened Stripe billing in your browser — manage or cancel there.'; }
  else if(r.reason==='no_customer'){ msg.textContent='This license wasn’t bought with a card (e.g. a gift/lifetime key), so there’s no card billing to manage.'; }
  else if(r.reason==='no_key'||r.reason==='no_license'){ msg.textContent='No active license found on this PC.'; }
  else { msg.textContent='Couldn’t open billing right now — please try again, or contact support.'; }
}
async function reactivateThisPC(){
  const btn=$("#reactGo"), msg=$("#reactMsg"); btn.disabled=true; const t=btn.textContent; btn.textContent='Re-activating…';
  _reactFail=null;
  let r; try{ r=await (await fetch('/dl/license/reactivate',{method:'POST'})).json(); }
  catch(e){ r={ok:false,reason:'network'}; }
  btn.disabled=false; btn.textContent=t;
  if(r.ok || r.active){ toast('Re-activated on this PC'); await refreshAccount(); }
  else { _reactFail=r.reason||'unknown'; msg.textContent=licReason(_reactFail); }   // kept over background refreshes
}
$("#reactGo").onclick=reactivateThisPC;
$("#licGo").onclick=activateKey;
$("#licKey").addEventListener('keydown',e=>{ if(e.key==='Enter') activateKey(); });
$("#acctBtn").onclick=()=>{ openAccount(); refreshAccount(); };   // open at once, then show the live state
$("#acctClose").onclick=$("#acctCloseB").onclick=closeAccount;
$("#acctDeact").onclick=deactivateLicense;
$("#licManage").onclick=manageBilling;
$("#acctModal").addEventListener('click',e=>{ if(backdropClick(e)) closeAccount(); });

/* ---------- plans + in-app card checkout ---------- */
// Plans come from the pay Worker (via the app backend) so prices never drift from the website.
// Buying opens Stripe Checkout in the real browser; on payment the key is minted, emailed, AND
// auto-activated on THIS PC by the backend poll. Pasting a key by hand still works too.
let PLANS = [];
const DEFAULT_PLANS = [   // shown only if the live list can't be fetched
  { id:"month", title:"Monthly",  usd:"9.99",  interval:"mo", blurb:"Unlimited downloads · billed monthly · cancel anytime" },
  { id:"year",  title:"Yearly",   usd:"29.99", interval:"yr", blurb:"Unlimited downloads · billed yearly · save 75%", badge:"Most popular" },
  { id:"life",  title:"Lifetime", usd:"59.99", interval:"",   blurb:"Unlimited forever · pay once · never expires" },
];
function renderPlans(){
  const list = (PLANS && PLANS.length) ? PLANS : DEFAULT_PLANS;
  $("#planList").innerHTML = list.map(p=>`
    <div class="plan${p.badge?" best":""}" data-plan="${esc(p.id)}">
      <div>
        <div class="pn">${esc(p.title)}${p.badge?` <span class="tag">${esc(p.badge)}</span>`:""}</div>
        <div class="pd">${esc(p.blurb||"Unlimited downloads")}</div>
      </div>
      <div class="pp"><div class="stars">$${esc(p.usd)}</div><div class="usd">${p.interval?esc("/"+p.interval):"one-time"}</div></div>
    </div>`).join("");
}
async function loadPlans(){
  try{ const r=await (await fetch('/dl/license/plans')).json(); if(r&&r.plans&&r.plans.length){ PLANS=r.plans; } }catch(e){}
  renderPlans();
}

// Buy flow: create a Checkout session (backend opens Stripe in the real browser), then poll until
// the key is minted + auto-activated on this PC. The key is also emailed, so a dropped poll is safe.
let _buying=false, _pollTimer=null;
async function startPurchase(plan){
  if(_buying || !plan) return;
  _buying=true;
  const st=$("#buyStatus"); st.hidden=false; st.className='plan-note'; st.textContent='Opening secure checkout in your browser…';
  document.querySelectorAll('#planList .plan').forEach(el=>el.classList.add('disabled'));
  let r; try{ r=await (await fetch('/dl/license/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan})})).json(); }
  catch(e){ r={ok:false,reason:'network'}; }
  if(!r.ok){
    _buying=false; document.querySelectorAll('#planList .plan').forEach(el=>el.classList.remove('disabled'));
    st.className='plan-note err';
    st.textContent = r.reason==='network' ? 'Could not reach the store — check your connection and try again.' : 'Could not start checkout. Please try again.';
    return;
  }
  const url=r.url;
  st.className='plan-note';
  st.innerHTML='Finish paying in the browser tab that just opened — this window unlocks automatically when it\'s done. &nbsp;<a href="#" id="buyReopen">Reopen checkout</a>';
  const ro=$("#buyReopen"); if(ro) ro.onclick=(e)=>{ e.preventDefault(); openExt(url); };
  pollPurchase(r.session_id, 0);
}
async function pollPurchase(sid, tries){
  if(!sid){ _buying=false; return; }
  let r; try{ r=await (await fetch('/dl/license/purchase-poll?session_id='+encodeURIComponent(sid))).json(); }
  catch(e){ r={pending:true}; }
  const st=$("#buyStatus");
  if(r && r.pending===false){
    _buying=false; document.querySelectorAll('#planList .plan').forEach(el=>el.classList.remove('disabled'));
    if(r.activated || r.ok){ st.className='plan-note ok'; st.textContent='Payment received — unlimited unlocked on this PC!'; toast('Licensed — unlimited unlocked!'); await refreshAccount(); return; }
    st.className='plan-note err';
    st.innerHTML='Payment received, but this PC couldn\'t be activated ('+esc(licReason(r.reason))+'). Your key was emailed — paste it above to activate.';
    await refreshAccount(); return;
  }
  if(tries>200){   // ~10 min — stop polling; the key is emailed regardless
    _buying=false;
    st.className='plan-note';
    st.innerHTML='Still waiting for payment. Once you finish, your key is emailed to you — paste it above, or &nbsp;<a href="#" id="buyRecheck">check again</a>.';
    const rc=$("#buyRecheck"); if(rc) rc.onclick=(e)=>{ e.preventDefault(); if(_buying) return; _buying=true; st.className='plan-note'; st.textContent='Checking…'; pollPurchase(sid, 0); };
    return;
  }
  _pollTimer=setTimeout(()=>pollPurchase(sid, tries+1), 3000);
}
function openExt(u){ if(!u || !/^https?:\/\//i.test(String(u))) return;   // server-relayed links (GitHub / checkout): web pages only, never javascript:
  try{ window.open(u,"_blank","noopener"); }catch(e){ location.href=u; } }
let UPDATE_INFO=null;
const _UPD_DISMISS="hg_upd_dismiss";
function _updDismissed(v){ try{ return !!v && localStorage.getItem(_UPD_DISMISS)===v; }catch(e){ return false; } }
function _setUpdDismissed(v){ try{ v?localStorage.setItem(_UPD_DISMISS,v):localStorage.removeItem(_UPD_DISMISS); }catch(e){} }

// Reflect the latest check into the UI: Account version + dot always tell the truth;
// the top banner is dismissable per-version so it never nags after being closed.
function renderUpdate(){
  const r=UPDATE_INFO;
  if(r&&r.current) $("#acctVersion").textContent = "v"+r.current;
  const has = !!(r&&r.update&&r.url);
  $("#acctBtn").classList.toggle("hasupd", has);
  $("#updRow").hidden = !has;
  if(has){
    $("#ubText").innerHTML = `<b>Update available</b> — ${esc(r.latest||"")}`;
    $("#ubGet").onclick = ()=>openUpdate();
  }
  $("#updBanner").hidden = !(has && !_updDismissed(r.latest));
  if(has) $("#updBannerSub").textContent =
    ` — version ${r.latest} is ready` + (r.current?` (you have v${r.current})`:"");
}

// Background checker: polls the GitHub-backed /dl/update-check (cached ~30 min server-side).
// Returns the reply (null when the app couldn't be reached) so the manual button can tell a failure from "latest".
async function checkUpdate(){
  let r; try{ r=await (await fetch("/dl/update-check")).json(); }catch(e){ return null; }
  if(!r) return null;
  UPDATE_INFO=r;
  renderUpdate();
  return r;
}

function openUpdate(){
  const r=UPDATE_INFO; if(!r||!r.update||!r.url) return;
  $("#updFrom").textContent = "v"+(r.current||"—");
  $("#updTo").textContent   = "v"+(r.latest||"—");
  $("#updName").textContent = (r.name && r.name!==r.latest) ? r.name : "";
  $("#updNotes").textContent = r.notes || "No release notes were provided.";
  const st=$("#updStatus"); st.hidden=true; st.className="upd-status"; st.textContent="";
  _setProg(null);
  const dl=$("#updDownload"); dl.disabled=false; dl.textContent="Download update"; dl.onclick=downloadAndVerify;
  const pg=$("#updPage");
  if(r.page){ pg.hidden=false; pg.onclick=()=>openExt(r.page); } else { pg.hidden=true; }
  $("#updModal").hidden=false;
}
function closeUpdate(){ _stopUpdPoll(); $("#updModal").hidden=true; }

function _shortPub(s){ const m=/CN=([^,]+)/i.exec(s||""); return (m?m[1]:(s||"")).trim().slice(0,48); }
function _mb(b){ b=+b||0; return (b/1048576).toFixed(b>=10485760?0:1)+" MB"; }
let _updPoll=null;
function _stopUpdPoll(){ if(_updPoll){ clearInterval(_updPoll); _updPoll=null; } }
function _setProg(pct){ const p=$("#updProg"), b=$("#updBar"); if(!p||!b) return;
  if(pct==null){ p.hidden=true; b.style.width="0%"; return; }
  p.hidden=false; b.style.width=Math.max(0,Math.min(100,pct))+"%"; }

async function downloadAndVerify(){
  // Option A "one-click in-app update": the app downloads the installer itself (live progress),
  // then lets the user install it right here — no browser trip, no re-download. The Authenticode
  // check stays and simply upgrades the wording to "verified" once the build is code-signed.
  const r=UPDATE_INFO; if(!r) return;
  const st=$("#updStatus"), dl=$("#updDownload");
  st.hidden=false; st.className="upd-status"; st.textContent="Starting download…"; dl.disabled=true; _setProg(0);
  _stopUpdPoll();
  _updPoll=setInterval(async ()=>{
    let p=null; try{ p=await (await fetch("/dl/update-progress")).json(); }catch(e){}
    if(!p) return;
    if(p.state==="downloading"){
      if(p.total>0){ _setProg(p.pct||0); st.textContent="Downloading the update… "+(p.pct||0)+"%"; }
      else{ st.textContent="Downloading the update… "+_mb(p.downloaded); }
    } else if(p.state==="verifying"){ _setProg(100); st.textContent="Almost ready…"; }
  }, 500);
  let v=null; try{ v=await (await fetch("/dl/update-download",{method:"POST"})).json(); }catch(e){}
  _stopUpdPoll(); dl.disabled=false;
  if(!v||!v.ok){
    _setProg(null); st.className="upd-status warn";
    st.textContent = (v&&v.busy) ? "A download is already running — one moment."
                                  : "Couldn't download the update. Check your connection and try again.";
    dl.textContent="Try again"; dl.onclick=downloadAndVerify; return;
  }
  _setProg(100);
  const pub=_shortPub(v.publisher);
  if(v.signed && !v.valid){
    _setProg(null); st.className="upd-status bad";
    st.textContent="⚠ This installer's signature looks wrong. Don't run it — get it from the website.";
    dl.textContent="Open website"; dl.onclick=()=>openExt(r.page||r.url); return;
  }
  if(v.expected_publisher && v.valid && !v.trusted){
    _setProg(null); st.className="upd-status bad";
    st.textContent="⚠ Signed by an unexpected publisher ("+(pub||"?")+"). Don't run it — get it from the website.";
    dl.textContent="Open website"; dl.onclick=()=>openExt(r.page||r.url); return;
  }
  st.className="upd-status ok";
  st.textContent = v.trusted ? ("✓ Downloaded & verified"+(pub?" — signed by "+esc(pub):"")+". Ready to install.")
                             : "✓ Downloaded and ready to install.";
  dl.textContent="Install now"; dl.onclick=()=>runInstaller(v.path);
}
async function runInstaller(path){
  const st=$("#updStatus"), dl=$("#updDownload");
  st.className="upd-status ok";
  st.textContent="Installing… the app will close, then reopen updated. In the installer window, click Next → Next → Finish.";
  dl.disabled=true; _setProg(null);
  let ok=false;
  try{ const j=await (await fetch("/dl/update-run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path})})).json(); ok=!!(j&&j.ok); }
  catch(e){}
  if(!ok){
    st.className="upd-status warn";
    st.textContent="Couldn't start the installer automatically. Open it from your Downloads folder, or get it from the website.";
    dl.disabled=false; dl.textContent="Open website"; dl.onclick=()=>openExt(UPDATE_INFO&&(UPDATE_INFO.page||UPDATE_INFO.url));
    toast("Couldn't launch the installer", true);
  }
}

$("#updWhats").onclick=()=>openUpdate();
/* License-section buttons: Check update / Website / Support */
$("#acctCheckUpd").onclick=async ()=>{
  const b=$("#acctCheckUpd"), old=b.textContent; b.disabled=true; b.textContent="Checking…";
  const r=await checkUpdate();
  b.disabled=false; b.textContent=old;
  // ok:false = GitHub couldn't be reached (offline, blocked, rate-limited) and nothing was known yet: that's
  // not "latest". (The server keeps a good answer ~30 min and has no force-refresh switch, so "latest" can be
  // up to 30 min old -- the same answer the banner uses.)
  if(!r || r.ok===false){ toast("Couldn’t check for updates — check your connection and try again", true); return; }
  if(r.update && r.url){ openUpdate(); }
  else { toast("You’re on the latest version"+(r.current?" (v"+r.current+")":"")); }
};
$("#acctWebsite").onclick=()=>openExt("https://hongguodownloader.com/");
$("#acctSupport").onclick=()=>openExt("https://t.me/M4st3r0");
/* Bug report: save a redacted logs/screenshot zip, open its folder + the support chat to attach */
$("#brSend").onclick=async ()=>{
  const b=$("#brSend"), old=b.innerHTML, m=$("#brMsg");
  const logs=$("#brLogs").checked, shot=$("#brShot").checked;
  if(!logs && !shot){ m.textContent="Pick app logs and/or a screenshot first."; return; }
  b.disabled=true; b.textContent="Preparing…"; m.textContent="";
  let r=null; try{ r=await (await fetch("/dl/bugreport",{method:"POST",headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({logs,screenshot:shot})})).json(); }catch(e){}
  b.disabled=false; b.innerHTML=old;
  if(r&&r.ok){ m.className="lic-msg ok"; m.textContent="Report saved — the folder opened with it selected. Drag it into the Telegram chat.";
               openExt("https://t.me/M4st3r0"); }
  else { m.className="lic-msg"; m.textContent="Couldn't create the report"+((r&&r.error)?(": "+r.error):"")+"."; toast("Bug report failed", true); }
};
// "Update now" = the one-click in-app updater (download with progress, then Install now), same as
// What's new -> Download update; the browser only as a fallback when there's no in-app update info.
$("#updNow").onclick=()=>{ const r=UPDATE_INFO;
  if(r&&r.update&&r.url){ openUpdate(); downloadAndVerify(); }
  else if(r&&(r.page||r.url)) openExt(r.page||r.url); };
$("#updDismiss").onclick=()=>{ const r=UPDATE_INFO; if(r) _setUpdDismissed(r.latest); $("#updBanner").hidden=true; };
$("#updModalClose").onclick=$("#updLater").onclick=closeUpdate;
$("#updModal").addEventListener('click',e=>{ if(backdropClick(e)) closeUpdate(); });
$("#planList").onclick=(e)=>{ const p=e.target.closest(".plan"); if(p&&p.dataset.plan) startPurchase(p.dataset.plan); };
loadPlans();

/* ---------- boot ---------- */
let _appStarted=false;
function startApp(){
  if(_appStarted) return; _appStarted=true;
  // the old Library header settings (Quality / Speed / Series, "hg_ub") are gone -- the download bar's are used: drop them
  try{ localStorage.removeItem("hg_ub"); }catch(e){}
  loadDir(); poll(); loadTrending(); loadLibrary();
  // adaptive poll: ~1s while a job runs (smooth live poster reveal), relaxed to 2s when idle
  (function tick(){ const ms=(lastStatus && lastStatus.running)?900:2000;
    setTimeout(()=>{ if(!DEMO) poll(); tick(); }, ms); })();
  if(!(DEMO||ALLOW_DEMO)){                        // the Account chip (free vs licensed): populate now, then keep it live
    refreshAccount();
    // Your own actions (download, activate, release) already update it instantly. This only catches changes
    // made elsewhere (the daily free count resetting, a key released or revoked from another PC). Kept gentle
    // on purpose: every licence-server usage check writes a row, so no per-minute polling from every open app.
    let _acctAt=Date.now();
    const _acctKick=(gap)=>{ if(document.hidden || Date.now()-_acctAt<gap) return; _acctAt=Date.now(); refreshAccount(); };
    setInterval(()=>_acctKick(0), 10*60*1000);                              // safety net
    document.addEventListener('visibilitychange',()=>_acctKick(2*60*1000)); // back to the window
    window.addEventListener('focus',()=>_acctKick(2*60*1000));
  }
  if(!(DEMO||ALLOW_DEMO)){                        // background update checker (banner + modal)
    checkUpdate();                               // on launch
    setInterval(checkUpdate, 3*60*60*1000);      // and every 3h for long-running sessions
    document.addEventListener('visibilitychange',()=>{ if(!document.hidden) checkUpdate(); });
  }
}
renderQueue();
startApp();


/* Display size — scale the whole UI to fit the user's monitor / Windows display scaling
   (125%, 150%, 200%, small laptops). Applied via CSS zoom on the root; persisted per device. */
(function(){
  var KEY='hg_uiscale', STEPS=[60,70,80,90,100,110,125,150,175,200];
  function cur(){ var v=parseInt(localStorage.getItem(KEY)||'100',10); return STEPS.indexOf(v)>-1?v:100; }
  // --uiz: under the root's CSS zoom a vh / vw length is scaled too (82vh at 150% = 123% of the window), so every
  // viewport-capped box (dialogs, players, toast) divides by it and still fits inside the real window
  function apply(v){ try{ document.documentElement.style.zoom = v/100; document.documentElement.style.setProperty('--uiz', String(v/100)); }catch(e){}
    var el=document.getElementById('uiZoomVal'); if(el) el.textContent=v+'%'; }
  function set(v){ localStorage.setItem(KEY,String(v)); apply(v);
    try{ window.dispatchEvent(new Event('resize')); }catch(e){} }   // zoom fires no resize: re-fit the 2-row Leaderboard
  apply(cur());
  document.addEventListener('click',function(e){
    var t=e.target; if(!t||!t.id) return;
    if(t.id==='uiZoomIn'){ var i=STEPS.indexOf(cur()); if(i<STEPS.length-1) set(STEPS[i+1]); }
    else if(t.id==='uiZoomOut'){ var i=STEPS.indexOf(cur()); if(i>0) set(STEPS[i-1]); }
  });
})();

