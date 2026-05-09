import os
import discord
from discord.ext import commands
from discord import app_commands
from mysever import server_on
import asyncio

# Channel IDs
schedule = 1502332277072597052
announcement_channel_id = 1502331959517384828
s_output = 1502332037917573261
command_channel_id = 1502332210068324503
verify_channel_id = 1502581306913980496

# Role ID
VERIFIED_ROLE_ID = 1502531862739030157

# Bot Setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- Check Function ---
def is_command_channel():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.channel_id == command_channel_id
    return app_commands.check(predicate)

# --- Verification System Components ---

class VerifyRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # แก้ไข: เพิ่ม button เข้าไปในพารามิเตอร์เพื่อป้องกัน TypeError
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
            await interaction.response.send_message("❌ ไม่พบช่องสำหรับทีมงาน", ephemeral=True)

class AdminApproveView(discord.ui.View):
    def __init__(self, target_user_id=None):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Approve (ยืนยันและมอบยศ)", style=discord.ButtonStyle.green, custom_id="approve_btn_static")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.target_user_id is None:
            try:
                description = interaction.message.embeds[0].description
                self.target_user_id = int(description.split("ID:** `")[1].split("`")[0])
            except:
                return await interaction.response.send_message("❌ ไม่สามารถระบุ ID ผู้ใช้ได้", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.target_user_id)
        role = guild.get_role(VERIFIED_ROLE_ID)

        if not role or not member:
            return await interaction.response.send_message("❌ ไม่พบยศหรือผู้ใช้ในเซิร์ฟเวอร์", ephemeral=True)

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

# --- Vote System Components ---
class PollView(discord.ui.View):
    def __init__(self, options, creator, timeout=None):
        super().__init__(timeout=timeout)
        self.options = options
        self.creator = creator
        self.votes = {option: 0 for option in options}
        self.voters = set()
        
        for i, option in enumerate(self.options):
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary, custom_id=f"poll_opt_{i}")
            button.callback = self.button_callback
            self.add_item(button)
            
        close_button = discord.ui.Button(label="Close Poll", style=discord.ButtonStyle.danger, custom_id="close_poll")
        close_button.callback = self.close_callback
        self.add_item(close_button)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.voters:
            return await interaction.response.send_message("คุณได้ลงคะแนนไปแล้ว!", ephemeral=True)
        
        idx = int(interaction.data['custom_id'].replace("poll_opt_", ""))
        selected_option = self.options[idx]
        
        self.votes[selected_option] += 1
        self.voters.add(interaction.user.id)
        await self.update_poll_message(interaction)

    async def close_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator.id:
            return await interaction.response.send_message("เฉพาะผู้สร้าง Poll เท่านั้นที่ปิดได้!", ephemeral=True)
        
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
        embed.set_footer(text=f"Total Voters: {total_votes} | Last update: {interaction.user.display_name}")
        await interaction.response.edit_message(embed=embed, view=self)

# --- Events ---

@bot.event
async def on_ready():
    print(f'[System] Bot {bot.user} is now Online')
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
        await interaction.response.send_message(f"❌ คำสั่งนี้ใช้ได้เฉพาะในห้อง <#{command_channel_id}> เท่านั้น", ephemeral=True)

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(s_output)
    if channel:
        embed = discord.Embed(
            title="Welcome to the server!", 
            description=f"Welcome to the Sponglium play & study center, {member.mention}!", 
            color=0xFFD230
        )
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(s_output)
    if channel:
        embed = discord.Embed(
            title="Leave the server!", 
            description=f"{member.mention} has left the server!", 
            color=0xFF2056
        )
        await channel.send(embed=embed)

# --- Slash Commands ---

