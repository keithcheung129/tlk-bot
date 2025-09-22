import os, aiohttp, asyncio, time, json
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# --- .env loading (robust for local + docker) ---
env_path = find_dotenv() or str(Path(__file__).with_name(".env"))
load_dotenv(env_path)
print("Loading .env from:", env_path or "(not found)")

# --- Discord setup ---
import discord
from discord import app_commands
from discord.ext import commands

RARITY_ORDER = {"N":0, "R":1, "AR":2, "SR":3, "SSR":4}

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Check your .env file and path.")

GID = int(os.getenv("GUILD_ID", "0"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
COMMAND_CHANNEL_ID = int(os.getenv("COMMAND_CHANNEL_ID", "0"))
HYPE_CHANNEL_ID = int(os.getenv("HYPE_CHANNEL_ID", "0"))

API_BASE = os.getenv("API_BASE")  # e.g. https://the-last-kick.example.workers.dev/api
API_SECRET = os.getenv("API_SECRET", "")  # same as Worker SCRIPT_SECRET
if not API_BASE:
    raise RuntimeError("API_BASE is missing. Set it to your Worker URL (include /api).")

CARD_BACK_URL = os.getenv("CARD_BACK_URL")  # optional

INTENTS = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=INTENTS)
bot.http_session = None

# --- Packs from env ---
def _load_pack_actions():
    """Env var PACK_ACTIONS should be a JSON object mapping visible pack name ➜ server action.
       Example: {"Base Pack":"open_base","Base":"open_base"} """
    raw = (os.getenv("PACK_ACTIONS", "") or "").strip()
    try:
        m = json.loads(raw) if raw else {}
        if isinstance(m, dict) and m:
            return {str(k): str(v) for k, v in m.items()}
    except Exception:
        pass
    return {"Base Pack": "open_base"}

PACK_ACTIONS = _load_pack_actions()
PACK_NAMES   = list(PACK_ACTIONS.keys())
print("PACK_ACTIONS =", PACK_ACTIONS)

# --- HTTP session ---
async def _ensure_session():
    if bot.http_session is None or bot.http_session.closed:
        bot.http_session = aiohttp.ClientSession()

# --- Guards ---
def in_command_channel(interaction: discord.Interaction) -> bool:
    return COMMAND_CHANNEL_ID == 0 or (interaction.channel and interaction.channel.id == COMMAND_CHANNEL_ID)

async def ensure_channel(interaction: discord.Interaction) -> bool:
    if in_command_channel(interaction):
        return True
    try:
        await interaction.response.send_message(f"Please use commands in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(f"Please use commands in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    return False

# --- API call helper ---
async def call_sheet(action: str, payload: dict):
    await _ensure_session()
    url = API_BASE.rstrip("/")
    data = {"action": action, **payload}
    headers = {"Content-Type": "application/json"}
    if API_SECRET:
        headers["X-API-Secret"] = API_SECRET

    async with bot.http_session.post(url, headers=headers, json=data) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"API {resp.status}: {text[:300]}")
        try:
            body = json.loads(text)
        except Exception:
            raise RuntimeError(f"API returned non-JSON: {text[:200]}")
        if isinstance(body, dict) and "ok" in body and "data" in body:
            if not body.get("ok", False):
                err = body.get("error") or body.get("data")
                raise RuntimeError(f"API error: {err}")
            return body.get("data", {})
        return body

# --- Sync + lifecycle ---
@bot.event
async def on_ready():
    try:
        if GID:
            synced_g = await bot.tree.sync(guild=discord.Object(id=GID))
            print("✅ Guild sync:", [c.name for c in synced_g], "to", GID)
        synced_glob = await bot.tree.sync()
        print("✅ Global sync (should be empty):", [c.name for c in synced_glob])
    except Exception as e:
        print("❌ Command sync error:", e)
    print(f"Logged in as {bot.user} ({bot.user.id})")

@bot.event
async def on_disconnect():
    print("⚠️  Discord gateway disconnected.")

@bot.event
async def on_resumed():
    print("🔄 Discord gateway session resumed.")

async def _graceful_close():
    if bot.http_session and not bot.http_session.closed:
        await bot.http_session.close()

# --- Autocomplete ---
async def _pack_autocomplete(_itx: discord.Interaction, current: str):
    q = (current or "").lower()
    out = [name for name in PACK_NAMES if q in name.lower()]
    return [app_commands.Choice(name=n, value=n) for n in out[:25]]

# --- Reveal UI ---
class RevealState(discord.ui.View):
    def __init__(self, pulls_sorted: list[dict], owner_id: int, pack_name: str, god: bool, best: dict | None):
        super().__init__(timeout=600)
        self.pulls_sorted = list(pulls_sorted)
        self.queue = list(pulls_sorted)
        self.owner_id = owner_id
        self.pack_name = pack_name
        self.god = god
        self.best = best or (pulls_sorted[-1] if pulls_sorted else None)
        self.total = len(pulls_sorted)
        self.revealed = 0
        self.done = False

    async def _post_summary(self, itx: discord.Interaction):
        rarity_em = {"N":"⚪","R":"🟦","AR":"🟪","SR":"🟧","SSR":"🟨"}
        lines = []
        for r in self.pulls_sorted:
            em = rarity_em.get(r.get("rarity",""), "📦")
            nm = r.get("name","(unknown)")
            rn = r.get("rarity","")
            sn = r.get("serial_no")
            lines.append(f"{em} **{nm}** [{rn}] " + (f"#**{sn}**" if sn else ""))
        desc = "\n".join(lines) if lines else "Pack complete!"
        emb = discord.Embed(
            title=f"{self.pack_name} — Results",
            description=desc,
            color=0xFFD166 if self.god else 0x57F287,
        )
        await itx.followup.send(embed=emb)

        try:
            if HYPE_CHANNEL_ID and (self.god or any(x.get("rarity") in ("SR", "SSR") for x in self.pulls_sorted)):
                chan = bot.get_channel(HYPE_CHANNEL_ID)
                if chan:
                    user = itx.user.mention
                    big = [x for x in self.pulls_sorted if x.get("rarity") in ("SR","SSR")]
                    if self.god:
                        await chan.send(f"{user} just pulled a **GOD PACK**!! 🎉🔥")
                    elif big:
                        # choose the best card to show in hype message
                        top = big[-1]
                        await chan.send(
                            f"{user} just pulled out a {top.get('rarity')} **{top.get('name')}**!!! Congrats!"
                        )
        except Exception:
            pass

        async def _maybe_hype(self, itx: discord.Interaction, card: dict):
            """Post a hype message to HYPE_CHANNEL_ID for SR/SSR or God Pack (once)."""
            # Channel configured?
            if not HYPE_CHANNEL_ID:
                return
            chan = bot.get_channel(HYPE_CHANNEL_ID)
            if not chan:
                return

            # God Pack? (announce once per session)
            try:
                if self.god and not getattr(self, "_hyped_god", False):
                    self._hyped_god = True
                    await chan.send(
                        f"💥 {itx.user.mention} just opened a **GOD PACK** in **{self.pack_name}**!!!"
                    )
                    # don't return; still allow individual SR/SSR hype too if you want
            except Exception:
                pass

            # Card-based hype (SR or above)
            rarity = (card.get("rarity") or "").upper()
            if rarity not in ("SR", "SSR"):
                return

            name = card.get("name") or "Unknown"
            try:
                msg = f"{itx.user.mention} just pulled out a **{rarity} {name}**!!! Congrats!"
                img = card.get("image_ref")
                if img:
                    emb = discord.Embed(color=0xFFD166 if rarity == "SSR" else 0xFFA654)
                    emb.set_image(url=img)
                    await chan.send(msg, embed=emb)
                else:
                    await chan.send(msg)
            except Exception:
                # Never let hype failures break the reveal flow.
                pass

    
    
    @discord.ui.button(label="Reveal Next", style=discord.ButtonStyle.primary)
    async def reveal_next(self, itx: discord.Interaction, _button: discord.ui.Button):
        if itx.user.id != self.owner_id:
            return await itx.response.send_message("Only the pack opener can use this.", ephemeral=True)
        await itx.response.defer(thinking=False)
        if self.done or not self.queue:
            try:
                await itx.message.edit(view=None)
            except Exception:
                pass
            return
        card = self.queue.pop(0)
        self.revealed += 1
        try:
            await itx.message.edit(view=None)
        except Exception:
            pass
        rarity_em = {"N":"⚪","R":"🟦","AR":"🟪","SR":"🟧","SSR":"🟨"}
        name   = card.get("name", "(unknown)")
        rarity = card.get("rarity", "")
        serial = card.get("serial_no")
        img    = card.get("image_ref")
        em     = rarity_em.get(rarity, "📦")
        color = 0x5865F2
        if rarity == "SR":  color = 0xFFA654
        if rarity == "SSR": color = 0xFFD166
        reveal_embed = discord.Embed(
            title=f"{em} {name} [{rarity}]" + (f"  •  #{serial}" if serial else ""),
            description=f"Card {self.revealed}/{self.total}",
            color=color,
        )
        if img:
            reveal_embed.set_image(url=img)
        await itx.message.edit(embed=reveal_embed, view=self) 
        if self.queue:
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        await itx.message.edit(view=self)
        await self._post_summary(itx)

    

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, itx: discord.Interaction, _button: discord.ui.Button):
        if itx.user.id != self.owner_id:
            return await itx.response.send_message("Only the pack opener can close this.", ephemeral=True)
        await itx.response.defer(thinking=False)
        self.done = True
        for child in self.children:
            child.disabled = True
        await itx.message.edit(view=self)
        await itx.followup.send("Session closed.")

