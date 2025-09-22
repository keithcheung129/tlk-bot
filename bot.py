import os, aiohttp, asyncio

from dotenv import load_dotenv, find_dotenv
from pathlib import Path

env_path = find_dotenv()
if not env_path:
    env_path = str(Path(__file__).with_name(".env"))

load_dotenv(env_path)
print("Loading .env from:", env_path or "(not found)")




load_dotenv(find_dotenv(), override=True)
env_path = find_dotenv()

import time
import json  # add this if not present
import discord
from discord import app_commands
from discord.ext import commands

GUILD_ID = 740430544273145876  # <-- replace with your server ID



TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Check your .env file and path.")

CLIENT_ID = os.getenv("CLIENT_ID")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
COMMAND_CHANNEL_ID = int(os.getenv("COMMAND_CHANNEL_ID", "0"))
HYPE_CHANNEL_ID = int(os.getenv("HYPE_CHANNEL_ID", "0"))


API_BASE = os.getenv("API_BASE")  # e.g. https://the-last-kick.keithcheung129.workers.dev/api
API_SECRET = os.getenv("API_SECRET", "")  # same as Worker SCRIPT_SECRET

if not API_BASE:
    raise RuntimeError("API_BASE is missing. Set it to your Worker URL (include /api).")

CARD_BACK_URL = os.getenv("CARD_BACK_URL")  # optional


RARITY_ORDER = {"N":0, "R":1, "AR":2, "SR":3, "SSR":4}

INTENTS = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=INTENTS)
bot.http_session = None



# ---- Pack registry (read from env so you can add packs later without code changes)
def _load_pack_actions():
    raw = os.getenv("PACK_ACTIONS", "").strip()
    try:
        m = json.loads(raw) if raw else {}
        if isinstance(m, dict) and m:
            # normalize to { DisplayName: action_name }
            return {str(k): str(v) for k, v in m.items()}
    except Exception:
        pass
    # sensible defaults
    default = os.getenv("OPEN_ACTION") or "open_base"  # your current Base pack
    return {"Base": default}

PACK_ACTIONS = _load_pack_actions()
PACK_NAMES   = list(PACK_ACTIONS.keys())
print("PACK_ACTIONS =", PACK_ACTIONS)  # shows in Railway logs on boot

# Autocomplete for /open pack=
from discord import app_commands
async def _pack_autocomplete(_itx: discord.Interaction, current: str):
    q = (current or "").lower()
    out = [name for name in PACK_NAMES if q in name.lower()]
    return [app_commands.Choice(name=n, value=n) for n in out[:25]]



async def _ensure_session():
    if bot.http_session is None or bot.http_session.closed:
        bot.http_session = aiohttp.ClientSession()

def in_command_channel(interaction: discord.Interaction) -> bool:
    return COMMAND_CHANNEL_ID == 0 or (interaction.channel and interaction.channel.id == COMMAND_CHANNEL_ID)

async def call_sheet(action: str, payload: dict):
    await _ensure_session()

    url = API_BASE.rstrip("/")  # Worker accepts "/" or "/api" — pass your full URL with /api
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

        # Worker always returns an envelope: { ok, data, status }.
        if isinstance(body, dict) and "ok" in body and "data" in body:
            if not body.get("ok", False):
                err = body.get("error") or body.get("data")
                raise RuntimeError(f"API error: {err}")
            return body.get("data", {})

        # Legacy shape (if you ever hit Apps Script directly)
        return body




@bot.event
async def on_ready():
    gid = int(os.getenv("GUILD_ID", "0"))
    try:
        if gid:
            guild = discord.Object(id=gid)
            synced = await bot.tree.sync(guild=guild)
            print(f"✅ Synced {[c.name for c in synced]} to guild {gid}")
        else:
            synced = await bot.tree.sync()
            print(f"✅ Synced globally: {[c.name for c in synced]}")
    except Exception as e:
        print("❌ Command sync error:", e)
    print(f"Logged in as {bot.user} ({bot.user.id})")



