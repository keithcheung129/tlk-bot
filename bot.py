<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>TLK – Card Dex</title>
<style>
  :root{--bg:#0b1220;--panel:#0f172a;--muted:#94a3b8;--text:#e5e7eb;--accent:#22c55e;--accent2:#38bdf8;--line:#1f2937}
  html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
  .wrap{max-width:1200px;margin:0 auto;padding:20px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.2)}
  .hdr{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--line)}
  .hdr h1{font-size:18px;margin:0}
  .muted{color:var(--muted);font-size:12px}

  .toolbar{display:flex;flex-wrap:wrap;gap:10px 12px;padding:12px 16px;border-bottom:1px solid var(--line)}
  .pill{display:flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid rgba(255,255,255,.12);border-radius:9999px;background:#0b1220;white-space:nowrap}
  .pill input,.pill select{appearance:none;background:#0f172a;color:#fff;border:0;outline:0;height:32px;line-height:32px;padding:0 10px;border-radius:8px}
  .pill input[type="checkbox"]{width:16px;height:16px}

  .btn{height:34px;line-height:34px;padding:0 12px;border-radius:10px;border:0;background:#2563eb;color:#fff;font-weight:600;cursor:pointer}
  .btn.alt{background:#334155}

  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;padding:16px}
  .card{background:#0b1220;border:1px solid var(--line);border-radius:14px;overflow:hidden;position:relative}
  .thumb{aspect-ratio:3/4;background:#060a12;display:block;width:100%;object-fit:cover;transition:opacity .2s, transform .08s}
  .card.unowned .thumb{opacity:.35}
  .thumb:active{transform:scale(.99)}
  .meta{padding:10px}
  .name{font-size:13px;font-weight:700}
  .sub{font-size:12px;color:var(--muted)}
  .cid{display:flex;align-items:center;gap:6px;margin-top:6px}
  .cid code{font-size:11px;background:#0f172a;border:1px solid #1f2937;border-radius:6px;padding:2px 6px;color:#cbd5e1}
  .copy{font-size:11px;background:#0f172a;border:1px solid #1f2937;border-radius:6px;padding:2px 6px;color:#38bdf8;cursor:pointer}
  .copy:active{transform:scale(.98)}

  .badge{position:absolute;top:8px;right:8px;background:#111827;border:1px solid #374151;border-radius:10px;padding:3px 6px;font-size:12px}
  .footer{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-top:1px solid var(--line)}
  .tiny{font-size:12px;color:var(--muted)}

  /* popup */
  #imgPopup{position:fixed;display:none;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.85);justify-content:center;align-items:center;z-index:9999}
  #imgPopup img{max-width:90%;max-height:90%;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.6)}
  #imgPopup.closeable{cursor:pointer}
</style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="hdr">
        <h1>TLK Card Dex <span class="muted">browse all cards & plan crafts</span></h1>
        <div class="tiny">🎟 <span id="tickets">–</span> • 🪙 <span id="tokens">–</span></div>
      </div>

      <div class="toolbar">
        <label class="pill">Discord ID:
          <input id="userId" placeholder="Optional — highlight owned">
        </label>
        <label class="pill">Type:
          <select id="type">
            <option>player</option><option>manager</option><option>stadium</option><option>event</option><option>ALL</option>
          </select>
        </label>
        <label class="pill">Rarity:
          <select id="rarity">
            <option>ALL</option><option>N</option><option>R</option><option>AR</option><option>SR</option><option>SSR</option>
          </select>
        </label>
        <label class="pill">Position:
          <select id="position">
            <option>ALL</option><option>GK</option><option>RB</option><option>LB</option><option>CB</option><option>DM</option><option>CM</option><option>AM</option><option>RW</option><option>LW</option><option>ST</option>
          </select>
        </label>
        <label class="pill">Batch:
          <select id="batch">
            <option>ALL</option><option>Base</option><option>Base U</option>
          </select>
        </label>
        <label class="pill">Club:
          <select id="club">
            <option>ALL</option>
          </select>
        </label>
        <label class="pill">Search:
          <input id="search" placeholder="name / club / card_id">
        </label>
        <label class="pill"><input type="checkbox" id="missingOnly"> Missing only</label>
        <label class="pill">Sort:
          <select id="sortBy">
            <option value="rarity">Rarity</option>
            <option value="club">Club</option>
            <option value="position">Position</option>
            <option value="name">Name</option>
            <option value="owned">Owned first</option>
          </select>
        </label>
        <button class="btn" id="btnApply">Apply</button>
        <button class="btn alt" id="btnClear">Clear</button>
      </div>
      <div id="status" class="muted" style="padding:8px 16px;display:none"></div>

      <div id="dex" class="grid" aria-live="polite"></div>

      <div class="footer">
        <div class="tiny" id="countInfo">0 items</div>
        <div class="tiny">Tip: enter your Discord ID to light up owned cards and see copy counts.</div>
      </div>
    </div>
  </div>

  <!-- image popup -->
  <div id="imgPopup" class="closeable" aria-hidden="true"><img src="" alt="preview"></div>

<script>
/* ===== Config ===== */
const API_BASE = 'https://the-last-kick.keithcheung129.workers.dev/api';
// Safe DOM helpers
const $ = (id) => document.getElementById(id);
const getVal = (id, def = "") => ($(`${id}`)?.value ?? def);
const setVal = (id, v) => { const el = $(`${id}`); if (el) el.value = v; };
const getChecked = (id) => !!$(`${id}`)?.checked;
const setChecked = (id, v) => { const el = $(`${id}`); if (el && "checked" in el) el.checked = !!v; };
const U = (s)=>String(s??'').toUpperCase();
// Return the first non-empty image field for a card
const pickImg = (c) => c.image_url || c.image_ref || c.image || c.img || "";


  
/* ===== State ===== */
let ALL_CARDS = [];           // full catalogue from /cards
let OWN_COUNTS = {};          // { card_id: copies }
let BAL = { tickets:'–', tokens:'–' };

// --- Image popup (null-safe) ---
function openImg(src){
  const el  = document.getElementById("imgPopup");
  const img = el ? el.querySelector("img") : null;
  if (!el || !img) return;
  img.src = src;
  el.style.display = "flex";
  el.setAttribute("aria-hidden", "false");
}
function closeImg(){
  const el  = document.getElementById("imgPopup");
  const img = el ? el.querySelector("img") : null;
  if (!el || !img) return;
  el.style.display = "none";
  img.src = "";
  el.setAttribute("aria-hidden", "true");
}
document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("imgPopup");
  if (el) el.addEventListener("click", closeImg);
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeImg(); });
});


/* ===== API helper (unwrap Worker envelope) ===== */
async function api(action, payload){
  const res = await fetch(API_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...payload })
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0,200)}`);

  let json; try { json = JSON.parse(text); } catch { throw new Error("Bad JSON from API"); }

  // Worker envelope: { ok, data, status }
  if ("ok" in json && json.ok === false) {
    const err = (json.data && json.data.error) || json.error || "Request failed";
    throw new Error(err);
  }
  const payloadOut = ("data" in json) ? json.data : json;

  // Script-level error (e.g., unknown_action) bubbles up
  if (payloadOut && payloadOut.error) throw new Error(payloadOut.error);

  return payloadOut;
}

function setStatus(msg) {
  const el = document.getElementById("status");
  if (!el) return;
  if (!msg) { el.style.display = "none"; el.textContent = ""; return; }
  el.style.display = "block";
  el.textContent = msg;
}
function fail(msg) {
  console.error(msg);
  setStatus("⚠️ " + String(msg));
}



/* ===== Loaders ===== */
async function loadCatalogue(){
  const data = await api("cards", {
    type:     getVal("type", "player"),
    batch:    getVal("batch", "ALL"),
    rarity:   getVal("rarity", "ALL"),
    position: getVal("position", "ALL"),
    club:     getVal("club", "ALL"),
    search:   getVal("search", "").trim()
  });

  ALL_CARDS = data.items || [];
  console.log("Loaded cards:", ALL_CARDS.length);
  console.log("Sample card:", ALL_CARDS[0]);


  // Rebuild the Club dropdown only if it exists
  const sel = document.getElementById("club");
  if (sel) {
    const cur = sel.value || "ALL";
    const clubs = Array.from(new Set(
      ALL_CARDS.map(x => (x.club || "").trim()).filter(Boolean)
    )).sort((a,b)=>a.localeCompare(b));

    sel.innerHTML = '<option>ALL</option>' + clubs.map(c => `<option>${c}</option>`).join('');

    if (Array.from(sel.options).some(o => o.value === cur)) {
      sel.value = cur;
    }
  }

  const countEl = document.getElementById("countInfo");
  if (countEl) countEl.textContent = `${ALL_CARDS.length} item${ALL_CARDS.length===1?'':'s'}`;
}


async function loadOwned(){
  const uid = getVal("userId", "").trim();
  OWN_COUNTS = {};
  // Don't fetch owned info unless a user ID is present
  if (!uid) { 
    // also clear balances display when no user
    document.getElementById("tickets").textContent = "–";
    document.getElementById("tokens").textContent  = "–";
    return;
  }
  const data = await api("collection", { user_id: uid, aggregate_only: true });
  OWN_COUNTS = data.counts_by_card || {};
  const bal = data.balances || {};
  document.getElementById("tickets").textContent = bal.tickets ?? "–";
  document.getElementById("tokens").textContent  = bal.tokens ?? "–";
}

// Debounced overlay update when typing Discord ID
let ownedTimer;
document.addEventListener("DOMContentLoaded", ()=>{
  const uid = document.getElementById("userId");
  if (uid){
    uid.addEventListener("input", ()=>{
      clearTimeout(ownedTimer);
      ownedTimer = setTimeout(async ()=>{
        await loadOwned();   // only fetches if ID present
        render();            // apply dim/highlight/counts
      }, 350);
    });
  }
});



/* ===== Sort & Render ===== */
const RARITY_ORDER = ["SSR","SR","AR","R","N","U","ALL"];
const POSITION_ORDER = ["GK","CB","RB","LB","DM","CM","AM","LW","RW","ST","MGR","STM","EVE","ALL"];
const rank = (v, arr)=>{ const i = arr.indexOf(U(v)); return i<0 ? 999 : i; };

function sortCards(arr){
  const mode = getVal("sortBy", "rarity");
  arr.sort((a,b)=>{
    const ra = rank(a.rarity, RARITY_ORDER), rb = rank(b.rarity, RARITY_ORDER);
    const pa = rank(a.position, POSITION_ORDER), pb = rank(b.position, POSITION_ORDER);
    const ca = U(a.club), cb = U(b.club);
    const na = String(a.name||""), nb = String(b.name||"");
    const oa = OWN_COUNTS[a.card_id] ? 0 : 1;
    const ob = OWN_COUNTS[b.card_id] ? 0 : 1;

    switch(mode){
      case "club":     return ca.localeCompare(cb) || pa - pb || ra - rb || na.localeCompare(nb);
      case "position": return pa - pb || ra - rb || ca.localeCompare(cb) || na.localeCompare(nb);
      case "name":     return na.localeCompare(nb);
      case "owned":    return oa - ob || ra - rb || na.localeCompare(nb);  // owned first
      case "rarity":
      default:         return ra - rb || ca.localeCompare(cb) || pa - pb || na.localeCompare(nb);
    }
  });
  return arr;
}

function render(){
  const root = document.getElementById("dex");
  root.innerHTML = "";

  const hasUser = getVal("userId", "").trim().length > 0;
  const missingOnly = getChecked("missingOnly") && hasUser;

  const cards = sortCards(ALL_CARDS.slice())
    .filter(c => !(missingOnly && (OWN_COUNTS[c.card_id] || 0) > 0)); // only hide owned if user entered

  for (const c of cards){
    const ownedCount = hasUser ? (OWN_COUNTS[c.card_id] || 0) : 0;
    const owned = hasUser && ownedCount > 0;

    const card = document.createElement("div");
    card.className = "card" + (owned ? "" : " unowned");  // dims everything unless owned

    const img = document.createElement("img");
    img.className = "thumb";
    img.loading = "lazy";
    img.src = pickImg(c);
    img.alt = c.name || c.card_id || "";
    img.addEventListener("click", ()=>openImg(img.src));
    card.appendChild(img);

    // Show count badge only if user entered an ID AND owns it
    if (hasUser && owned){
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = `×${ownedCount}`;
      card.appendChild(badge);
    }

    const meta = document.createElement("div");
    meta.className = "meta";

    const nameEl = document.createElement("div");
    nameEl.className = "name";
    nameEl.textContent = c.name || "—";

    const subEl = document.createElement("div");
    subEl.className  = "sub";
    subEl.textContent = [c.rarity, c.club, c.position, c.batch].filter(Boolean).join(" • ");

    const cidRow = document.createElement("div");
    cidRow.className = "cid";
    const codeEl = document.createElement("code");
    codeEl.textContent = c.card_id;
    const copyBtn = document.createElement("button");
    copyBtn.className = "copy";
    copyBtn.type = "button";
    copyBtn.textContent = "Copy ID";
    copyBtn.addEventListener("click", async ()=>{
      try { await navigator.clipboard.writeText(c.card_id); copyBtn.textContent = "Copied!"; setTimeout(()=>copyBtn.textContent="Copy ID", 900); }
      catch { copyBtn.textContent = "Failed"; setTimeout(()=>copyBtn.textContent="Copy ID", 900); }
    });
    cidRow.appendChild(codeEl);
    cidRow.appendChild(copyBtn);

    meta.appendChild(nameEl);
    meta.appendChild(subEl);
    meta.appendChild(cidRow);

    card.appendChild(meta);
    root.appendChild(card);
  }

  if (!root.children.length){
    root.innerHTML = '<div style="padding:12px;opacity:.7">No cards match your filters.</div>';
  }
}


/* ===== Orchestration ===== */
async function run(){
  try {
    setStatus("Loading cards…");
    await loadCatalogue();      // fetches full catalogue
    setStatus("");              // clear status after catalogue ok

    await loadOwned();          // no-op if no ID typed
    render();                   // renders (dimmed by default)
  } catch (e) {
    fail(e?.message || e);
  }
}


/* ===== QS support (shareable links e.g. ?u=123&r=SR&club=Arsenal) ===== */
(function applyQS(){
  const qs = new URLSearchParams(location.search);
  const set = (id,key)=>{ if(qs.get(key)) $(id).value = qs.get(key); };
  set("userId","u"); set("rarity","r"); set("position","p"); set("batch","b");
  set("type","t");   set("club","club"); set("search","q"); set("sortBy","s");
  if (qs.get("missing")==="1") $("#missingOnly").checked = true;
})();

/* ===== Wire up ===== */
document.addEventListener("DOMContentLoaded", () => {
  $("#btnApply")?.addEventListener("click", run);

  $("#btnClear")?.addEventListener("click", () => {
    setVal("userId", "");
    setVal("search", "");
    setVal("club", "ALL");
    setVal("rarity", "ALL");
    setVal("position", "ALL");
    setVal("batch", "ALL");
    setVal("type", "player");
    setChecked("missingOnly", false);
    setVal("sortBy", "rarity");

    run();
  });

  // Live “owned overlay” update when typing Discord ID
  let ownedTimer;
  $("#userId")?.addEventListener("input", () => {
    clearTimeout(ownedTimer);
    ownedTimer = setTimeout(async () => {
      await loadOwned();   // no-op if empty; fetch counts if provided
      render();            // stays dimmed by default; lights owned when ID present
    }, 300);
  });

  run(); // initial load: shows all cards dimmed
});


</script>
</body>
</html>