@bot.tree.command(name='setup_verify', description="ติดตั้งปุ่มยืนยันตัวตนในช่อง Verify")
@is_command_channel()
async def setup_verify(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ เฉพาะแอดมินเท่านั้นที่ใช้คำสั่งนี้ได้", ephemeral=True)

    channel = bot.get_channel(verify_channel_id)
    if not channel:
        return await interaction.response.send_message("❌ ไม่พบช่องสำหรับยืนยันตัวตน", ephemeral=True)

    embed = discord.Embed(
        title="🔒 ระบบยืนยันตัวตน (Verification System)",
        description="กดปุ่มด้านล่างเพื่อส่งคำขอรับการยืนยันตัวตนจากทีมงาน",
        color=0x2ecc71
    )
    embed.add_field(name="📜 วิธีการ", value="กดปุ่มสีเขียวแล้วรอทีมงานกดยืนยันในช่องคอมมานด์", inline=False)
    
    view = VerifyRequestView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ ติดตั้งระบบเรียบร้อย", ephemeral=True)

@bot.tree.command(name='poll', description="สร้างโหวตส่งไปห้องประกาศ")
@is_command_channel()
async def poll(interaction: discord.Interaction, question: str, options: str):
    option_list = [opt.strip() for opt in options.split(',')]
    if len(option_list) < 2:
        return await interaction.response.send_message("ต้องมีอย่างน้อย 2 ตัวเลือก", ephemeral=True)

    channel = bot.get_channel(announcement_channel_id)
    if not channel:
        return await interaction.response.send_message("❌ ไม่พบห้องประกาศ", ephemeral=True)

    embed = discord.Embed(title="📊 LIVE POLL", description=f"# {question}", color=0x5865F2)
    for opt in option_list:
        embed.add_field(name=f"🔹 {opt}", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ **0** votes (0%)", inline=False)
    
    view = PollView(option_list, interaction.user)
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ สร้างโหวตสำเร็จ", ephemeral=True)

@bot.tree.command(name='announce', description="ส่งประกาศเปิดห้อง (Thumbnail เป็นรูปเซิร์ฟเวอร์)")
@is_command_channel()
async def announce_room(interaction: discord.Interaction, room_name: str, type: str, time_s: str, time_t: str, link: str, des: str):
    channel = bot.get_channel(announcement_channel_id)
    
    # ดึง URL รูปไอคอนของเซิร์ฟเวอร์ (ถ้าไม่มีจะใช้ None)
    server_icon = interaction.guild.icon.url if interaction.guild.icon else None
    
    # สร้าง Embed แบบจัดเต็ม
    embed = discord.Embed(
        title=f"# 📢 ANNOUNCEMENT\n## 📂 TOPIC: {type}\n" + "—" * 25,
        description="ประกาศเปิดห้องพูดคุย",
        color=0xFF2056
    )

    # 1. ใส่รูปมุมขวาบนเป็นรูปเซิร์ฟเวอร์
    if server_icon:
        embed.set_thumbnail(url=server_icon)

    # 2. ข้อมูลหลัก
    embed.add_field(name="📍 LOCATION", value=f"```\n{room_name}\n```", inline=False)
    embed.add_field(name="⏰ DURATION", value=f"⏳ **{time_s}** - **{time_t}**", inline=True)
    
    if link != '-':
        embed.add_field(name="📃 DOCUMENT", value=f"🔗 [คลิกชมเอกสาร]({link})", inline=True)
    else:
        embed.add_field(name="📃 DOCUMENT", value='-', inline=True)
    
    # 3. รายละเอียด (ใช้ช่องสีเทา fix ให้ดูเด่น)
    embed.add_field(name="🎯 INFORMATION", value=f"```fix\n{des}\n```", inline=False)

    # 4. ส่วนท้าย (บอกว่าใครเป็นคนประกาศ)
    embed.set_footer(
        text=f"ประกาศโดย {interaction.user.display_name} • {interaction.guild.name}", 
        icon_url=interaction.user.display_avatar.url
    )

    await channel.send(embed=embed)
    await interaction.response.send_message("✅ ส่งประกาศสำเร็จ", ephemeral=True)

@bot.tree.command(name='timer', description="ตั้งเวลาถอยหลัง")
@is_command_channel()
async def timer(interaction: discord.Interaction, minutes: int, details: str = "Time's up!"):
    await interaction.response.send_message(f"⏲️ เริ่มนับถอยหลัง {minutes} นาที: **{details}**")
    await asyncio.sleep(minutes * 60)
    await interaction.channel.send(f"🔔 {interaction.user.mention} **หมดเวลาแล้วสำหรับ: {details}**")

@bot.tree.command(name='role_summary', description="สรุปจำนวนสมาชิกและรายชื่อในแต่ละ Role")
@is_command_channel()
async def role_summary(interaction: discord.Interaction):
    guild = interaction.guild
    
    # ดึงรายชื่อ Role ทั้งหมด (เรียงจากตำแหน่งสูงสุดลงไป และข้าม @everyone)
    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
    
    embed = discord.Embed(
        title=f"📊 สรุปรายชื่อ Role ในเซิร์ฟเวอร์ {guild.name}",
        description="ตรวจสอบจำนวนสมาชิกและรายชื่อแยกตามยศ",
        color=discord.Color.blue()
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    for role in roles:
        if role.is_default(): # ข้าม @everyone
            continue
            
        # แยกแยะสมาชิกที่เป็นคน และ สมาชิกที่เป็นบอท
        humans = [m for m in role.members if not m.bot]
        bots = [m for m in role.members if m.bot]
        
        # เตรียมรายชื่อสมาชิก (แสดงสูงสุด 15 คนแรกเพื่อไม่ให้ข้อความยาวเกินไป)
        member_names = [m.display_name for m in role.members]
        if len(member_names) > 15:
            names_str = ", ".join(member_names[:15]) + f" ...และอีก {len(member_names)-15} คน"
        elif len(member_names) > 0:
            names_str = ", ".join(member_names)
        else:
            names_str = "ไม่มีสมาชิก"

        field_value = (
            f"👤 **มนุษย์:** {len(humans)} คน\n"
            f"🤖 **บอท:** {len(bots)} ตัว\n"
            f"📜 **สมาชิก:** `{names_str}`"
        )
        
        embed.add_field(
            name=f"🏷️ {role.name} (รวม {len(role.members)})",
            value=field_value,
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# --- 1. หน้าต่างกรอกชื่อสมาชิก (Modal) ---
class RoleMemberModal(discord.ui.Modal, title='ระบุสมาชิกที่ต้องการมอบยศ'):
    member_input = discord.ui.TextInput(
        label='ชื่อสมาชิก หรือ ID (ต้องอยู่ในเซิร์ฟเวอร์)',
        placeholder='ตัวอย่าง: Somchai หรือ 123456789012345678',
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        query = self.member_input.value
        guild = interaction.guild
        
        # ค้นหา Member จาก ID หรือ ชื่อ
        member = None
        if query.isdigit():
            member = guild.get_member(int(query))
        else:
            member = discord.utils.get(guild.members, display_name=query) or discord.utils.get(guild.members, name=query)

        if not member:
            return await interaction.response.send_message(f"❌ ไม่พบสมาชิกที่ชื่อว่า `{query}`", ephemeral=True)

        # เมื่อเจอสมาชิกแล้ว ให้ส่งเมนูเลือกยศไปให้แอดมินเลือก
        view = RoleSelectView(member)
        await interaction.response.send_message(f"👤 เลือกยศที่ต้องการมอบให้คุณ {member.mention}:", view=view, ephemeral=True)

# --- 2. เมนูเลือกยศ (Select Menu) ---
class RoleSelectView(discord.ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=60)
        self.target_member = target_member

    # คุณสามารถเพิ่ม/ลด รายชื่อยศตรงนี้ได้
    @discord.ui.select(
        placeholder="เลือกยศที่ต้องการ...",
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
            return await interaction.response.send_message("❌ ไม่พบยศนี้ในเซิร์ฟเวอร์", ephemeral=True)

        try:
            await self.target_member.add_roles(role)
            
            # ปิดการใช้งาน Select Menu หลังเลือกเสร็จ
            self.clear_items()
            await interaction.response.edit_message(
                content=f"✅ มอบยศ {role.mention} ให้กับ {self.target_member.mention} เรียบร้อยแล้ว!", 
                view=self
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

# --- 3. Slash Command สำหรับเรียกใช้งาน ---
@bot.tree.command(name='give_role', description="ค้นหาสมาชิกและเลือกยศที่จะมอบให้")
@is_command_channel()
@app_commands.checks.has_permissions(manage_roles=True)
async def give_role(interaction: discord.Interaction):
    # ตรวจสอบว่าบอทมีสิทธิ์จัดการยศไหม
    if not interaction.guild.me.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ บอทไม่มีสิทธิ์ `Manage Roles` (จัดลำดับยศบอทให้สูงกว่ายศที่จะมอบด้วยนะครับ)", ephemeral=True)
        
    await interaction.response.send_modal(RoleMemberModal())


server_on()
bot.run(os.getenv('TOKEN'))