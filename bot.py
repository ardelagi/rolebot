import discord
from discord.ext import commands
from discord import app_commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
HELPER_ROLE_ID = int(os.getenv('HELPER_ROLE_ID'))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID'))
PANEL_CHANNEL_ID = int(os.getenv('PANEL_CHANNEL_ID'))

# Manageable roles
MANAGEABLE_ROLES = {
    'GOVERNMENT': int(os.getenv('ROLE_A_ID')),
    'LAWMEN': int(os.getenv('ROLE_B_ID')),
    'MEDIC': int(os.getenv('ROLE_C_ID')),
}

# Bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


class RoleManagementView(discord.ui.View):
    """Main view with role select and user select"""
    def __init__(self):
        super().__init__(timeout=None)
        self.selected_role = None
        self.selected_action = None
        
        # Dropdown to select role to give
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
        
        # Dropdown to select role to remove
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
        
        # User Select to choose target member
        user_select = discord.ui.UserSelect(
            placeholder="Select target member",
            custom_id="user_select",
            min_values=1,
            max_values=1,
            row=2
        )
        user_select.callback = self.user_select_callback
        self.add_item(user_select)
    
    async def role_select_callback(self, interaction: discord.Interaction):
        """Callback when role is selected"""
        # Verify Helper role
        helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
        if helper_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ You don't have permission to use this panel!",
                ephemeral=True
            )
            return
        
        selected = interaction.data['values'][0]
        
        # Parse action and role_id
        if selected.startswith('give_'):
            self.selected_action = "give"
            role_id = int(selected.replace('give_', ''))
            action_text = "give"
        else:
            self.selected_action = "remove"
            role_id = int(selected.replace('remove_', ''))
            action_text = "remove"
        
        self.selected_role = role_id
        
        # Get role name
        role_name = [name for name, rid in MANAGEABLE_ROLES.items() if rid == role_id][0]
        role = interaction.guild.get_role(role_id)
        
        # Store in interaction for later use
        interaction.client.temp_data = {
            'user_id': interaction.user.id,
            'role_id': role_id,
            'role_name': role_name,
            'action': self.selected_action
        }
        
        await interaction.response.send_message(
            f"✅ Role **{role.mention}** selected to {action_text}.\n"
            f"👉 Now select the target member using the **User Select** dropdown below.",
            ephemeral=True
        )
    
    async def user_select_callback(self, interaction: discord.Interaction):
        """Callback when user is selected"""
        # Verify Helper role
        helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
        if helper_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ You don't have permission to use this panel!",
                ephemeral=True
            )
            return
        
        # Check if role was selected first
        temp_data = getattr(interaction.client, 'temp_data', None)
        if not temp_data or temp_data['user_id'] != interaction.user.id:
            await interaction.response.send_message(
                "❌ Please select a role first from the dropdown above!",
                ephemeral=True
            )
            return
        
        # Get selected user
        target_member = interaction.data['resolved']['users'].values()
        target_member = list(target_member)[0]
        target_member = await interaction.guild.fetch_member(int(target_member['id']))
        
        # Get role info from temp data
        role_id = temp_data['role_id']
        role_name = temp_data['role_name']
        action = temp_data['action']
        
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message(
                "❌ Role not found in server!",
                ephemeral=True
            )
            return
        
        # Check if bot
        if target_member.bot:
            await interaction.response.send_message(
                "❌ Cannot assign roles to bots!",
                ephemeral=True
            )
            return
        
        # Perform action
        try:
            if action == "give":
                if role in target_member.roles:
                    await interaction.response.send_message(
                        f"ℹ️ {target_member.mention} already has the **{role.name}** role",
                        ephemeral=True
                    )
                    return
                await target_member.add_roles(role)
                action_text = "given"
                action_preposition = "to"
                emoji = "✅"
                log_color = discord.Color.green()
                log_title = "Role Given"
            else:  # remove
                if role not in target_member.roles:
                    await interaction.response.send_message(
                        f"ℹ️ {target_member.mention} doesn't have the **{role.name}** role",
                        ephemeral=True
                    )
                    return
                await target_member.remove_roles(role)
                action_text = "removed"
                action_preposition = "from"
                emoji = "🗑️"
                log_color = discord.Color.orange()
                log_title = "Role Removed"
            
            # Send confirmation to helper
            await interaction.response.send_message(
                f"{emoji} **Success!**\n"
                f"Action: {action_text.capitalize()} role **{role.name}** {action_preposition} {target_member.mention}\n"
                f"Helper: {interaction.user.mention}",
                ephemeral=True
            )
            
            # Send log to admin channel
            log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title=f"📋 {log_title}",
                    color=log_color,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(
                    name="👤 Helper",
                    value=f"{interaction.user.mention}\n`{interaction.user.name}` (ID: {interaction.user.id})",
                    inline=False
                )
                log_embed.add_field(
                    name="🎯 Target Member",
                    value=f"{target_member.mention}\n`{target_member.name}` (ID: {target_member.id})",
                    inline=False
                )
                log_embed.add_field(
                    name="🏷️ Role",
                    value=f"{role.mention}\n`{role.name}` (ID: {role.id})",
                    inline=False
                )
                log_embed.add_field(
                    name="⚡ Action",
                    value=f"**{action_text.upper()}**",
                    inline=False
                )
                log_embed.set_thumbnail(url=target_member.display_avatar.url)
                log_embed.set_footer(
                    text=f"Helper: {interaction.user.name}",
                    icon_url=interaction.user.display_avatar.url
                )
                
                await log_channel.send(embed=log_embed)
            
            # Clear temp data
            delattr(interaction.client, 'temp_data')
                
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot doesn't have permission to manage this role!\n"
                "Make sure the bot's role is higher than the managed role.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}",
                ephemeral=True
            )


