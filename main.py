import os
import discord
from discord.ext import commands
from discord import app_commands
from mysever import server_on  # Note: Ensure 'myserver.py' exists and function name is correct
import asyncio
import sqlite3

# --- Configuration: Channel and Role IDs ---
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
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role in interaction.user.roles:
            return await interaction.response.send_message("You are already verified!", ephemeral=True)

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
            await interaction.response.send_message("✅ Request sent to staff. Please wait for approval.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Command channel not found. Please contact an admin.", ephemeral=True)

class AdminApproveView(discord.ui.View):
    """View sent to the command channel for admin approval."""
    def __init__(self, target_user_id=None):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Approve & Grant Role", style=discord.ButtonStyle.green, custom_id="approve_btn_static")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ You do not have permission to manage roles.", ephemeral=True)

        # Attempt to recover target ID from embed if not provided (for persistence)
        if self.target_user_id is None:
            try:
                description = interaction.message.embeds[0].description
                self.target_user_id = int(description.split("ID:** `")[1].split("`")[0])
            except:
                return await interaction.response.send_message("❌ Could not identify user ID from message.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.target_user_id)
        role = guild.get_role(VERIFIED_ROLE_ID)

        if not role or not member:
            return await interaction.response.send_message("❌ Role or user not found in the server.", ephemeral=True)

        try:
            await member.add_roles(role)
            button.disabled = True
            button.label = "Approved"
            button.style = discord.ButtonStyle.secondary
            
            embed = interaction.message.embeds[0]
            embed.title = "✅ Verification Successful"
            embed.color = discord.Color.green()
            embed.add_field(name="Approved By", value=interaction.user.mention, inline=False)
            
            await interaction.response.edit_message(embed=embed, view=self)
            try:
                await member.send(f"🎉 You have been verified in **{guild.name}**!")
            except:
                pass 
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

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
            return await interaction.response.send_message("Only the creator or an admin can close this poll!", ephemeral=True)
        
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
        embed.set_footer(text=f"Total Voters: {total_votes} | Last update: {interaction.user.display_name}")
        await interaction.response.edit_message(embed=embed, view=self)

# --- Events ---
@bot.event
async def on_ready():
    init_db()
    print(f'[System] Bot {bot.user} is now Online')
    # Register persistent views
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
        await interaction.response.send_message(f"❌ This command can only be used in <#{COMMAND_CHANNEL_ID}>", ephemeral=True)
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You do not have sufficient permissions to use this command.", ephemeral=True)
    else:
        print(f"Unhandled Error: {error}")

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="Welcome!", description=f"Welcome {member.mention} to Sponglium server!", color=0xFFD230)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(WELCOME_LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title="Goodbye!", description=f"{member.name} has left the server.", color=0xFF2056)
        await channel.send(embed=embed)

# --- Slash Commands ---

@bot.tree.command(name='setup_verify', description="Setup verification message and button in the verify channel")
@is_command_channel()
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction):
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Verify channel not found (Check ID).", ephemeral=True)
    
    embed = discord.Embed(
        title="🔒 Server Verification", 
        description="Please click the button below to request verification and access the server.", 
        color=0x2ecc71
    )
    embed.add_field(name="Note", value="Once clicked, please wait for a staff member to approve your request.")
    
    await channel.send(embed=embed, view=VerifyRequestView())
    await interaction.response.send_message("✅ Verification system setup successfully.", ephemeral=True)

@bot.tree.command(name='poll', description="Create a poll in the announcement channel")
@is_command_channel()
async def poll(interaction: discord.Interaction, question: str, options: str):
    option_list = [opt.strip() for opt in options.split(',')]
    if len(option_list) < 2:
        return await interaction.response.send_message("Please provide at least 2 options (separated by commas `,`)", ephemeral=True)
    
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Announcement channel not found.", ephemeral=True)
        
    embed = discord.Embed(title="📊 LIVE POLL", description=f"# {question}", color=0x5865F2)
    for opt in option_list:
        embed.add_field(name=f"🔹 {opt}", value="⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ **0** votes (0%)", inline=False)
    
    await channel.send(embed=embed, view=PollView(option_list, interaction.user))
    await interaction.response.send_message("✅ Poll created in the announcement channel.", ephemeral=True)

