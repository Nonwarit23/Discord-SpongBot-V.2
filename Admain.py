import discord
import os
from discord import app_commands
from mysever import server_on
import sqlite3
import asyncio


# ตั้งค่า ID ห้องแชท และ รายชื่อห้องเสียงที่เลือกเข้าได้
# รูปแบบ: { ID_ห้องแชท: ["ชื่อห้องเสียง1", "ชื่อห้องเสียง2", "ชื่อห้องเสียง3"] }
MUSIC_CONFIG = {
    1502545890953396235: ["1️⃣ Game room", "2️⃣ Game room", "3️⃣ Game room"],  # ห้อง A (Game Zone)
    1502546288108113980: ["🦠biology-room-", "🧪Chemistry room", "🍎Physics Room"]         # ห้อง B (Study Zone)
}

# --- DATABASE SYSTEM ---
def init_db():
    conn = sqlite3.connect('music_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS music_stats (
            url TEXT PRIMARY KEY,
            title TEXT,
            play_count INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

def update_stats(title, url):
    conn = sqlite3.connect('music_stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO music_stats (url, title, play_count)
        VALUES (?, ?, 1)
        ON CONFLICT(url) DO UPDATE SET play_count = play_count + 1
    ''', (url, title))
    conn.commit()
    conn.close()

# --- DISCORD BOT SETUP ---
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()

bot = MyBot()

# --- UI COMPONENTS ---

# เมนูเลือกห้องเสียง (Remote Control)
class VoiceChannelSelect(discord.ui.Select):
    def __init__(self, channels, url, title):
        options = [discord.SelectOption(label=ch, value=ch) for ch in channels]
        super().__init__(placeholder="เลือกห้องที่จะให้บอทเข้าไปเล่นเพลง...", options=options)
        self.url = url
        self.title = title

    async def callback(self, interaction: discord.Interaction):
        selected_vc_name = self.values[0]
        # ค้นหาห้องเสียงในเซิร์ฟเวอร์ตามชื่อที่เลือก
        vc_channel = discord.utils.get(interaction.guild.voice_channels, name=selected_vc_name)
        
        if vc_channel:
            update_stats(self.title, self.url)
            await interaction.response.send_message(f"กำลังไปที่ห้อง **{selected_vc_name}** เพื่อเล่นเพลง: **{self.title}**")
            # โค้ดส่วนเชื่อมต่อ Voice (ข้ามส่วน play logic จริงเนื่องจากต้องใช้ FFmpeg)
            # await vc_channel.connect() 
        else:
            await interaction.response.send_message(f"ไม่พบห้องเสียงชื่อ {selected_vc_name} ในเซิร์ฟเวอร์นี้", ephemeral=True)

# เมนูเลือกเพลงฮิต (Recommend)
class FavoriteSongsSelect(discord.ui.Select):
    def __init__(self, options, allowed_vcs):
        super().__init__(placeholder="เลือกเพลงจากรายการที่ฟังบ่อย...", options=options)
        self.allowed_vcs = allowed_vcs

    async def callback(self, interaction: discord.Interaction):
        url = self.values[0]
        title = next(o.label for o in self.options if o.value == url)
        
        view = discord.ui.View()
        view.add_item(VoiceChannelSelect(self.allowed_vcs, url, title))
        await interaction.response.send_message(f"เลือกเพลงฮิต: **{title}**\nกรุณาเลือกห้องที่จะเล่นต่อ:", view=view, ephemeral=True)

# --- COMMANDS ---

@bot.tree.command(name="play_custom", description="สั่งเล่นเพลงและเลือกห้อง")
async def play_custom(interaction: discord.Interaction, url: str):
    channel_id = interaction.channel_id
    
    if channel_id not in MUSIC_CONFIG:
        return await interaction.response.send_message("❌ ห้องนี้ไม่อนุญาตให้ใช้คำสั่งเปิดเพลง", ephemeral=True)

    allowed_vcs = MUSIC_CONFIG[channel_id]
    title = "เพลงจากลิงก์ที่คุณส่งมา" # ในการใช้งานจริงควรใช้ yt-dlp ดึงชื่อเพลง
    
    view = discord.ui.View()
    view.add_item(VoiceChannelSelect(allowed_vcs, url, title))
    await interaction.response.send_message(f"🎵 รับคำสั่งเพลงแล้ว! กรุณาเลือกห้องเสียง:", view=view)

@bot.tree.command(name="recommend", description="ดูเพลงฮิตและเลือกเล่นทันที")
async def recommend(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in MUSIC_CONFIG:
        return await interaction.response.send_message("❌ กรุณาสั่งในห้องที่กำหนดเพื่อเลือกห้องเล่นเพลงได้", ephemeral=True)

    conn = sqlite3.connect('music_stats.db')
    cursor = conn.cursor()
    cursor.execute('SELECT title, url, play_count FROM music_stats ORDER BY play_count DESC LIMIT 5')
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return await interaction.response.send_message("ฐานข้อมูลยังว่างเปล่า ลองเปิดเพลงก่อนนะ!")

    embed = discord.Embed(title="🔥 5 อันดับเพลงที่เปิดบ่อยที่สุด", color=discord.Color.gold())
    options = []
    for i, (title, url, count) in enumerate(rows, 1):
        embed.add_field(name=f"{i}. {title}", value=f"เปิดไปแล้ว {count} ครั้ง", inline=False)
        options.append(discord.SelectOption(label=title[:100], value=url))

    view = discord.ui.View()
    view.add_item(FavoriteSongsSelect(options, MUSIC_CONFIG[channel_id]))
    await interaction.response.send_message(embed=embed, view=view)

server_on()
bot.run(os.getenv('TOKEN'))