@bot.event
async def on_disconnect():
    # just a log point; the session persists
    print("⚠️  Discord gateway disconnected.")

@bot.event
async def on_resumed():
    print("🔄 Discord gateway session resumed.")

async def _graceful_close():
    if bot.http_session and not bot.http_session.closed:
        await bot.http_session.close()



# --------- Guards ---------
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


def admin_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ADMIN_USER_ID



@bot.tree.command(name="ping", description="Test command that replies immediately")
@app_commands.guilds(discord.Object(id=int(os.getenv("GUILD_ID", "0"))))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong ✅", ephemeral=True)




# --------- Helper of revealing options -----------
class RevealState(discord.ui.View):
    def __init__(self, pulls_sorted: list[dict], owner_id: int, pack_name: str, god: bool, best: dict):
        super().__init__(timeout=600)  # 10 minutes
        self.pulls_sorted = list(pulls_sorted)   # full list (for summary)        
        self.queue = list(pulls_sorted)  # reveal worst ➜ best; best is last
        self.owner_id = owner_id
        self.pack_name = pack_name
        self.god = god
        self.best = best
        self.total = len(pulls_sorted)
        self.revealed = 0
        self.done = False

    async def _post_next(self, itx: discord.Interaction):
        if self.done or not self.queue:
            return await itx.response.defer()
        card = self.queue.pop(0)
        self.revealed += 1

        name = card.get("name", "(unknown)")
        rarity = card.get("rarity", "")
        serial = card.get("serial_no")
        img = card.get("image_ref")
        em = {"N":"⚪","R":"🟦","AR":"🟪","SR":"🟧","SSR":"🟨"}.get(rarity, "📦")
        color = 0x5865F2
        if rarity == "SR": color = 0xFFA654
        if rarity == "SSR": color = 0xFFD166

        embed = discord.Embed(
            title=f"{em} {name} [{rarity}]" + (f"  •  #{serial}" if serial else ""),
            description=f"Card {self.revealed}/{self.total}",
            color=color
        )
        if img:
            embed.set_image(url=img)

        await itx.followup.send(embed=embed)

        if not self.queue:
            # last reveal just happened (the best)
            self.done = True
            for child in self.children:
                child.disabled = True
            await itx.message.edit(view=self)
            await self._post_summary(itx)

    async def _post_all(self, itx: discord.Interaction):
        await itx.response.defer()
        while self.queue and not self.done:
            # reveal remaining quickly
            # use channel sends; avoid hammering edits
            # small delay for pacing
            dummy = itx  # we’re using channel sends, so we can reuse the interaction
            await self._post_next(dummy)
            await asyncio.sleep(0.35)

    async def _post_summary(self, itx: discord.Interaction):
        # Compose and post the pack results summary
        lines = []
        rarity_em = {"N":"⚪","R":"🟦","AR":"🟪","SR":"🟧","SSR":"🟨"}
        
        # If you kept your pulls list outside, you can pass it into the class as needed.
        # Easiest: store the full sorted list on init:
        #   self.pulls_sorted = pulls_sorted
        # Then build lines from self.pulls_sorted:
        lines = []
        for r in getattr(self, "pulls_sorted", []):
            em = rarity_em.get(r.get("rarity",""), "📦")
            nm = r.get("name","(unknown)")
            rn = r.get("rarity","")
            sn = r.get("serial_no")
            lines.append(f"{em} **{nm}** [{rn}] " + (f"#**{sn}**" if sn else ""))

        # If you didn’t store pulls_sorted, quick workaround:
        #   Just skip the detailed list or pass it when constructing the view.

        if not lines and hasattr(self, "pulls_sorted"):
            pass  # no-op; lines already built
        desc = "\n".join(lines) if lines else "Pack complete!"

        emb = discord.Embed(
            title=f"{self.pack_name} — Results",
            description=desc,
            color=0xFFD166 if self.god else 0x57F287
        )
        await itx.followup.send(embed=emb)

        # Optional hype channel post if SSR or God Pack
        try:
            if HYPE_CHANNEL_ID and (self.god or any(x.get("rarity")=="SSR" for x in self.pulls_sorted)):
                chan = bot.get_channel(HYPE_CHANNEL_ID)
                if chan:
                    hype = discord.Embed(
                        title="HUGE PULL!",
                        description=f"{itx.user.mention} just opened **{self.pack_name}** and hit "
                                    + ("a **GOD PACK**!" if self.god else "an **SSR**!"),
                        color=0xFFD166
                    )
                    if self.best and self.best.get("image_ref"):
                        hype.set_image(url=self.best["image_ref"])
                    await chan.send(embed=hype)
        except Exception:
            pass

    # ---- Buttons ----
    @discord.ui.button(label="Reveal Next", style=discord.ButtonStyle.primary)
    async def reveal_next(self, itx: discord.Interaction, button: discord.ui.Button):
        if itx.user.id != self.owner_id:
            return await itx.response.send_message("Only the pack opener can use this.", ephemeral=True)

        await itx.response.defer(thinking=False)

        # nothing left? just tidy up the old panel
        if self.done or not self.queue:
            try:
                await itx.message.edit(view=None)
            except Exception:
                pass
            return

        # take next card (worst → best; best was placed last when building pulls_sorted)
        card = self.queue.pop(0)
        self.revealed += 1

        # disable the old controls so users don't keep clicking a stale panel
        try:
            await itx.message.edit(view=None)
        except Exception:
            pass

        # build the reveal embed
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
            color=color
        )
        if img:
            reveal_embed.set_image(url=img)

        # send the revealed card
        await itx.message.edit(embed=reveal_embed, view=self)

        # continue revealing via buttons if queue remains; otherwise finish
        if self.queue:
            return

        self.done = True
        for child in self.children:
            child.disabled = True
        await itx.message.edit(view=self)
        await self._post_summary(itx)




    @discord.ui.button(label="Reveal All", style=discord.ButtonStyle.secondary)
    async def reveal_all(self, itx: discord.Interaction, button: discord.ui.Button):
        # Owner gate
        if itx.user.id != self.owner_id:
            return await itx.response.send_message("Only the pack opener can use this.", ephemeral=True)

        # 1) Acknowledge to avoid the red banner
        await itx.response.defer(thinking=False)

        # 2) If already finished or nothing left, just tidy up the panel
        if self.done or not self.queue:
            try:
                await itx.message.edit(view=None)
            except Exception:
                pass
            return

        # 3) Disable the old controls so users don't click stale buttons
        try:
            await itx.message.edit(view=None)
        except Exception:
            pass

        # 4) Stream all remaining reveals at the bottom (no extra panels needed)
        rarity_em = {"N":"⚪","R":"🟦","AR":"🟪","SR":"🟧","SSR":"🟨"}
        while self.queue and not self.done:
            card = self.queue.pop(0)
            self.revealed += 1

            name = card.get("name", "(unknown)")
            rarity = card.get("rarity", "")
            serial = card.get("serial_no")
            img = card.get("image_ref")
            em = rarity_em.get(rarity, "📦")

            color = 0x5865F2
            if rarity == "SR":  color = 0xFFA654
            if rarity == "SSR": color = 0xFFD166

            embed = discord.Embed(
                title=f"{em} {name} [{rarity}]" + (f"  •  #{serial}" if serial else ""),
                description=f"Card {self.revealed}/{self.total}",
                color=color
            )
            if img:
                embed.set_image(url=img)

            await itx.followup.send(embed=embed)

            # Small pacing so it doesn't dump all at once (tweak or remove as you like)
            await asyncio.sleep(0.3)

        # 5) Mark done and post the summary
        self.done = True
        await self._post_summary(itx)

  

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, itx: discord.Interaction, button: discord.ui.Button):
        if itx.user.id != self.owner_id:
            return await itx.response.send_message("Only the pack opener can close this.", ephemeral=True)
        await itx.response.defer(thinking=False)
        self.done = True
        for child in self.children:
            child.disabled = True
        await itx.message.edit(view=self)
        await itx.followup.send("Session closed.")