@bot.tree.command(name='announce_room', description="Announce a room opening and add to schedule")
@is_command_channel()
async def announce_room(interaction: discord.Interaction, category: str, room_name: str, start_time: str, end_time: str, link: str, description: str):
    ann_channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    sch_channel = bot.get_channel(SCHEDULE_CHANNEL_ID)
    server_icon = interaction.guild.icon.url if interaction.guild.icon else None
    
    # Main Announcement
    embed = discord.Embed(title=f"# 📢 ANNOUNCEMENT\n## 📂 TOPIC: {category}", color=0xFF2056)
    if server_icon: embed.set_thumbnail(url=server_icon)
    embed.add_field(name="📍 LOCATION", value=f"```\n{room_name}\n```", inline=False)
    embed.add_field(name="⏰ DURATION", value=f"⏳ **{start_time}** - **{end_time}**", inline=True)
    embed.add_field(name="📃 DOCUMENT", value=f"🔗 [View Here]({link})" if link != '-' else '-', inline=True)
    embed.add_field(name="🎯 INFORMATION", value=f"```fix\n{description}\n```", inline=False)
    embed.set_footer(text=f"By {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    # Schedule Entry
    embed1 = discord.Embed(title=f"# 📆 Schedule\n## 📂 TOPIC: {category}", description=description, color=0xB22222)
    embed1.add_field(name="📍 LOCATION", value=f"```\n{room_name}\n```", inline=False)
    embed1.add_field(name="⏰ TIME", value=f"⏳ {start_time} to {end_time}", inline=True)
    if link != '-': embed1.add_field(name="🔗 LINK", value=link, inline=False)

    if ann_channel: await ann_channel.send(embed=embed)
    if sch_channel: await sch_channel.send(embed=embed1)
    await interaction.response.send_message("✅ Room announcement sent successfully.", ephemeral=True)

@bot.tree.command(name='announce_normal', description="Send a general announcement")
@is_command_channel()
async def announce_normal(interaction: discord.Interaction, topic: str, to: str, content: str, document_link: str, extra_details: str):
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    server_icon = interaction.guild.icon.url if interaction.guild.icon else None
    
    embed = discord.Embed(
        title=f"# 📢 ANNOUNCEMENT\n## 📂 TOPIC: {topic}", 
        description="Please read the details below.", 
        color=0xFF2056
    )
    if server_icon: embed.set_thumbnail(url=server_icon)
    embed.add_field(name="To", value=f"```\n{to}\n```", inline=False)
    embed.add_field(name="Content", value=f"```\n{content}\n```", inline=False)
    embed.add_field(name="Document", value=f"🔗 [Open Link]({document_link})" if document_link != '-' else '-', inline=False)
    embed.add_field(name="Additional Info", value=f"```fix\n{extra_details}\n```", inline=False)
    embed.set_footer(text=f"Announced by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url, timestamp=discord.utils.utcnow())

    if channel:
        await channel.send(embed=embed)
        await interaction.response.send_message("✅ General announcement sent.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Announcement channel not found.", ephemeral=True)

@bot.tree.command(name='timer', description="Set a countdown timer with notification")
@is_command_channel()
async def timer(interaction: discord.Interaction, minutes: int, details: str = "Time is up!"):
    if minutes <= 0:
        return await interaction.response.send_message("❌ Please specify a time greater than 0 minutes.", ephemeral=True)
        
    await interaction.response.send_message(f"⏲️ Timer started for {minutes} minute(s): **{details}**")
    await asyncio.sleep(minutes * 60)
    await interaction.channel.send(f"🔔 {interaction.user.mention} **Time's up for: {details}**")

@bot.tree.command(name='role_summary', description="Summarize roles and member lists")
@is_command_channel()
async def role_summary(interaction: discord.Interaction):
    guild = interaction.guild
    roles = sorted(guild.roles, key=lambda r: r.position, reverse=True)
    embed = discord.Embed(title=f"📊 Role Summary: {guild.name}", color=discord.Color.blue())
    
    if guild.icon: embed.set_thumbnail(url=guild.icon.url)

    for role in roles:
        if role.is_default(): continue
        m_members = role.members
        m_list = [m.display_name for m in m_members]
        names = ", ".join(m_list[:10]) + ("..." if len(m_list) > 10 else "")
        
        humans = len([m for m in m_members if not m.bot])
        bots = len([m for m in m_members if m.bot])
        
        val = f"👤 Humans: {humans} | 🤖 Bots: {bots}\nMembers: `{names if names else 'No members'}`"
        embed.add_field(name=f"🏷️ {role.name} (Total {len(m_members)})", value=val, inline=False)
        
    await interaction.response.send_message(embed=embed)

# --- Member Search and Role Grant System ---
class RoleMemberModal(discord.ui.Modal, title='Search Member & Grant Role'):
    member_input = discord.ui.TextInput(label='Member Name or ID', placeholder='e.g. Somchai or 123456789', required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        query = self.member_input.value
        guild = interaction.guild
        member = None
        
        if query.isdigit():
            member = guild.get_member(int(query))
        else:
            member = discord.utils.get(guild.members, display_name=query)
        
        if not member:
            return await interaction.response.send_message(f"❌ Could not find member with Name/ID `{query}`", ephemeral=True)
            
        await interaction.response.send_message(f"👤 Found {member.mention}. Select the role to grant:", view=RoleSelectView(member), ephemeral=True)

class RoleSelectView(discord.ui.View):
    """View containing a dropdown to select a specific role for a member."""
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=60)
        self.target_member = target_member
        
    @discord.ui.select(
        placeholder="Select a role to grant...",
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
            return await interaction.response.send_message("❌ Role not found in this server.", ephemeral=True)
            
        try:
            await self.target_member.add_roles(role)
            await interaction.response.edit_message(content=f"✅ Successfully granted {role.mention} to {self.target_member.mention}!", view=None)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to grant role: {e}", ephemeral=True)

@bot.tree.command(name='give_role', description="Search for a member and select a role to grant")
@is_command_channel()
@app_commands.checks.has_permissions(manage_roles=True)
async def give_role(interaction: discord.Interaction):
    if not interaction.guild.me.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ Bot lacks 'Manage Roles' permission.", ephemeral=True)
    await interaction.response.send_modal(RoleMemberModal())

# --- Startup ---
server_on()
bot.run(os.getenv('TOKEN'))
