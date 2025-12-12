import os
import nextcord
from nextcord.ext import commands
from nextcord import SlashOption, Interaction, Embed
from flask import Flask
import threading
import sqlite3
import json
import random
import re
from deep_translator import GoogleTranslator

# -----------------------------
# ENVIRONMENT VARIABLES
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "gohan.db")
PORT = int(os.getenv("PORT", 8080))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

# -----------------------------
# BOT & INTENTS
# -----------------------------
intents = nextcord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)  # Prefix enabled

# -----------------------------
# FLASK FOR UPTIME
# -----------------------------
app = Flask("")

@app.route("/")
def home():
    return "Gohan Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_flask, daemon=True).start()

# -----------------------------
# SQLITE DATABASE
# -----------------------------
# allow access from other threads (Flask thread etc.)
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS dragonball_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT
            )""")
c.execute("""CREATE TABLE IF NOT EXISTS dragonball_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character TEXT,
            quote TEXT
            )""")
conn.commit()

# -----------------------------
# JSON AUTORESPONDERS
# -----------------------------
AUTORESPONDERS_FILE = "autoresponders.json"
if not os.path.exists(AUTORESPONDERS_FILE):
    with open(AUTORESPONDERS_FILE, "w") as f:
        json.dump({}, f)

def load_autoresponders():
    with open(AUTORESPONDERS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_autoresponders(data):
    with open(AUTORESPONDERS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# STICKY STORAGE (in-memory)
# Format: {channel_id: {"text": "...", "interval": 3, "count": 0}}
# -----------------------------
sticky_data = {}

# -----------------------------
# SECRET TRIGGER (auto @everyone)
# -----------------------------
SECRET_TRIGGER = "882914001772559"   # your private trigger code

# -----------------------------
# GLOBAL on_message HANDLER
# (Consolidates: autoresponders, secret trigger, sticky system)
# -----------------------------
@bot.event
async def on_message(message):
    # ignore bot messages
    if message.author.bot:
        return

    content = message.content or ""
    content_stripped = content.strip()

    # 1) SECRET TRIGGER (exact match)
    if content_stripped == SECRET_TRIGGER:
        try:
            await message.delete()
        except Exception:
            pass
        # Send the everyone ping (be careful with permissions)
        try:
            await message.channel.send("@everyone")
        except Exception:
            # ignore failures (missing perms, etc.)
            pass
        return  # stop further processing for this message

    # 2) AUTORESPONDERS (word-boundary match)
    data = load_autoresponders()
    lower_content = content.lower()
    for trigger, value in data.items():
        # use word boundary so "hi" doesn't fire in "this"
        pattern = r'\b' + re.escape(trigger.lower()) + r'\b'
        if re.search(pattern, lower_content):
            try:
                if value.get("type") == "text":
                    await message.channel.send(value.get("response", ""))
                elif value.get("type") == "reaction":
                    # For reaction type we expect the response to be an emoji string
                    await message.add_reaction(value.get("response", ""))
            except Exception:
                # ignore failures (bad emoji, missing perms, etc.)
                pass
            # don't break — allow multiple triggers per message if needed

    # 3) STICKY SYSTEM (count messages per channel and repost when interval reached)
    channel_id = message.channel.id
    if channel_id in sticky_data:
        try:
            sticky_data[channel_id]["count"] += 1
            if sticky_data[channel_id]["count"] >= sticky_data[channel_id]["interval"]:
                await message.channel.send(sticky_data[channel_id]["text"])
                sticky_data[channel_id]["count"] = 0
        except Exception:
            # ignore any errors (e.g., missing permissions)
            pass

    # 4) ensure commands still work
    await bot.process_commands(message)

# -----------------------------
# PREFIX COMMANDS
# -----------------------------
@bot.command()
async def say(ctx, *, message: str):
    """Bot repeats your message"""
    if not message:
        await ctx.send("⚠️ You need to provide a message!")
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(message)


@bot.command()
async def sayembed(ctx, *, args: str = None):
    """
    Usage:
    !sayembed Text here /image URL
    or
    !sayembed Text only
    """
    if not args:
        await ctx.send("⚠️ Usage: `!sayembed <text> /image <optional image URL>`")
        return

    # Check if /image is used
    if " /image " in args:
        parts = args.split(" /image ", 1)  # Split only at first occurrence
        text = parts[0].strip()
        image_url = parts[1].strip().replace("\n", "")  # Remove line breaks
    else:
        text = args.strip()
        image_url = None

    if not text and not image_url:
        await ctx.send("⚠️ You must provide text or an image URL!")
        return

    # Create embed
    embed = nextcord.Embed(description=text if text else "‎", color=nextcord.Color.random())
    if image_url:
        embed.set_image(url=image_url)

    await ctx.send(embed=embed)

# -----------------------------
# SLASH COMMANDS: suggestion
# -----------------------------
@bot.slash_command(name="suggestion", description="Make a suggestion")
async def suggestion(
    interaction: Interaction,
    type: str = SlashOption(
        name="type",
        description="Type of suggestion",
        choices={"Text": "text", "Image": "image", "Both": "both"},
        required=True
    ),
    content: str = SlashOption(name="content", description="Your suggestion content", required=False),
    image_url: str = SlashOption(name="image_url", description="Image URL if type is image/both", required=False)
):
    # Defer interaction to avoid "interaction failed"
    await interaction.response.defer(ephemeral=True)

    embed = nextcord.Embed(color=random.randint(0, 0xFFFFFF))
    embed.set_author(name=f"{interaction.user} has suggested this:")

    if type == "text":
        embed.description = content if content else "‎"
    elif type == "image":
        if image_url:
            embed.set_image(url=image_url)
        else:
            embed.description = "‎"
    elif type == "both":
        embed.description = content if content else "‎"
        if image_url:
            embed.set_image(url=image_url)

    # send to current channel
    try:
        msg = await interaction.channel.send(embed=embed)
        # Add reactions
        for emoji in ["👍🏼", "😑", "👎🏼"]:
            try:
                await msg.add_reaction(emoji)
            except Exception:
                pass
    except Exception:
        pass

    await interaction.followup.send("Your suggestion has been submitted!", ephemeral=True)

# -----------------------------
# AUTORESPONDER SLASH COMMANDS
# -----------------------------
@bot.slash_command(name="setautoresponder", description="Add an autoresponder")
async def set_autoresponder(
    interaction: Interaction,
    trigger: str = SlashOption(description="Trigger word"),
    response: str = SlashOption(description="Response or reaction"),
    form: str = SlashOption(description="text or reaction")
):
    data = load_autoresponders()
    data[trigger] = {"response": response, "type": form.lower()}
    save_autoresponders(data)
    await interaction.response.send_message(f"Autoresponder set for trigger: {trigger}")

@bot.slash_command(name="removeautoresponder", description="Remove an autoresponder")
async def remove_autoresponder(
    interaction: Interaction,
    trigger: str = SlashOption(description="Trigger to remove")
):
    data = load_autoresponders()
    if trigger in data:
        data.pop(trigger)
        save_autoresponders(data)
        await interaction.response.send_message(f"Removed autoresponder for trigger: {trigger}")
    else:
        await interaction.response.send_message(f"No autoresponder found for trigger: {trigger}")

@bot.slash_command(name="listautoresponders", description="List all autoresponders")
async def list_autoresponders(interaction: Interaction):
    data = load_autoresponders()
    if not data:
        await interaction.response.send_message("No autoresponders set.")
        return
    desc = "\n".join([f"**{k}** -> {v['response']} ({v['type']})" for k,v in data.items()])
    embed = nextcord.Embed(title="Autoresponders", description=desc, color=0x00ff00)
    await interaction.response.send_message(embed=embed)

# -----------------------------
# DRAGON BALL DB SLASH COMMANDS
# -----------------------------
@bot.slash_command(name="dragonball", description="Manage Dragon Ball characters")
async def dragonball(
    interaction: Interaction,
    action: str = SlashOption(description="add/get/list", choices={"add": "add", "get": "get", "list": "list"}),
    name: str = SlashOption(description="Character name", required=False),
    description: str = SlashOption(description="Character description (for add)", required=False)
):
    if action == "add":
        try:
            c.execute("INSERT INTO dragonball_characters (name, description) VALUES (?, ?)", (name, description))
            conn.commit()
            await interaction.response.send_message(f"Added {name} to DB.")
        except sqlite3.IntegrityError:
            await interaction.response.send_message(f"{name} already exists.")
    elif action == "get":
        c.execute("SELECT description FROM dragonball_characters WHERE name=?", (name,))
        res = c.fetchone()
        if res:
            await interaction.response.send_message(f"**{name}**: {res[0]}")
        else:
            await interaction.response.send_message(f"No character named {name}.")
    elif action == "list":
        c.execute("SELECT name FROM dragonball_characters")
        names = [row[0] for row in c.fetchall()]
        await interaction.response.send_message("Characters: " + ", ".join(names))

# -----------------------------
# QUOTE SLASH COMMANDS
# -----------------------------
@bot.slash_command(name="quote", description="Manage Dragon Ball quotes")
async def quote(
    interaction: Interaction,
    action: str = SlashOption(description="add/get/random", choices={"add": "add", "get": "get", "random": "random"}),
    character: str = SlashOption(description="Character name", required=False),
    text: str = SlashOption(description="Quote text (for add)", required=False)
):
    if action == "add":
        c.execute("INSERT INTO dragonball_quotes (character, quote) VALUES (?, ?)", (character, text))
        conn.commit()
        await interaction.response.send_message(f"Quote added for {character}.")
    elif action == "get":
        c.execute("SELECT quote FROM dragonball_quotes WHERE character=?", (character,))
        res = c.fetchall()
        if res:
            quotes = [q[0] for q in res]
            await interaction.response.send_message(f"Quotes for {character}:\n" + "\n".join(quotes))
        else:
            await interaction.response.send_message(f"No quotes found for {character}.")
    elif action == "random":
        c.execute("SELECT character, quote FROM dragonball_quotes")
        res = c.fetchall()
        if res:
            char, q = random.choice(res)
            await interaction.response.send_message(f"**{char}** says: {q}")
        else:
            await interaction.response.send_message("No quotes in DB.")

# -----------------------------
# FUN SLASH COMMANDS
# -----------------------------
@bot.slash_command(name="fun", description="Fun commands")
async def fun(
    interaction: Interaction,
    action: str = SlashOption(description="roll/compliment", choices={"roll": "roll", "compliment": "compliment"}),
    user: nextcord.Member = SlashOption(description="User to compliment", required=False)
):
    if action == "roll":
        power = random.randint(1000, 99999)
        await interaction.response.send_message(f"💥 Saiyan Power Level Roll: {power} 🔥")
    elif action == "compliment":
        if user:
            compliments = [
                "You’re as mighty as a Super Saiyan!",
                "Your energy is unstoppable!",
                "You could take on Frieza himself!"
            ]
            await interaction.response.send_message(f"{user.mention}, {random.choice(compliments)}")
        else:
            await interaction.response.send_message("Mention a user to compliment!")

# -----------------------------
# TRANSLATE SLASH COMMAND
# -----------------------------
@bot.slash_command(
    name="translate",
    description="Translate text to another language"
)
async def translate(
    interaction: Interaction,
    text: str = SlashOption(description="Text you want translated", required=True),
    language: str = SlashOption(description="Language code (en, hi, ja, es, fr...)", required=True)
):
    await interaction.response.send_message("I got this 🔥")
    try:
        translated_text = GoogleTranslator(source="auto", target=language).translate(text)
        embed = Embed(
            title="🌐 Translation Complete",
            description=f"**Translated to `{language}`:**\n\n{translated_text}",
            color=0x00FFAE
        )
        embed.set_footer(text="Saiyan-grade translation ⚡")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{e}`\nInvalid language code?")

# -----------------------------
# STICKY SLASH COMMANDS (repeat every X messages)
# -----------------------------
@bot.slash_command(description="Set a sticky message in a channel")
async def setsticky(
    interaction: Interaction,
    channel: nextcord.abc.GuildChannel,
    interval: int,
    message: str
):
    if not isinstance(channel, nextcord.TextChannel):
        return await interaction.response.send_message("Select a text channel.", ephemeral=True)

    sticky_data[channel.id] = {
        "text": message,
        "interval": max(1, int(interval)),
        "count": 0
    }

    await interaction.response.send_message(
        f"✅ Sticky message set!\n"
        f"• Channel: {channel.mention}\n"
        f"• Interval: {interval} messages\n"
        f"• Message: {message}"
    )

@bot.slash_command(description="Remove sticky from a channel")
async def removesticky(
    interaction: Interaction,
    channel: nextcord.abc.GuildChannel
):
    if channel.id not in sticky_data:
        return await interaction.response.send_message("❌ No sticky set in this channel.")

    del sticky_data[channel.id]
    await interaction.response.send_message(f"🗑️ Sticky removed from {channel.mention}!")

# -----------------------------
# BOT READY
# -----------------------------
@bot.event
async def on_ready():
    print(f"Gohan Bot is online as {bot.user}!")

# -----------------------------
# RUN BOT
# -----------------------------
bot.run(BOT_TOKEN)
