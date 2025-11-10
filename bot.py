import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Optional

load_dotenv()

# Configuration from .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
HELPER_ROLE_ID = int(os.getenv('HELPER_ROLE_ID'))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID'))
PANEL_CHANNEL_ID = int(os.getenv('PANEL_CHANNEL_ID'))

# Manageable roles
MANAGEABLE_ROLES = {
    'GOVERNMENT': int(os.getenv('GOVERNMENT')),
    'LAWMAN': int(os.getenv('LAWMAN')),
    'MEDIC': int(os.getenv('MEDIC')),
}

PANEL_DATA_FILE = 'panel_data.json'

# Bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


class PanelDataManager:
    
    @staticmethod
    def load():
        try:
            if os.path.exists(PANEL_DATA_FILE):
                with open(PANEL_DATA_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load panel data: {e}")
        return {}
    
    @staticmethod
    def save(data):
        try:
            with open(PANEL_DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save panel data: {e}")
    
    @staticmethod
    def get_message_id():
        data = PanelDataManager.load()
        return data.get('panel_message_id')
    
    @staticmethod
    def set_message_id(message_id: int):
        data = PanelDataManager.load()
        data['panel_message_id'] = message_id
        PanelDataManager.save(data)


class TempDataManager:
    def __init__(self):
        self.data = {}
        self.timestamps = {}
        self._task_started = False
    
    def start_cleanup(self):
        if not self._task_started:
            self.cleanup_task.start()
            self._task_started = True
    
    def set(self, user_id: int, data: dict):
        self.data[user_id] = data
        self.timestamps[user_id] = datetime.utcnow()
    
    def get(self, user_id: int) -> Optional[dict]:
        return self.data.get(user_id)
    
    def delete(self, user_id: int):
        self.data.pop(user_id, None)
        self.timestamps.pop(user_id, None)
    
    @tasks.loop(minutes=5)
    async def cleanup_task(self):
        now = datetime.utcnow()
        expired = [
            uid for uid, ts in self.timestamps.items()
            if now - ts > timedelta(minutes=10)
        ]
        for uid in expired:
            self.delete(uid)
        if expired:
            print(f"🧹 Cleaned up {len(expired)} expired temp data entries")


class ConfirmButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.value = None
    
    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.send_message("❌ Action cancelled", ephemeral=True)


class RoleManagementView(discord.ui.View):
    def __init__(self, temp_data_manager: TempDataManager):
        super().__init__(timeout=None)
        self.temp_data_manager = temp_data_manager
        
        # Dropdown untuk tambah role
        give_role_options = [
            discord.SelectOption(
                label=name,
                value=f"give_{role_id}",
                description=f"Give {name} role",
                emoji="✅"
            )
            for name, role_id in MANAGEABLE_ROLES.items()
        ]
        give_role_select = discord.ui.Select(
            placeholder="Select role to GIVE",
            options=give_role_options,
            custom_id="give_role_select",
            row=0
        )
        give_role_select.callback = self.role_select_callback
        self.add_item(give_role_select)
        
        # Dropdown untuk hapus role
        remove_role_options = [
            discord.SelectOption(
                label=name,
                value=f"remove_{role_id}",
                description=f"Remove {name} role",
                emoji="🗑️"
            )
            for name, role_id in MANAGEABLE_ROLES.items()
        ]
        remove_role_select = discord.ui.Select(
            placeholder="Select role to REMOVE",
            options=remove_role_options,
            custom_id="remove_role_select",
            row=1
        )
        remove_role_select.callback = self.role_select_callback
        self.add_item(remove_role_select)
        
        # User select
        user_select = discord.ui.UserSelect(
            placeholder="Select one or more target members",
            custom_id="user_select",
            min_values=1,
            max_values=10,
            row=2
        )
        user_select.callback = self.user_select_callback
        self.add_item(user_select)

    def has_permission(self, interaction: discord.Interaction) -> bool:
        helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
        is_admin = interaction.user.guild_permissions.administrator
        has_helper = helper_role in interaction.user.roles if helper_role else False
        return is_admin or has_helper

    async def role_select_callback(self, interaction: discord.Interaction):
        # Permission check
        if not self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ You don't have permission to use this panel!", 
                ephemeral=True
            )
            return
        
        selected = interaction.data['values'][0]
        action = "give" if selected.startswith('give_') else "remove"
        role_id = int(selected.replace(f'{action}_', ''))
        
        # Find role name
        role_name = next(
            (name for name, rid in MANAGEABLE_ROLES.items() if rid == role_id),
            "Unknown"
        )
        role = interaction.guild.get_role(role_id)
        
        if not role:
            await interaction.response.send_message(
                "❌ Role not found in server!", 
                ephemeral=True
            )
            return
        
        # Check bot permissions
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"❌ I cannot manage {role.mention} - it's higher than my highest role!",
                ephemeral=True
            )
            return
        
        # Store temp data
        self.temp_data_manager.set(interaction.user.id, {
            'role_id': role_id,
            'role_name': role_name,
            'action': action,
            'role_mention': role.mention
        })
        
        await interaction.response.send_message(
            f"✅ Role **{role.mention}** selected to **{action.upper()}**.\n"
            "👉 Now select one or more target members using the dropdown below.",
            ephemeral=True
        )

    async def user_select_callback(self, interaction: discord.Interaction):
        # Permission check
        if not self.has_permission(interaction):
            await interaction.response.send_message(
                "❌ You don't have permission to use this panel!", 
                ephemeral=True
            )
            return

        temp_data = self.temp_data_manager.get(interaction.user.id)
        if not temp_data:
            await interaction.response.send_message(
                "❌ Please select a role first!", 
                ephemeral=True
            )
            return

        selected_user_ids = interaction.data['values']
        role_id = temp_data['role_id']
        role_name = temp_data['role_name']
        action = temp_data['action']
        role = interaction.guild.get_role(role_id)

        # PERBAIKAN: Defer immediately untuk menghindari timeout
        await interaction.response.defer(ephemeral=True)

        # Confirmation for bulk actions (more than 3 users)
        if len(selected_user_ids) > 3:
            confirm_view = ConfirmButton()
            confirm_message = await interaction.followup.send(
                f"⚠️ You are about to **{action}** {role.mention} for **{len(selected_user_ids)} members**.\n\n"
                "Are you sure?",
                view=confirm_view,
                ephemeral=True,
                wait=True
            )
            
            await confirm_view.wait()
            if not confirm_view.value:
                await confirm_message.edit(content="❌ Action cancelled", view=None)
                return
            
            # Delete confirmation message
            try:
                await confirm_message.delete()
            except:
                pass

        # Process actions
        success_list = []
        failed_list = []

        for user_id in selected_user_ids:
            try:
                member = await interaction.guild.fetch_member(int(user_id))
                
                # Check if target is bot
                if member.bot:
                    failed_list.append(f"{member.mention} (cannot manage bots)")
                    continue
                
                # Check role hierarchy
                if member.top_role >= interaction.guild.me.top_role:
                    failed_list.append(f"{member.mention} (higher role than bot)")
                    continue

                if action == "give":
                    if role in member.roles:
                        failed_list.append(f"{member.mention} (already has role)")
                        continue
                    await member.add_roles(role, reason=f"Role management by {interaction.user}")
                else:
                    if role not in member.roles:
                        failed_list.append(f"{member.mention} (no role to remove)")
                        continue
                    await member.remove_roles(role, reason=f"Role management by {interaction.user}")
                
                success_list.append(member.mention)

            except discord.Forbidden:
                failed_list.append(f"<@{user_id}> (permission denied)")
            except discord.HTTPException:
                failed_list.append(f"<@{user_id}> (network error)")
            except Exception as e:
                failed_list.append(f"<@{user_id}> (error: {type(e).__name__})")

        # Build result embed
        summary_embed = discord.Embed(
            title=f"🔄 Bulk Role {action.capitalize()} Results",
            color=discord.Color.green() if action == "give" else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        
        summary_embed.add_field(
            name=f"✅ Success ({len(success_list)})", 
            value="\n".join(success_list) or "*None*", 
            inline=False
        )
        summary_embed.add_field(
            name=f"❌ Failed ({len(failed_list)})", 
            value="\n".join(failed_list) or "*None*", 
            inline=False
        )
        summary_embed.add_field(name="🏷️ Role", value=role.mention, inline=True)
        summary_embed.add_field(
            name="👤 Performed by", 
            value=interaction.user.mention, 
            inline=True
        )

        # Send result to user
        await interaction.followup.send(embed=summary_embed, ephemeral=True)

        # Send to log channel
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(embed=summary_embed)
            except Exception as e:
                print(f"❌ Failed to send log: {e}")

        # Cleanup temp data
        self.temp_data_manager.delete(interaction.user.id)


# Initialize temp data manager
temp_data_manager = TempDataManager()


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    temp_data_manager.start_cleanup()
    bot.add_view(RoleManagementView(temp_data_manager))
    
    await restore_panel()
    
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} command(s) to guild {GUILD_ID}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")


