import os
import discord
from discord.ext import commands
from discord import app_commands
from mysever import server_on
import asyncio
import sqlite3

# --- การตั้งค่า ID ต่างๆ ---
schedule = 1502332277072597052
announcement_channel_id = 1502331959517384828
s_output = 1502332037917573261
command_channel_id = 1502332210068324503
verify_channel_id = 1502581306913980496
VERIFIED_ROLE_ID = 1502531862739030157

# --- ตั้งค่า Bot ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- ระบบฐานข้อมูล ---
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
        ON CONFLICT(url) DO UPDATE SET 
            play_count = play_count + 1
    ''', (url, title))
    conn.commit()
    conn.close()

# --- ฟังก์ชันตรวจสอบห้อง (Decorator) ---
def is_command_channel():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.channel_id == command_channel_id
    return app_commands.check(predicate)

# --- ส่วนประกอบระบบยืนยันตัวตน ---
class VerifyRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ยืนยันตัวตนที่นี่ / Verify Here", style=discord.ButtonStyle.success, custom_id="verify_request_btn")
    async def request_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role in interaction.user.roles:
            return await interaction.response.send_message("คุณได้รับการยืนยันตัวตนอยู่แล้วครับ!", ephemeral=True)

        cmd_channel = bot.get_channel(command_channel_id)
        if cmd_channel:
            embed = discord.Embed(
                title="🔔 คำขอการยืนยันตัวตนใหม่",
                description=f"**ผู้ใช้:** {interaction.user.mention}\n**ชื่อในดิส:** `{interaction.user.name}`\n**ID:** `{interaction.user.id}`\n\nกรุณาตรวจสอบและกดยืนยันด้านล่างเพื่อมอบยศ",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            view = AdminApproveView(target_user_id=interaction.user.id)
            await cmd_channel.send(embed=embed, view=view)
            await interaction.response.send_message("✅ ส่งคำขอไปยังทีมงานเรียบร้อยแล้ว กรุณารอสักครู่นะครับ", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่พบช่องสำหรับทีมงาน (Command Channel)", ephemeral=True)

class AdminApproveView(discord.ui.View):
    def __init__(self, target_user_id=None):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Approve (ยืนยันและมอบยศ)", style=discord.ButtonStyle.green, custom_id="approve_btn_static")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ตรวจสอบสิทธิ์ผู้กดปุ่ม (ต้องมีสิทธิ์จัดการยศ)
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์กดปุ่มนี้", ephemeral=True)

        if self.target_user_id is None:
            try:
                description = interaction.message.embeds[0].description
                self.target_user_id = int(description.split("ID:** `")[1].split("`")[0])
            except:
                return await interaction.response.send_message("❌ ไม่สามารถระบุ ID ผู้ใช้จากข้อความได้", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.target_user_id)
        role = guild.get_role(VERIFIED_ROLE_ID)

        if not role or not member:
            return await interaction.response.send_message("❌ ไม่พบยศหรือผู้ใช้อยู่ในเซิร์ฟเวอร์ในขณะนี้", ephemeral=True)

        try:
            await member.add_roles(role)
            button.disabled = True
            button.label = "Approved (มอบยศแล้ว)"
            button.style = discord.ButtonStyle.secondary
            
            embed = interaction.message.embeds[0]
            embed.title = "✅ การยืนยันตัวตนสำเร็จ"
            embed.color = discord.Color.green()
            embed.add_field(name="อนุมัติโดย", value=interaction.user.mention, inline=False)
            
            await interaction.response.edit_message(embed=embed, view=self)
            try:
                await member.send(f"🎉 คุณได้รับการยืนยันตัวตนใน **{guild.name}** เรียบร้อยแล้ว!")
            except:
                pass 
        except Exception as e:
            await interaction.response.send_message(f"เกิดข้อผิดพลาด: {e}", ephemeral=True)

# --- ส่วนประกอบระบบโหวต ---
class PollView(discord.ui.View):
    def __init__(self, options, creator, timeout=None):
        super().__init__(timeout=timeout)
        self.options = options
        self.creator = creator
        self.votes = {option: 0 for option in options}
        self.voters = set()
        
        for i, option in enumerate(self.options):
            btn = discord.ui.Button(label=option, style=discord.ButtonStyle.primary, custom_id=f"poll_opt_{i}")
            btn.callback = self.button_callback
            self.add_item(btn)
            
        close_btn = discord.ui.Button(label="ปิดการโหวต (Close)", style=discord.ButtonStyle.danger, custom_id="close_poll")
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.voters:
            return await interaction.response.send_message("คุณได้ลงคะแนนไปแล้ว!", ephemeral=True)
        
        idx = int(interaction.data['custom_id'].replace("poll_opt_", ""))
        selected_option = self.options[idx]
        self.votes[selected_option] += 1
        self.voters.add(interaction.user.id)
        await self.update_poll_message(interaction)

    async def close_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("เฉพาะผู้สร้างโพลล์หรือแอดมินเท่านั้นที่ปิดได้!", ephemeral=True)
        
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.title = "📊 POLL CLOSED (สิ้นสุดการโหวต)"
        embed.color = discord.Color.red()
        await interaction.response.edit_message(embed=embed, view=self)

    async def update_poll_message(self, interaction):
        total_votes = len(self.voters)
        embed = interaction.message.embeds[0]
        embed.clear_fields()
        for opt, count in self.votes.items():
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            bar = "🟩" * int(percentage / 10) + "⬜" * (10 - int(percentage / 10))
            embed.add_field(name=f"🔹 {opt}", value=f"{bar} **{count}** votes ({percentage:.1f}%)", inline=False)
        embed.set_footer(text=f"Total Voters: {total_votes} | อัปเดตล่าสุด: {interaction.user.display_name}")
        await interaction.response.edit_message(embed=embed, view=self)

# --- เหตุการณ์ต่างๆ (Events) ---
@bot.event
async def on_ready():
    init_db()
    print(f'[System] Bot {bot.user} is now Online')
    # ทำให้ปุ่มยังคงทำงานอยู่แม้บอทจะรีสตาร์ท (Persistent Views)
    bot.add_view(VerifyRequestView())
    bot.add_view(AdminApproveView()) 
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Sync error: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(f"❌ คำสั่งนี้อนุญาตให้ใช้เฉพาะในห้อง <#{command_channel_id}> เท่านั้น", ephemeral=True)
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์เพียงพอในการใช้คำสั่งนี้", ephemeral=True)
    else:
        print(f"Unhandled Error: {error}")

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(s_output)
    if channel:
        embed = discord.Embed(title="ยินดีต้อนรับ! (Welcome)", description=f"ขอต้อนรับ {member.mention} เข้าสู่เซิร์ฟเวอร์ Sponglium!", color=0xFFD230)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(s_output)
    if channel:
        embed = discord.Embed(title="ลาก่อน! (Goodbye)", description=f"{member.name} ได้ออกจากเซิร์ฟเวอร์ไปแล้ว", color=0xFF2056)
        await channel.send(embed=embed)

# --- คำสั่ง Slash Commands ---

@bot.tree.command(name='setup_verify', description="ติดตั้งข้อความและปุ่มยืนยันตัวตนในห้องที่กำหนด")
@is_command_channel()
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    channel = bot.get_channel(verify_channel_id)
    if not channel:
        return await interaction.response.send_message("❌ ไม่พบช่องสำหรับยืนยันตัวตน (โปรดตรวจสอบ ID)", ephemeral=True)
    
    embed = discord.Embed(
        title="🔒 ระบบยืนยันตัวตน (Verification)", 
        description="กรุณากดปุ่มด้านล่างเพื่อส่งคำขอให้ทีมงานตรวจสอบและมอบยศเพื่อเข้าถึงเซิร์ฟเวอร์", 
        color=0x2ecc71
    )
    embed.add_field(name="หมายเหตุ", value="เมื่อกดแล้ว โปรดรอทีมงานดำเนินการสักครู่")
    
    await channel.send(embed=embed, view=VerifyRequestView())
    await interaction.response.send_message("✅ ติดตั้งระบบยืนยันตัวตนเรียบร้อยแล้ว", ephemeral=True)

@bot.tree.command(name='poll', description="สร้างการโหวตส่งไปยังห้องประกาศ")
@is_command_channel()
async def poll(interaction: discord.Interaction, question: str, options: str):
    option_list = [opt.strip() for opt in options.split(',')]
    if len(option_list) < 2:
        return await interaction.response.send_message("กรุณาระบุตัวเลือกอย่างน้อย 2 ตัวเลือก (คั่นด้วยคอมม่า `,`)", ephemeral=True)
    
    channel = bot.get_channel(announcement_channel_id)
    if not channel:
        return await interaction.response.send_message("❌ ไม่พบห้องประกาศ", ephemeral=True)
        
    embed = discord.Embed(title="📊 LIVE POLL (กำลังเปิดโหวต)", description=f"# {question}", color=0x5865F2)
    for opt in option_list:
        embed.add_field(name=f"🔹 {opt}", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ **0** votes (0%)", inline=False)
    
    await channel.send(embed=embed, view=PollView(option_list, interaction.user))
    await interaction.response.send_message("✅ สร้างโหวตสำเร็จแล้วในห้องประกาศ", ephemeral=True)

@bot.tree.command(name='announce_room', description="ประกาศเปิดห้องและบันทึกลงในตารางเวลา")
@is_command_channel()
async def announce_room(interaction: discord.Interaction, type: str, room_name: str, time_s: str, time_t: str, link: str, des: str):
    channel = bot.get_channel(announcement_channel_id)
    channel_a = bot.get_channel(schedule)
    server_icon = interaction.guild.icon.url if interaction.guild.icon else None
    
    # ประกาศหลัก
    embed = discord.Embed(title=f"# 📢 ANNOUNCEMENT\n## 📂 TOPIC: {type}", color=0xFF2056)
    if server_icon: embed.set_thumbnail(url=server_icon)
    embed.add_field(name="📍 LOCATION", value=f"```\n{room_name}\n```", inline=False)
    embed.add_field(name="⏰ DURATION", value=f"⏳ **{time_s}** - **{time_t}**", inline=True)
    embed.add_field(name="📃 DOCUMENT", value=f"🔗 [คลิกที่นี่เพื่อดู]({link})" if link != '-' else '-', inline=True)
    embed.add_field(name="🎯 INFORMATION", value=f"```fix\n{des}\n```", inline=False)
    embed.set_footer(text=f"โดย {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    # ลงตารางเวลา
    embed1 = discord.Embed(title=f"# 📆 Schedule (ตารางเวลา)\n## 📂 TOPIC: {type}", description=des, color=0xB22222)
    embed1.add_field(name="📍 LOCATION", value=f"```\n{room_name}\n```", inline=False)
    embed1.add_field(name="⏰ TIME", value=f"⏳ {time_s} ถึง {time_t}", inline=True)
    if link != '-': embed1.add_field(name="🔗 LINK", value=link, inline=False)

    if channel: await channel.send(embed=embed)
    if channel_a: await channel_a.send(embed=embed1)
    await interaction.response.send_message("✅ ส่งประกาศเปิดห้องสำเร็จ", ephemeral=True)

@bot.tree.command(name='announce_normal', description="ส่งประกาศทั่วไปพร้อมรายละเอียด")
@is_command_channel()
async def announce_normal(interaction: discord.Interaction, topic: str, who: str, content: str, link: str, des_link: str):
    channel = bot.get_channel(announcement_channel_id)
    server_icon = interaction.guild.icon.url if interaction.guild.icon else None
    
    embed = discord.Embed(
        title=f"# 📢 ANNOUNCEMENT\n## 📂 TOPIC: {topic}", 
        description="กรุณาอ่านประกาศด้านล่างนี้", 
        color=0xFF2056
    )
    if server_icon: embed.set_thumbnail(url=server_icon)
    embed.add_field(name="ถึง (To)", value=f"```\n{who}\n```", inline=False)
    embed.add_field(name="หัวข้อ (Content)", value=f"```\n{content}\n```", inline=False)
    embed.add_field(name="เอกสาร (Document)", value=f"🔗 [เปิดดูเอกสาร]({link})" if link != '-' else '-', inline=False)
    embed.add_field(name="รายละเอียดเพิ่มเติม", value=f"```fix\n{des_link}\n```", inline=False)
    embed.set_footer(text=f"ประกาศโดย {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url, timestamp=discord.utils.utcnow())

    if channel:
        await channel.send(embed=embed)
        await interaction.response.send_message("✅ ส่งประกาศทั่วไปสำเร็จ", ephemeral=True)
    else:
        await interaction.response.send_message("❌ ไม่พบห้องประกาศ", ephemeral=True)

@bot.tree.command(name='timer', description="ตั้งเวลาถอยหลังและแจ้งเตือนเมื่อหมดเวลา")
@is_command_channel()
async def timer(interaction: discord.Interaction, minutes: int, details: str = "หมดเวลาแล้ว!"):
    if minutes <= 0:
        return await interaction.response.send_message("❌ กรุณาระบุเวลาที่มากกว่า 0 นาที", ephemeral=True)
        
    await interaction.response.send_message(f"⏲️ เริ่มนับถอยหลัง {minutes} นาที สำหรับ: **{details}**")
    await asyncio.sleep(minutes * 60)
    await interaction.channel.send(f"🔔 {interaction.user.mention} **หมดเวลาแล้ว! สำหรับหัวข้อ: {details}**")

@bot.tree.command(name='role_summary', description="สรุปข้อมูล Role และรายชื่อสมาชิกในแต่ละยศ")
@is_command_channel()
async def role_summary(interaction: discord.Interaction):
    guild = interaction.guild
    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
    embed = discord.Embed(title=f"📊 สรุป Role ในเซิร์ฟเวอร์: {guild.name}", color=discord.Color.blue())
    
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)

    for role in roles:
        if role.is_default(): continue
        m_members = role.members
        m_list = [m.display_name for m in m_members]
        names = ", ".join(m_list[:10]) + ("..." if len(m_list) > 10 else "")
        
        humans = len([m for m in m_members if not m.bot])
        bots = len([m for m in m_members if m.bot])
        
        val = f"👤 มนุษย์: {humans} | 🤖 บอท: {bots}\nรายชื่อ: `{names if names else 'ไม่มีสมาชิก'}`"
        embed.add_field(name=f"🏷️ {role.name} (รวม {len(m_members)})", value=val, inline=False)
        
    await interaction.response.send_message(embed=embed)

# --- ระบบค้นหาและมอบยศ ---
class RoleMemberModal(discord.ui.Modal, title='ค้นหาสมาชิกและเลือกยศ'):
    member_input = discord.ui.TextInput(label='ชื่อสมาชิก หรือ ID', placeholder='ตัวอย่าง: Somchai หรือ 123456789', required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        query = self.member_input.value
        guild = interaction.guild
        member = guild.get_member(int(query)) if query.isdigit() else discord.utils.get(guild.members, display_name=query)
        
        if not member:
            return await interaction.response.send_message(f"❌ ไม่พบสมาชิกที่ชื่อหรือ ID `{query}`", ephemeral=True)
            
        await interaction.response.send_message(f"👤 พบสมาชิก {member.mention} แล้ว กรุณาเลือกยศที่จะมอบให้:", view=RoleSelectView(member), ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=60)
        self.target_member = target_member
        
    @discord.ui.select(
        placeholder="เลือกยศที่ต้องการมอบให้...",
        options=[
            discord.SelectOption(label="Controller", value="1501235032118001674", emoji="📡"),
            discord.SelectOption(label="Study permission", value="1502533553244864612", emoji="📖"),
            discord.SelectOption(label="Game permission", value="1502534056854818976", emoji="🕹️"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        role_id = int(select.values[0])
        role = interaction.guild.get_role(role_id)
        
        if not role:
            return await interaction.response.send_message("❌ ไม่พบยศที่เลือกในเซิร์ฟเวอร์นี้", ephemeral=True)
            
        try:
            await self.target_member.add_roles(role)
            await interaction.response.edit_message(content=f"✅ มอบยศ {role.mention} ให้แก่ {self.target_member.mention} สำเร็จแล้ว!", view=None)
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาดในการมอบยศ: {e}", ephemeral=True)

@bot.tree.command(name='give_role', description="ค้นหาสมาชิกและเลือกยศที่จะมอบให้ผ่านเมนู")
@is_command_channel()
@app_commands.checks.has_permissions(manage_roles=True)
async def give_role(interaction: discord.Interaction):
    if not interaction.guild.me.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ บอทไม่มีสิทธิ์จัดการยศ (Manage Roles)", ephemeral=True)
    await interaction.response.send_modal(RoleMemberModal())

# --- เริ่มการทำงาน ---
server_on()
bot.run(os.getenv('TOKEN'))