@bot.event
async def on_ready():
    print(f'✅ Bot {bot.user} is now online!')
    print(f'📊 Connected to {len(bot.guilds)} server(s)')
    
    # Add persistent views
    bot.add_view(RoleManagementView())
    print('✅ Persistent views loaded')
    
    # Sync commands
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'❌ Error syncing commands: {e}')


@bot.tree.command(name="setup_panel", description="Setup role helper panel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    """Setup panel for Helpers"""
    channel = interaction.guild.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(
            "❌ Panel channel not found! Check PANEL_CHANNEL_ID in .env",
            ephemeral=True
        )
        return
    
    # Create embed
    embed = discord.Embed(
        title="Role Management Panel",
        description=(
            "**How to Use:**\n"
            "1️⃣ Select a role from the first or second dropdown\n"
            "2️⃣ Select the target member from the **User Select** dropdown\n"
            "3️⃣ The role will be automatically given/removed\n\n"
            "✅ **Top Dropdown**: Give role\n"
            "🗑️ **Middle Dropdown**: Remove role\n"
            "👥 **Bottom Dropdown**: Select target member\n\n"
            "**Manageable Roles:**"
        ),
        color=discord.Color.blue()
    )
    
    # Add available roles to embed
    for role_name, role_id in MANAGEABLE_ROLES.items():
        role = interaction.guild.get_role(role_id)
        if role:
            embed.add_field(name=role_name, value=role.mention, inline=True)
    
    embed.set_footer(text="This panel can only be used by Helper role")
    
    # Send panel
    view = RoleManagementView()
    await channel.send(embed=embed, view=view)
    
    await interaction.response.send_message(
        f"✅ Panel successfully created in {channel.mention}!",
        ephemeral=True
    )


@bot.tree.command(name="refresh_panel", description="Refresh persistent views (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def refresh_panel(interaction: discord.Interaction):
    """Refresh views to persist after bot restart"""
    bot.add_view(RoleManagementView())
    await interaction.response.send_message(
        "✅ Panel views have been refreshed and are ready to use!",
        ephemeral=True
    )


# Run bot
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