# --- Reveal session helper ---

def _normalize_card(x: dict) -> dict:
    """Normalize to the keys RevealState expects."""
    return {
        "card_id":   x.get("card_id"),
        "name":      x.get("name") or x.get("player") or x.get("printcode") or "Unknown",
        "rarity":    x.get("rarity"),
        "serial_no": x.get("serial_no") or x.get("serial"),
        "image_ref": x.get("image_ref") or x.get("image_url"),
    }

async def start_reveal_session(
    interaction: discord.Interaction,
    pulls: list[dict],
    pack_name: str,
    *,
    god: bool = False,
):
    if not pulls:
        await interaction.followup.send("No results returned.", ephemeral=True)
        return

    pulls_norm = [_normalize_card(p) for p in pulls]
    pulls_sorted = sorted(pulls_norm, key=lambda r: RARITY_ORDER.get((r.get("rarity") or ""), -1))
    best = pulls_sorted[-1]

    await interaction.followup.send(f"🎴 **{pack_name}** for {interaction.user.mention} — let’s reveal here!")

    embed_back = discord.Embed(
        title=f"{pack_name} — Tap to reveal",
        description="We’ll flip 1-by-1. The last one is your best rarity. Use buttons below.",
        color=0x2B2D31,
    )
    if CARD_BACK_URL:
        embed_back.set_image(url=CARD_BACK_URL)

    view = RevealState(pulls_sorted, interaction.user.id, pack_name, god, best)
    await interaction.channel.send(embed=embed_back, view=view)

