import os
import discord
from discord.ext import commands
from discord import app_commands
from mysever import server_on
import asyncio
import sqlite3

# --- Configuration: Channel and Role IDs ---
# Ensure these IDs are correct for your specific server
SCHEDULE_CHANNEL_ID = 1502332277072597052
ANNOUNCEMENT_CHANNEL_ID = 1502331959517384828
WELCOME_LOG_CHANNEL_ID = 1502332037917573261
COMMAND_CHANNEL_ID = 1502332210068324503
VERIFY_CHANNEL_ID = 1502581306913980496
VERIFIED_ROLE_ID = 1502531862739030157

# --- Bot Setup ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- Database System ---
def init_db():
    """Initializes the SQLite database for music statistics."""
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
    """Updates play count for a specific song URL."""
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

# --- Custom Decorator: Channel Check ---
def is_command_channel():
    """Restricts command usage to the designated command channel."""
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.channel_id == COMMAND_CHANNEL_ID
    return app_commands.check(predicate)

# --- Verification System Components ---
class VerifyRequestView(discord.ui.View):
    """View displayed in the public verification channel."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify Here", style=discord.ButtonStyle.success, custom_id="verify_request_btn")
    async def request_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role in interaction.user.roles:
            return await interaction.followup.send("You are already verified!", ephemeral=True)

        cmd_channel = bot.get_channel(COMMAND_CHANNEL_ID)
        if cmd_channel:
            embed = discord.Embed(
                title="🔔 New Verification Request",
                description=f"**User:** {interaction.user.mention}\n**Username:** `{interaction.user.name}`\n**ID:** `{interaction.user.id}`\n\nPlease review and approve below.",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            view = AdminApproveView(target_user_id=interaction.user.id)
            await cmd_channel.send(embed=embed, view=view)
            await interaction.followup.send("✅ Request sent to staff. Please wait for approval.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Command channel not found. Please contact an admin.", ephemeral=True)

class AdminApproveView(discord.ui.View):
    """View sent to the command channel for admin approval."""
    def __init__(self, target_user_id=None):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Approve & Grant Role", style=discord.ButtonStyle.green, custom_id="approve_btn_static")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ You do not have permission to manage roles.", ephemeral=True)

        await interaction.response.defer()

        if self.target_user_id is None:
            try:
                description = interaction.message.embeds[0].description
                self.target_user_id = int(description.split("ID:** `")[1].split("`")[0])
            except:
                return await interaction.followup.send("❌ Could not identify user ID from message.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.target_user_id)
        role = guild.get_role(VERIFIED_ROLE_ID)

        if not role or not member:
            return await interaction.followup.send("❌ Role or user not found in the server.", ephemeral=True)

        try:
            await member.add_roles(role)
            button.disabled = True
            button.label = "Approved"
            button.style = discord.ButtonStyle.secondary
            
            embed = interaction.message.embeds[0]
            embed.title = "✅ Verification Successful"
            embed.color = discord.Color.green()
            embed.add_field(name="Approved By", value=interaction.user.mention, inline=False)
            
            await interaction.edit_original_response(embed=embed, view=self)
            try:
                await member.send(f"🎉 You have been verified in **{guild.name}**!")
            except:
                pass 
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

# --- Voting System Components ---
class PollView(discord.ui.View):
    """View for creating interactive polls with live updates."""
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
            
        close_btn = discord.ui.Button(label="Close Poll", style=discord.ButtonStyle.danger, custom_id="close_poll")
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.voters:
            return await interaction.response.send_message("You have already voted!", ephemeral=True)
        
        idx = int(interaction.data['custom_id'].replace("poll_opt_", ""))
        selected_option = self.options[idx]
        self.votes[selected_option] += 1
        self.voters.add(interaction.user.id)
        await self.update_poll_message(interaction)

    async def close_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only creator/admin can close!", ephemeral=True)
        
        for item in self.children:
            item.disabled = True
        embed = interaction.message.embeds[0]
        embed.title = "📊 POLL CLOSED"
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
        embed.set_footer(text=f"Total: {total_votes} | Updated by: {interaction.user.display_name}")
        await interaction.response.edit_message(embed=embed, view=self)

# --- Events ---
@bot.event
async def on_ready():
    init_db()
    bot.add_view(VerifyRequestView())
    bot.add_view(AdminApproveView()) 
    print(f'[System] Bot {bot.user} is online.')
    try:
        await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print(f"Sync error: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Use this in <#{COMMAND_CHANNEL_ID}>", ephemeral=True)
    elif isinstance(error, app_commands.MissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Missing Permissions.", ephemeral=True)

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="Welcome!", description=f"Welcome {member.mention} to the server!", color=0xFFD230)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="Goodbye!", description=f"{member.name} has left.", color=0xFF2056)
        await channel.send(embed=embed)

# --- Slash Commands ---

@bot.tree.command(name='setup_verify', description="Setup verification message")
@is_command_channel()
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel:
        return await interaction.followup.send("❌ Channel not found.", ephemeral=True)
    
    embed = discord.Embed(title="🔒 Verification", description="Click to verify.", color=0x2ecc71)
    await channel.send(embed=embed, view=VerifyRequestView())
    await interaction.followup.send("✅ Setup complete.", ephemeral=True)

@bot.tree.command(name='poll', description="Create a poll")
@is_command_channel()
async def poll(interaction: discord.Interaction, question: str, options: str):
    await interaction.response.defer(ephemeral=True)
    option_list = [opt.strip() for opt in options.split(',')]
    if len(option_list) < 2:
        return await interaction.followup.send("Need 2+ options.", ephemeral=True)
    
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel: return await interaction.followup.send("❌ Channel not found.", ephemeral=True)
        
    embed = discord.Embed(title="📊 LIVE POLL", description=f"# {question}", color=0x5865F2)
    for opt in option_list:
        embed.add_field(name=f"🔹 {opt}", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ **0** votes (0%)", inline=False)
    
    await channel.send(embed=embed, view=PollView(option_list, interaction.user))
    await interaction.followup.send("✅ Poll created.", ephemeral=True)

@bot.tree.command(name='announce_room', description="Announce room opening to Announcement and Schedule channels")
@is_command_channel()
async def announce_room(interaction: discord.Interaction, type: str, room_name: str, time_start: str, time_end: str, link: str, description: str):
    # Defer immediately to prevent response timeout
    await interaction.response.defer(ephemeral=True)
    
    ann_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    sch_channel = bot.get_channel(SCHEDULE_CHANNEL_ID)
    
    # 1. Prepare Main Announcement Embed
    embed = discord.Embed(title=f"# 📢 ROOM OPENING\n## 📂 CATEGORY: {type}", color=0xFF2056)
    embed.add_field(name="📍 LOCATION / ROOM", value=f"```\n{room_name}\n```", inline=False)
    embed.add_field(name="⏰ DURATION", value=f"⏳ **{time_start}** - **{time_end}**", inline=True)
    embed.add_field(name="📃 ATTACHMENT", value=f"🔗 [Open Document]({link})" if link != '-' else '-', inline=True)
    embed.add_field(name="🎯 DESCRIPTION", value=f"```fix\n{description}\n```", inline=False)
    embed.set_footer(text=f"Announced by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    # 2. Prepare Schedule Log Embed
    sch_embed = discord.Embed(title=f"📆 New Schedule Added: {type}", description=description, color=0xB22222)
    sch_embed.add_field(name="📍 Location", value=f"`{room_name}`", inline=True)
    sch_embed.add_field(name="⏰ Time", value=f"`{time_start} - {time_end}`", inline=True)
    sch_embed.set_timestamp()

    errors = []
    
    # Send to Announcement Channel
    if ann_channel:
        try:
            await ann_channel.send(embed=embed)
        except Exception as e:
            errors.append(f"Announcement: {e}")
    else:
        errors.append("Announcement channel not found.")

    # Send to Schedule Channel
    if sch_channel:
        try:
            await sch_channel.send(embed=sch_embed)
        except Exception as e:
            errors.append(f"Schedule: {e}")
    else:
        errors.append("Schedule channel not found.")

    # Final Feedback
    if not errors:
        await interaction.followup.send("✅ Room announced successfully in both channels!", ephemeral=True)
    else:
        error_msg = "\n".join(errors)
        await interaction.followup.send(f"⚠️ Sent with errors:\n{error_msg}", ephemeral=True)

@bot.tree.command(name='announce_normal', description="General announcement")
@is_command_channel()
async def announce_normal(interaction: discord.Interaction, topic: str, to: str, content: str, link: str, details: str):
    await interaction.response.defer(ephemeral=True)
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    
    embed = discord.Embed(title=f"# 📢 ANNOUNCEMENT: {topic}", color=0xFF2056)
    embed.add_field(name="To", value=f"```\n{to}\n```", inline=False)
    embed.add_field(name="Content", value=f"```\n{content}\n```", inline=False)
    embed.add_field(name="Document", value=f"🔗 [Open]({link})" if link != '-' else '-', inline=False)
    embed.add_field(name="Details", value=f"```fix\n{details}\n```", inline=False)
    embed.set_footer(text=f"By {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    if channel:
        await channel.send(embed=embed)
        await interaction.followup.send("✅ Sent.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Channel not found.", ephemeral=True)

@bot.tree.command(name='timer', description="Set timer")
@is_command_channel()
async def timer(interaction: discord.Interaction, minutes: int, details: str = "Time's up!"):
    await interaction.response.send_message(f"⏲️ Timer: {minutes}m for **{details}**")
    await asyncio.sleep(minutes * 60)
    await interaction.channel.send(f"🔔 {interaction.user.mention} **Time's up: {details}**")

@bot.tree.command(name='role_summary', description="Role statistics")
@is_command_channel()
async def role_summary(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
    embed = discord.Embed(title=f"📊 Role Summary: {guild.name}", color=discord.Color.blue())
    
    for role in roles:
        if role.is_default(): continue
        m_members = role.members
        m_list = [m.display_name for m in m_members]
        names = ", ".join(m_list[:10]) + ("..." if len(m_list) > 10 else "")
        humans = len([m for m in m_members if not m.bot])
        bots = len([m for m in m_members if m.bot])
        
        val = f"👤 Humans: {humans} | 🤖 Bots: {bots}\n`{names if names else 'Empty'}`"
        embed.add_field(name=f"🏷️ {role.name} ({len(m_members)})", value=val, inline=False)
        
    await interaction.followup.send(embed=embed)

# --- Role Management Modal & System ---
class RoleMemberModal(discord.ui.Modal, title='Search & Grant Role'):
    member_input = discord.ui.TextInput(label='Member Name or ID', required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query = self.member_input.value
        guild = interaction.guild
        member = guild.get_member(int(query)) if query.isdigit() else discord.utils.get(guild.members, display_name=query)
        
        if not member:
            return await interaction.followup.send(f"❌ Not found: `{query}`", ephemeral=True)
            
        await interaction.followup.send(f"👤 Found {member.mention}. Select role:", view=RoleSelectView(member), ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=60)
        self.target_member = target_member
        
    @discord.ui.select(
        placeholder="Select role...",
        options=[
            discord.SelectOption(label="Controller", value="1501235032118001674", emoji="📡"),
            discord.SelectOption(label="Study", value="1502533553244864612", emoji="📖"),
            discord.SelectOption(label="Game", value="1502534056854818976", emoji="🕹️"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer(ephemeral=True)
        role = interaction.guild.get_role(int(select.values[0]))
        if not role: return await interaction.followup.send("❌ Role not found.", ephemeral=True)
            
        try:
            await self.target_member.add_roles(role)
            await interaction.edit_original_response(content=f"✅ Granted {role.name} to {self.target_member.name}", view=None)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name='give_role', description="Search and give role")
@is_command_channel()
@app_commands.checks.has_permissions(manage_roles=True)
async def give_role(interaction: discord.Interaction):
    await interaction.response.send_modal(RoleMemberModal())

# --- Start ---
server_on()
bot.run(os.getenv('TOKEN'))