async def restore_panel():
    try:
        message_id = PanelDataManager.get_message_id()
        if not message_id:
            print("ℹ️ No saved panel message found")
            return
        
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print("❌ Guild not found")
            return
        
        channel = guild.get_channel(PANEL_CHANNEL_ID)
        if not channel:
            print("❌ Panel channel not found")
            return
        
        try:
            message = await channel.fetch_message(message_id)
            
            embed = message.embeds[0] if message.embeds else create_panel_embed(guild)
            await message.edit(embed=embed, view=RoleManagementView(temp_data_manager))
            print(f"✅ Panel restored from message ID: {message_id}")
            
        except discord.NotFound:
            print("⚠️ Saved panel message not found, will need to create new one")
            PanelDataManager.set_message_id(None)
        except discord.Forbidden:
            print("❌ No permission to edit panel message")
            
    except Exception as e:
        print(f"⚠️ Failed to restore panel: {e}")


def create_panel_embed(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(
        title="Role Management Panel",
        description=(
            "**How to use:**\n"
            "1️⃣ Select a role action (give/remove)\n"
            "2️⃣ Select one or more members (up to 10)\n"
            "3️⃣ Confirm if bulk action (>3 members)\n\n"
            "✅ **Top dropdown:** Give Role\n"
            "🗑️ **Middle dropdown:** Remove Role\n"
            "👥 **Bottom dropdown:** Select Members\n\n"
            "**Manageable Roles:**"
        ),
        color=discord.Color.blue()
    )

    for name, role_id in MANAGEABLE_ROLES.items():
        role = guild.get_role(role_id)
        if role:
            embed.add_field(name=name, value=role.mention, inline=True)

    embed.set_footer(text="Motion County Role Management")
    return embed


@bot.tree.command(name="setup_panel", description="Setup role helper panel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    channel = interaction.guild.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            "❌ Panel channel not found! Check PANEL_CHANNEL_ID in .env", 
            ephemeral=True
        )
        return

    # Check if panel already exists
    existing_message_id = PanelDataManager.get_message_id()
    if existing_message_id:
        try:
            existing_message = await channel.fetch_message(existing_message_id)
            await interaction.response.send_message(
                f"⚠️ Panel already exists! [Jump to message]({existing_message.jump_url})\n"
                f"Use `/refresh_panel` to update it, or delete it manually first.",
                ephemeral=True
            )
            return
        except discord.NotFound:
            pass

    embed = create_panel_embed(interaction.guild)
    
    try:
        message = await channel.send(embed=embed, view=RoleManagementView(temp_data_manager))
        
        PanelDataManager.set_message_id(message.id)
        
        await interaction.response.send_message(
            f"✅ Panel successfully created in {channel.mention}\n"
            f"Message ID `{message.id}` has been saved.",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ I don't have permission to send messages in that channel!", 
            ephemeral=True
        )


@bot.tree.command(name="list_roles", description="List all manageable roles and their members")
async def list_roles(interaction: discord.Interaction):
    helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
    is_admin = interaction.user.guild_permissions.administrator
    has_helper = helper_role in interaction.user.roles if helper_role else False
    
    if not (is_admin or has_helper):
        await interaction.response.send_message(
            "❌ You need Admin or Helper role to use this command!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    embed = discord.Embed(
        title="Manageable Roles Overview",
        color=discord.Color.teal(),
        timestamp=discord.utils.utcnow()
    )
    
    total_members = 0
    
    for name, role_id in MANAGEABLE_ROLES.items():
        role = interaction.guild.get_role(role_id)
        if not role:
            embed.add_field(name=name, value="❌ Role not found", inline=False)
            continue

        members = role.members
        total_members += len(members)
        
        if len(members) == 0:
            value = "*No members have this role*"
        elif len(members) <= 10:
            value = "\n".join([m.mention for m in members])
        else:
            value = "\n".join([m.mention for m in members[:10]])
            value += f"\n*...and {len(members) - 10} more*"
        
        embed.add_field(
            name=f"{role.name} ({len(members)} members)", 
            value=value, 
            inline=False
        )

    embed.description = f"**Total members with managed roles:** {total_members}"
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="refresh_panel", description="Refresh existing panel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def refresh_panel(interaction: discord.Interaction):
    message_id = PanelDataManager.get_message_id()
    
    if not message_id:
        await interaction.response.send_message(
            "❌ No panel message found! Use `/setup_panel` first.",
            ephemeral=True
        )
        return
    
    channel = interaction.guild.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            "❌ Panel channel not found!",
            ephemeral=True
        )
        return
    
    try:
        message = await channel.fetch_message(message_id)
        embed = create_panel_embed(interaction.guild)
        await message.edit(embed=embed, view=RoleManagementView(temp_data_manager))
        
        await interaction.response.send_message(
            f"✅ Panel refreshed successfully! [Jump to panel]({message.jump_url})",
            ephemeral=True
        )
    except discord.NotFound:
        await interaction.response.send_message(
            "❌ Panel message not found! It may have been deleted.\n"
            "Use `/setup_panel` to create a new one.",
            ephemeral=True
        )
        PanelDataManager.set_message_id(None)
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Failed to refresh panel: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="role_stats", description="View role management statistics")
async def role_stats(interaction: discord.Interaction):
    helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
    is_admin = interaction.user.guild_permissions.administrator
    has_helper = helper_role in interaction.user.roles if helper_role else False
    
    if not (is_admin or has_helper):
        await interaction.response.send_message(
            "❌ You need Admin or Helper role to use this command!",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="Role Statistics",
        description="Statistics for manageable roles only",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    
    total_with_roles = 0
    
    for name, role_id in MANAGEABLE_ROLES.items():
        role = interaction.guild.get_role(role_id)
        if role:
            member_count = len(role.members)
            total_with_roles += member_count
            percentage = (member_count / interaction.guild.member_count) * 100
            
            # Bar visualization
            bar_length = int(percentage / 5)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            
            embed.add_field(
                name=f"{name} - {role.name}",
                value=f"{bar}\n👥 {member_count} members ({percentage:.1f}%)",
                inline=False
            )
    
    embed.set_footer(text=f"Total: {total_with_roles} members • Requested by {interaction.user.name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command(name="rek")
async def rekening_command(ctx):
    """Command !rek untuk menampilkan informasi rekening"""
    embed = discord.Embed(
        title="💳 Rekening",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(
        name="Nomor Rekening",
        value="`90190172055`",
        inline=False
    )
    
    embed.add_field(
        name="Bank",
        value="Jenius",
        inline=False
    )
    
    embed.add_field(
        name="Atas Nama",
        value="Rio Djaja",
        inline=False
    )
    
    embed.set_footer(text="Motion County Donation")
    
    await ctx.send(embed=embed)


@bot.tree.command(name="delete_panel", description="Delete saved panel message ID (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def delete_panel(interaction: discord.Interaction):
    message_id = PanelDataManager.get_message_id()
    
    if not message_id:
        await interaction.response.send_message(
            "❌ No panel message ID saved!",
            ephemeral=True
        )
        return
    
    channel = interaction.guild.get_channel(PANEL_CHANNEL_ID)
    if channel:
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except discord.NotFound:
            pass
        except Exception as e:
            await interaction.response.send_message(
                f"⚠️ Could not delete message: {e}\nClearing saved ID anyway.",
                ephemeral=True
            )
    
    PanelDataManager.set_message_id(None)
    await interaction.response.send_message(
        "✅ Panel message ID cleared! Use `/setup_panel` to create a new one.",
        ephemeral=True
    )


# Error handlers
@setup_panel.error
@refresh_panel.error
@delete_panel.error
async def admin_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need Administrator permission to use this command!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ An error occurred: {str(error)}",
            ephemeral=True
        )
        print(f"Error in command: {error}")


if __name__ == "__main__":
    bot.run(BOT_TOKEN)