# --- Commands ---
@bot.tree.command(name="ping", description="Test command that replies immediately")
@app_commands.guilds(discord.Object(id=GID))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ✅", ephemeral=True)

@bot.tree.command(name="balance", description="Show your Tickets and Tokens")
@app_commands.guilds(discord.Object(id=GID))
async def balance(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    def to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0
    try:
        data = await call_sheet("collection", {
            "user_id": str(interaction.user.id),
            "page": 1,
            "page_size": 1,
            "unique_only": False,
            "rarity": "ALL",
            "position": "ALL",
            "batch": "ALL",
        })
        bal = (data or {}).get("balances") or {}
        tickets = to_int(bal.get("tickets", 0))
        tokens_ = to_int(bal.get("tokens", 0))
        await interaction.followup.send(
            f"🎟️ Tickets: **{tickets}**\n🪙 Tokens: **{tokens_}**",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)

@bot.tree.command(name="last_pack", description="Show your most recent pack (no cost)")
@app_commands.guilds(discord.Object(id=GID))
async def last_pack(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    PACK_SIZE = 5
    try:
        res = await call_sheet("collection", {
            "user_id": str(interaction.user.id),
            "page": 1,
            "page_size": 50,
            "unique_only": False,
            "rarity": "ALL",
            "position": "ALL",
            "batch": "ALL",
        })
        items = (res or {}).get("items") or []
        if not items:
            await interaction.followup.send("No recent cards found.", ephemeral=True)
            return
        def ts(x):
            v = x.get("acquired_ts") or x.get("ts") or 0
            try: return int(v)
            except: return 0
        key = "draw_id" if any("draw_id" in i for i in items) else None
        if not key and any("commit" in i for i in items):
            key = "commit"
        pulled = None
        if key:
            groups = {}
            for it in items:
                k = it.get(key)
                if not k: continue
                groups.setdefault(k, []).append(it)
            if groups:
                last_key = max(groups.keys(), key=lambda k: max(ts(x) for x in groups[k]))
                pulled = sorted(groups[last_key], key=ts, reverse=False)[:PACK_SIZE]
        if not pulled:
            pulled = sorted(items, key=ts, reverse=True)[:PACK_SIZE]
        lines = []
        for i, it in enumerate(pulled, 1):
            name   = it.get("name") or it.get("player") or it.get("printcode") or it.get("card_id") or "Unknown"
            rarity = it.get("rarity") or "—"
            club   = it.get("club") or it.get("Club") or ""
            pos    = it.get("position") or ""
            serial = f" #{it['serial']}" if it.get("serial") else (f" #{it['serial_no']}" if it.get("serial_no") else "")
            bits   = [rarity, club, pos]
            lines.append(f"{i}. **{name}** · {' • '.join([b for b in bits if b])}{serial}")
        emb = discord.Embed(
            title="Your most recent pack",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=emb, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)

@bot.tree.command(description="Sell one duplicate of a specific card_id (keeps your first copy).")
@app_commands.guilds(discord.Object(id=GID))
@app_commands.describe(card_id="Exact card_id from the card list (e.g., PLR123)")
async def sell(interaction: discord.Interaction, card_id: str):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        res = await call_sheet("sell", {"user_id": str(interaction.user.id), "card_id": card_id})
        gained = res.get("tokens_gained", 0)
        bal = res.get("balance", 0)
        rarity = res.get("rarity", "?")
        serial = res.get("sold_serial")
        await interaction.followup.send(
            f"Sold duplicate **{card_id}** [{rarity}] (serial #{serial}) → +**{gained}** 🔑  | New balance: **{bal}**",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(description="Sell all duplicates (keeps 1 of each).")
@app_commands.guilds(discord.Object(id=GID))
async def sell_all_dupes(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        res = await call_sheet("sell_all_dupes", {"user_id": str(interaction.user.id)})
        sold = res.get("sold_count", 0)
        gained = res.get("tokens_gained", 0)
        bal = res.get("balance", 0)
        await interaction.followup.send(
            f"Sold **{sold}** duplicates → +**{gained}** 🔑  | New balance: **{bal}**",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# --- /open (with pack options + timeout recovery) ---
@bot.tree.command(name="open", description="Open a pack")
@app_commands.guilds(discord.Object(id=GID))
@app_commands.describe(pack="Which pack to open")
@app_commands.autocomplete(pack=_pack_autocomplete)
async def open_pack(interaction: discord.Interaction, pack: str = "Base Pack"):
    if not await ensure_channel(interaction):
        return
    await interaction.response.defer(thinking=True)

    user_id   = str(interaction.user.id)
    PACK_SIZE = 5
    started_ms = int(time.time() * 1000)

    action = PACK_ACTIONS.get(pack) or "open_base"

    def _extract(res):
        body = res.get("data", res) if isinstance(res, dict) else res
        if isinstance(body, dict) and body.get("error"):
            raise RuntimeError(str(body["error"]))
        raw = []
        if isinstance(body, dict):
            raw = body.get("results") or body.get("pulls") or body.get("cards") or body.get("items") or []
        return [_normalize_card(x) for x in raw], (body if isinstance(body, dict) else {})

    async def _recover_from_collection():
        col = await call_sheet("collection", {
            "user_id": user_id,
            "page": 1,
            "page_size": PACK_SIZE * 2,
            "unique_only": False,
            "rarity": "ALL", "position": "ALL", "batch": "ALL",
        })
        items = (col or {}).get("items") or []
        def ts(it):
            try: return int(it.get("acquired_ts") or it.get("ts") or 0)
            except: return 0
        recent = [it for it in items if ts(it) >= started_ms - 200000]
        pool = recent[:PACK_SIZE] or items[:PACK_SIZE]
        return [_normalize_card(it) for it in pool]

    try:
        res = await call_sheet(action, {"user_id": user_id})
        cards, body = _extract(res)
        if cards:
            pack_name = body.get("pack_name") or pack
            await start_reveal_session(
                interaction,
                cards,
                pack_name=pack_name,
                god=bool(body.get("godPack")),
            )
            return
        recovered = await _recover_from_collection()
        if recovered:
            await start_reveal_session(
                interaction,
                recovered,
                pack_name=f"Recovered — {pack}",
                god=False,
            )
        else:
            await interaction.followup.send("⚠️ Pack did not open (no new cards). Please try again.", ephemeral=True)
    except Exception as e:
        msg = str(e)
        if any(x in msg.lower() for x in ("upstream_timeout", "502", "bad gateway", "timeout")):
            try:
                recovered = await _recover_from_collection()
                if recovered:
                    await start_reveal_session(
                        interaction,
                        recovered,
                        pack_name=f"Recovered — {pack}",
                        god=False,
                    )
                    return
            except Exception as e2:
                msg += f" | recovery: {e2}"
        await interaction.followup.send(f"⚠️ Error opening pack: {msg}", ephemeral=True)

# --- Starter ---
@bot.tree.command(name="starter", description="Claim your one-time Starter Pack and reveal it (worst → best).")
@app_commands.guilds(discord.Object(id=GID))
async def starter(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer()
    try:
        res = await call_sheet("starter", {"user_id": str(interaction.user.id)})
        body = res if isinstance(res, dict) else {}
        raw = body.get("results") or body.get("pulls") or body.get("cards") or body.get("items") or []
        cards = [_normalize_card(x) for x in raw]
        await start_reveal_session(
            interaction,
            cards,
            pack_name=body.get("pack_name") or "Starter Pack",
            god=bool(body.get("godPack")),
        )
    except Exception as e:
        msg = str(e)
        if "starter" in msg.lower() or "claimed" in msg.lower():
            await interaction.followup.send("You’ve already claimed your Starter Pack.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

# --- Admin grant ---
@bot.tree.command(name="grant", description="Admin: grant tickets to a user.")
@app_commands.guilds(discord.Object(id=GID))
@app_commands.describe(user="Target user", amount="Number of tickets", reason="Reason for the grant")
async def grant(interaction: discord.Interaction, user: discord.User, amount: int, reason: str = "admin grant"):
    if not await ensure_channel(interaction): return
    if interaction.user.id != ADMIN_USER_ID:
        await interaction.response.send_message("Only the game admin can use this.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        data = await call_sheet("grant", {"user_id": str(user.id), "amount": amount, "reason": reason})
        await interaction.followup.send(
            f"Granted **{amount}** to {user.mention}. New balance: **{data.get('balance',0)}**",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# --- Collection ---
RARITY_CHOICES = [app_commands.Choice(name=x, value=x) for x in ["ALL","N","R","AR","SR","SSR"]]
POSITION_CHOICES = [app_commands.Choice(name=x, value=x) for x in [
    "ALL","GK","ST","LW","RW","AM","CM","DM","LB","RB","CB"
]]
BATCH_CHOICES = [app_commands.Choice(name=x, value=x) for x in ["ALL","Base","Base U"]]

@bot.tree.command(name="collection", description="View your collection as an image gallery (10 per page).")
@app_commands.guilds(discord.Object(id=GID))
@app_commands.describe(page="Page number (starts at 1)")
@app_commands.choices(rarity=RARITY_CHOICES, position=POSITION_CHOICES, batch=BATCH_CHOICES)
async def collection(
    interaction: discord.Interaction,
    page: int = 1,
    rarity: app_commands.Choice[str] | None = None,
    position: app_commands.Choice[str] | None = None,
    batch: app_commands.Choice[str] | None = None,
    unique_only: bool = False,
):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer()
    try:
        filt = {
            "user_id": str(interaction.user.id),
            "page": max(1, page),
            "page_size": 10,
            "unique_only": bool(unique_only),
            "rarity": (rarity.value if rarity else "ALL"),
            "position": (position.value if position else "ALL"),
            "batch": (batch.value if batch else "ALL"),
        }
        data = await call_sheet("collection", filt)
        items: list[dict] = data.get("items", [])
        counts = data.get("counts", {})
        total = data.get("total", len(items))
        page_num = data.get("page", page)
        summary = " | ".join([f"{k}: {v}" for k, v in counts.items()]) if counts else ""
        emb = discord.Embed(
            title=f"{interaction.user.display_name} — Collection",
            description=(f"{summary}\nFilters: R={filt['rarity']} • Pos={filt['position']} • Batch={filt['batch']}"
                         + (" • Unique only" if unique_only else "")),
            color=0x2B2D31,
        )
        emb.set_footer(text=f"Page {page_num} • Showing {len(items)} of {total}")
        for i, it in enumerate(items[:10], start=1):
            nm = it.get("name","(unknown)")
            rn = it.get("rarity","")
            sn = it.get("serial_no")
            emb.add_field(name=f"{i}. {nm} [{rn}] " + (f"#{sn}" if sn else ""), value=it.get("card_id",""), inline=False)
        await interaction.followup.send(embed=emb)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# --- Utility ---
@bot.tree.command(name="whoami", description="Show your Discord user ID.")
@app_commands.guilds(discord.Object(id=GID))
async def whoami(interaction: discord.Interaction):
    if not await ensure_channel(interaction): return
    await interaction.response.send_message(f"Your ID: `{interaction.user.id}`", ephemeral=True)

@bot.tree.command(name="resync", description="Admin: resync app commands")
@app_commands.guilds(discord.Object(id=GID))
async def resync(interaction: discord.Interaction):
    if str(interaction.user.id) != os.getenv("ADMIN_USER_ID", ""):
        return await interaction.response.send_message("Nope.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    gid = int(os.getenv("GUILD_ID","0"))
    guild = discord.Object(id=gid) if gid else None
    synced = await bot.tree.sync(guild=guild) if guild else await bot.tree.sync()
    await interaction.followup.send(f"Synced: {', '.join(c.name for c in synced)}", ephemeral=True)

# --- Error handler ---
@bot.tree.error
async def on_app_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        msg = str(getattr(error, "original", error))
        await interaction.response.send_message(f"⚠️ Oops: {msg}", ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(f"⚠️ Oops: {error}", ephemeral=True)
    print("App command error:", repr(error))

# --- Main ---
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    finally:
        asyncio.run(_graceful_close())