# --------- Commands ---------
@bot.tree.command(name="balance", description="Show your Tickets and Tokens")
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
        # Use 'collection' because it returns both ticket & token balances
        data = await call_sheet("collection", {
            "user_id": str(interaction.user.id),
            "page": 1,           # small slice so it's light
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
@app_commands.guilds(discord.Object(id=int(os.getenv("GUILD_ID", "0"))))
async def last_pack(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    PACK_SIZE = 5
    try:
        res = await call_sheet("collection", {
            "user_id": str(interaction.user.id),
            "page": 1,
            "page_size": PACK_SIZE,
            "unique_only": False,
            "rarity": "ALL",
            "position": "ALL",
            "batch": "ALL",
        })
        items = (res or {}).get("items") or []
        pulled = items[:PACK_SIZE]
        if not pulled:
            await interaction.followup.send("No recent cards found.", ephemeral=True)
            return

        lines = []
        for i, it in enumerate(pulled, 1):
            name = it.get("name") or it.get("player") or it.get("printcode") or it.get("card_id") or "Unknown"
            rarity = it.get("rarity") or "—"
            club = it.get("club") or it.get("Club") or ""
            pos = it.get("position") or ""
            serial = f" #{it['serial']}" if it.get("serial") else ""
            bits = [rarity, club, pos]
            bits = [b for b in bits if b]
            lines.append(f"{i}. **{name}** · {' • '.join(bits)}{serial}")

        emb = discord.Embed(title="Your most recent pack",
                            description="\n".join(lines),
                            color=discord.Color.gold())
        await interaction.followup.send(embed=emb, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)





@bot.tree.command(description="Sell one duplicate of a specific card_id (keeps your first copy).")
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
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(description="Sell all duplicates (keeps 1 of each).")
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
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)






#--------card revealing orders and clicks
async def start_reveal_session(interaction: discord.Interaction, res: dict, pack_name: str):
    pulls = res.get("results", [])
    if not pulls:
        await interaction.followup.send("No results returned. (Check your starter settings.)", ephemeral=True)
        return

    # Sort worst ➜ best (best last)
    pulls_sorted = sorted(pulls, key=lambda r: RARITY_ORDER.get((r.get("rarity") or ""), -1))
    best = pulls_sorted[-1]
    god = res.get("godPack", False)


    await interaction.followup.send(
        f"🎴 **{pack_name}** for {interaction.user.mention} — let’s reveal here!"
    )

    # Card back message
    embed_back = discord.Embed(
        title=f"{pack_name} — Tap to reveal",
        description="We’ll flip 1-by-1. The last one is your best rarity. Use buttons below.",
        color=0x2B2D31
    )
    if CARD_BACK_URL:
        embed_back.set_image(url=CARD_BACK_URL)

    msg = await interaction.channel.send(embed=embed_back)

    # Reuse the same RevealState view class you already use in /open:
    # If you defined it inside /open, move that class to top-level so both can import it.
    view = RevealState(pulls_sorted, interaction.user.id, pack_name, god, best)
    msg = await interaction.channel.send(embed=embed_back, view=view)


@bot.tree.command(name="open", description="Open a pack")
@app_commands.guilds(discord.Object(id=int(os.getenv("GUILD_ID", "0"))))
@app_commands.describe(pack="Which pack to open")
@app_commands.autocomplete(pack=_pack_autocomplete)
async def open_pack(interaction: discord.Interaction, pack: str = "Base"):
    if not await ensure_channel(interaction):
        return

    await interaction.response.defer(thinking=True)

    user_id   = str(interaction.user.id)
    PACK_SIZE = 5   # adjust if your packs are a different size
    started   = int(time.time() * 1000)

    # resolve the Apps Script action for this pack (e.g., "open_base")
    action = PACK_ACTIONS.get(pack)
    if not action:
        # derive: "My New Pack" -> "open_my_new_pack"
        action = "open_" + pack.lower().replace(" ", "_")

    def _extract(res):
        body = res.get("data", res) if isinstance(res, dict) else res
        if isinstance(body, dict) and body.get("error"):
            raise RuntimeError(str(body["error"]))
        pulls = []
        if isinstance(body, dict):
            pulls = body.get("pulls") or body.get("cards") or body.get("items") or []
        return pulls, (body if isinstance(body, dict) else {})

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
        recent = [it for it in items if ts(it) >= started - 120000]
        return recent[:PACK_SIZE]

    try:
        res = await call_sheet(action, {"user_id": user_id})
        pulls, body = _extract(res)
        if pulls:
            pack_name = body.get("pack_name") or pack
            await start_reveal_session(interaction, pulls, pack_name=pack_name, god=None, best=None)
            return

        # nothing returned → see if anything minted; if not, tell user cleanly
        recovered = await _recover_from_collection()
        if recovered:
            await start_reveal_session(interaction, recovered, pack_name=f"Recovered {pack}", god=None, best=None)
        else:
            await interaction.followup.send("⚠️ Pack did not open (no new cards). Please try again.", ephemeral=True)

    except Exception as e:
        msg = str(e)
        # timeouts or gateway issues → try recovery then surface error
        if any(x in msg.lower() for x in ("upstream_timeout", "502", "bad gateway", "timeout")):
            try:
                recovered = await _recover_from_collection()
                if recovered:
                    await start_reveal_session(interaction, recovered, pack_name=f"Recovered {pack}", god=None, best=None)
                    return
            except Exception as e2:
                msg += f" | recovery: {e2}"
        # unknown action? point user/admin at available packs
        if "unknown action" in msg.lower():
            opts = ", ".join(PACK_NAMES) or "Base"
            msg += f" (available packs: {opts})"
        await interaction.followup.send(f"⚠️ Error opening pack: {msg}", ephemeral=True)






@bot.tree.command(description="Claim your one-time Starter Pack and reveal it (worst → best).")
async def starter(interaction: discord.Interaction):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)
    await interaction.response.defer()
    try:
        res = await call_sheet("starter", {"user_id": str(interaction.user.id)})
        # If the API throws an error because it’s already claimed, your call_sheet will raise.
        await start_reveal_session(interaction, res, "Starter Pack (30)")
    except Exception as e:
        # Friendly message if already claimed
        msg = str(e)
        if "starter" in msg.lower() or "claimed" in msg.lower():
            await interaction.followup.send("You’ve already claimed your Starter Pack.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)



@bot.tree.command(description="Admin: grant tickets to a user.")
@app_commands.describe(user="Target user", amount="Number of tickets", reason="Reason for the grant")
async def grant(interaction: discord.Interaction, user: discord.User, amount: int, reason: str = "admin grant"):
    if not await ensure_channel(interaction): return
    if not admin_only(interaction):
        await interaction.response.send_message("Only the game admin can use this.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        data = await call_sheet("grant", {"user_id": str(user.id), "amount": amount, "reason": reason})
        await interaction.followup.send(f"Granted **{amount}** to {user.mention}. New balance: **{data.get('balance',0)}**", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


RARITY_CHOICES = [app_commands.Choice(name=x, value=x) for x in ["ALL","N","R","AR","SR","SSR"]]
POSITION_CHOICES = [app_commands.Choice(name=x, value=x) for x in
    ["ALL","GK","ST","LW","RW","AM","CM","DM","LB","RB","CB"]]
BATCH_CHOICES = [app_commands.Choice(name=x, value=x) for x in ["ALL","Base","Base U"]]

@bot.tree.command(description="View your collection as an image gallery (10 per page).")
@app_commands.describe(page="Page number (starts at 1)")
@app_commands.choices(rarity=RARITY_CHOICES, position=POSITION_CHOICES, batch=BATCH_CHOICES)
async def collection(
    interaction: discord.Interaction,
    page: int = 1,
    rarity: app_commands.Choice[str] = None,
    position: app_commands.Choice[str] = None,
    batch: app_commands.Choice[str] = None,
    unique_only: bool = False
):
    if not await ensure_channel(interaction):
        return await interaction.response.send_message(f"Use this in <#{COMMAND_CHANNEL_ID}>.", ephemeral=True)

    # NOTE: attachments are not allowed in ephemeral messages, so this is public.
    await interaction.response.defer()

    try:
        # ask server for filtered/paged slice (if your API supports it)
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

        items: list[dict] = data.get("items", [])  # expect only current page (10 max)
        counts = data.get("counts", {})            # N/R/AR/SR/SSR totals (active only)
        total = data.get("total", len(items))      # if your API gives total with filters
        page_num = data.get("page", page)
        page_size = data.get("page_size", 10)

        # compose embed
        summary = " | ".join([f"{k}: {v}" for k, v in counts.items()]) if counts else ""
        emb = discord.Embed(
            title=f"{interaction.user.display_name} — Collection",
            description=(f"{summary}\nFilters: R={filt['rarity']} • Pos={filt['position']} • Batch={filt['batch']}"
                         + (" • Unique only" if unique_only else "")),
            color=0x2B2D31
        )
        emb.set_footer(text=f"Page {page_num} • Showing {len(items)} of {total}")

        files = []
        # Up to 10 images (Discord limit per message)
        for i, it in enumerate(items[:10], start=1):
            url = it.get("image_ref")
            nm = it.get("name","(unknown)")
            rn = it.get("rarity","")
            sn = it.get("serial_no")
            emb.add_field(name=f"{i}. {nm} [{rn}] " + (f"#{sn}" if sn else ""), value=it.get("card_id",""), inline=False)
            if url:
                # we can just set URLs as embed images OR attach; here we attach for reliability
                # downloading and attaching would require requests get & BytesIO; to keep it simple,
                # we’ll rely on Discord to unfurl links (most hosts allow it). So we skip attachments here.
                pass

        await interaction.followup.send(embed=emb)
        # (Optional later) If you want to attach actual image files, we can add a small fetch-and-attach helper.

    except Exception as e:
        await interaction.followup.send(f"Error: {e}")



@bot.tree.command(description="Show your Discord user ID.")
async def whoami(interaction: discord.Interaction):
    if not await ensure_channel(interaction): return
    await interaction.response.send_message(f"Your ID: `{interaction.user.id}`", ephemeral=True)


@bot.tree.command(name="resync", description="Admin: resync app commands")
@app_commands.guilds(discord.Object(id=int(os.getenv("GUILD_ID","0"))))
async def resync(interaction: discord.Interaction):
    if str(interaction.user.id) != os.getenv("ADMIN_USER_ID", ""):
        return await interaction.response.send_message("Nope.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    gid = int(os.getenv("GUILD_ID","0"))
    guild = discord.Object(id=gid) if gid else None
    synced = await bot.tree.sync(guild=guild) if guild else await bot.tree.sync()
    await interaction.followup.send(f"Synced: {', '.join(c.name for c in synced)}", ephemeral=True)




@bot.tree.error
async def on_app_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        # surface a clean message to the user
        msg = str(getattr(error, "original", error))
        await interaction.response.send_message(f"⚠️ Oops: {msg}", ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(f"⚠️ Oops: {error}", ephemeral=True)
    # server logs
    print("App command error:", repr(error))





if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    finally:
        asyncio.run(_graceful_close())

