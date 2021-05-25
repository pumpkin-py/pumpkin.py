import datetime
import json
import re
import tempfile
from typing import Dict, List, Set, Tuple

import discord
from discord.ext import commands

from core import text, logging, utils
from database.acl import ACL_group, ACL_rule

tr = text.Translator(__file__).translate
bot_log = logging.Bot.logger()
guild_log = logging.Guild.logger()


class ACL(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    #

    @commands.guild_only()
    @commands.group(name="acl")
    async def acl_(self, ctx):
        """Permission controll."""
        await utils.Discord.send_help(ctx)

    @acl_.group(name="group")
    async def acl_group(self, ctx):
        """Permission group controll."""
        await utils.Discord.send_help(ctx)

    @acl_group.command(name="list")
    async def acl_group_list(self, ctx):
        """List permission groups."""
        groups = ACL_group.get_all(ctx.guild.id)

        if not len(groups):
            await ctx.reply(tr("acl group list", "none"))
            return

        # compute relationships between groups
        relationships: Dict[str, ACL_group] = dict()
        for group in groups:
            if group.name not in relationships:
                relationships[group.name]: List[ACL_group] = list()
            if group.parent is not None:
                if group.parent not in relationships:
                    relationships[group.parent]: List[ACL_group] = list()
                relationships[group.parent].append(group)

        # add relationships to group objects
        for group in groups:
            group.children = relationships[group.name]
            group.level = 0

        def bfs(queue: List[ACL_group]) -> List[ACL_group]:
            visited: List[ACL_group] = list()
            while queue:
                group = queue.pop(0)
                if group not in visited:
                    visited.append(group)
                    # build levels for indentation
                    for child in group.children:
                        child.level = group.level + 1
                    queue = group.children + queue
            return visited

        result = ""
        template = "{group_id:<2} {name:<20} {role:<18}"
        for group in bfs(groups):
            result += "\n" + template.format(
                group_id=group.id,
                name="  " * group.level + group.name,
                role=group.role_id,
            )

        await ctx.reply(f"```{result}```")

    @acl_group.command(name="get")
    async def acl_group_get(self, ctx, name: str):
        """Get ACL group."""
        group = ACL_group.get(ctx.guild.id, name)
        if group is None:
            await ctx.reply(tr("acl group get", "none"))
            return

        await ctx.reply(embed=self.get_group_embed(ctx, group))

    @acl_group.command(name="add")
    async def acl_group_add(self, ctx, name: str, parent: str, role_id: int):
        """Add ACL group.

        name: string matching `[a-zA-Z-]+`
        parent: ACL parent group name
        role_id: Discord role ID

        To unlink the group from the parent, set it to "".
        To set up virtual group with no link to Discord roles, set role_id to 0.
        """
        RE_NAME = r"[a-zA-Z-]+"
        if re.fullmatch(RE_NAME, name) is None:
            await ctx.reply(tr("acl group add", "bad name", regex=RE_NAME))
            return

        if len(parent) == 0:
            parent = None

        group = ACL_group.add(ctx.guild.id, name, parent, role_id)
        await ctx.reply(embed=self.get_group_embed(ctx, group))
        await guild_log.warning(
            ctx.author,
            ctx.channel,
            f'New ACL group "{name}".',
            group=group.to_dict(),
        )

    @acl_group.command(name="update")
    async def acl_group_update(self, ctx, name: str, param: str, value):
        """Update ACL group.

        name: name of group

        Options:
        name, string matching `[a-zA-Z-]+`
        parent, parent group name
        role_id, Discord role ID

        To unlink the group from any parents, set parent to "".
        To set up virtual group with no link to discord roles, set role_id to 0.
        """
        group = ACL_group.get(ctx.guild.id, name)
        if group is None:
            await ctx.reply(tr("acl group update", "none"))
            return

        if param == "name":
            RE_NAME = r"[a-zA-Z-]+"
            if re.fullmatch(RE_NAME, name) is None:
                await ctx.reply(tr("acl group update", "bad name", regex=RE_NAME))
                return
            group.name = value
        elif param == "parent":
            group.parent = value
        elif param == "role_id":
            group.role_id = int(value)
        else:
            await ctx.reply(tr("acl group update", "bad parameter"))
            return

        group.save()
        await ctx.reply(embed=self.get_group_embed(ctx, group))
        await guild_log.warning(
            ctx.author,
            ctx.channel,
            f'ACL group "{group.name}" updated.',
            group=group.to_dict(),
        )

    @acl_group.command(name="remove")
    async def acl_group_remove(self, ctx, name: str):
        """Remove ACL group."""
        result = ACL_group.remove(ctx.guild.id, name)
        if result < 0:
            await ctx.reply(tr("acl group remove", "none"))
            return

        await ctx.reply(tr("acl group remove", "reply"))
        await guild_log.warning(ctx.author, ctx.channel, f'ACL group "{name}" removed.')

    #

    @acl_.group(name="rule")
    async def acl_rule(self, ctx):
        await utils.Discord.send_help(ctx)

    @acl_rule.command(name="export")
    async def acl_rule_export(self, ctx):
        """Export command rules."""
        timestamp: str = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        filename: str = f"acl_{ctx.guild.id}_{timestamp}.json"

        rules: list = ACL_rule.get_all(ctx.guild.id)
        export: Dict[str, dict] = dict()

        for rule in rules:
            rule_dict = rule.to_dict()
            del rule_dict["id"]
            del rule_dict["command"]
            del rule_dict["guild_id"]
            export["command"] = rule_dict

        file = tempfile.TemporaryFile(mode="w+")
        json.dump(export, file, indent="\t", sort_keys=True)

        file.seek(0)
        await ctx.reply(
            tr("acl rule export", "reply", count=len(rules)),
            file=discord.File(fp=file, filename=filename),
        )
        file.close()
        await guild_log.info(ctx.author, ctx.channel, "ACL rules exported.")

    @acl_rule.command(name="remove")
    async def acl_rule_remove(self, ctx, *, command: str):
        """Remove command."""
        count = ACL_rule.remove(ctx.guild.id, command)
        if count < 1:
            await ctx.reply(tr("acl rule remove", "none"))
            return

        await ctx.reply(tr("acl rule remove", "reply"))
        await guild_log.warning(ctx.author, ctx.channel, f"ACL rule {command} removed.")

    @acl_rule.command(name="flush")
    async def acl_rule_flush(self, ctx):
        """Flush all the command rules."""

        # export the rules, just to make sure
        await self.acl_rule_export(ctx)

        # delete all
        count = ACL_rule.remove_all(ctx.guild.id)
        await ctx.send(tr("acl rule flush", "reply", count=count))
        await guild_log.info(ctx.author, ctx.channel, "ACL rules flushed.")

    @acl_rule.command(name="import")
    async def acl_rule_import(self, ctx, mode: str):
        """Add new rules from JSON file.

        Existing rules are skipped, unless you pass "replace" as mode parameter.
        """
        if len(ctx.message.attachments) != 1:
            await ctx.reply(tr("acl rule import", "wrong file"))
            return
        if not ctx.message.attachments[0].filename.lower().endswith("json"):
            await ctx.reply(tr("acl rule import", "wrong json"))
            return

        # download the file
        data_file = tempfile.TemporaryFile()
        await ctx.message.attachments[0].save(data_file)
        data_file.seek(0)
        try:
            json_data = json.load(data_file)
        except json.decoder.JSONDecodeError as exc:
            await ctx.reply(tr("acl rule import", "bad json") + f"\n> `{str(exc)}`")
            return

        new, updated, rejected = await self.import_rules(
            ctx, json_data, replace=(mode == "replace")
        )
        data_file.close()

        await ctx.reply(
            tr(
                "acl rule import",
                "reply",
                new=len(new),
                updated=len(updated),
            )
        )

        result = tr("acl rule import", "skip") + ":\n> "
        result += ", ".join([f"{command} ({reason})" for (command, reason) in rejected])
        if len(result):
            for stub in utils.Text.split(result):
                await ctx.send(stub)

        await guild_log.warning(
            ctx.author,
            ctx.channel,
            f"ACL rule import: {len(new)} added, {len(updated)} updated.",
        )

    #

    def get_group_embed(self, ctx, group: ACL_group) -> discord.Embed:
        group_dict: dict = group.to_dict()

        embed = utils.Discord.create_embed(
            author=ctx.author,
            title=tr("group embed", "title", name=group_dict["name"]),
        )

        role = ctx.guild.get_role(group_dict["role_id"])
        if role is not None:
            embed.add_field(
                name=tr("group embed", "role"),
                value=f"{role.name} ({role.id})",
                inline=False,
            )

        if group_dict["parent"] is not None:
            embed.add_field(
                name=tr("group embed", "parent"),
                value=group_dict["parent"],
                inline=False,
            )

        return embed

    def import_rules(
        self, guild_id: int, data: dict, mode: str = "add"
    ) -> Tuple[List[str], List[str], List[Tuple[str, str]]]:
        """Import JSON rules.

        Returns
        -------
        list: New commands
        list: Updated commands
        list: Rejected commands as (command, reason) tuples
        """
        result_new: list = list()
        result_upd: list = list()
        result_rej: Dict[str, Set[str]] = dict()
        for reason in ("not bool", "not list", "not group", "not user id", "duplicate"):
            result_rej[reason]: Set[str] = set()

        acl_groups: List[str] = [g.name for g in ACL_group.get_all(guild_id)]

        for command, attributes in data.items():
            bad: bool = False

            # booleans
            if getattr(attributes, "default", False) not in (True, False):
                result_rej["not bool"].add(command)
                bad = True

            # lists
            for keyword in ("users_allow", "users_deny", "groups_allow", "groups_deny"):
                if type(getattr(attributes, keyword, [])) != list:
                    result_rej["not list"].add(command)
                    bad = True

            # groups
            for keyword in ("groups_allow", "groups_deny"):
                for group in getattr(attributes, keyword, []):
                    if group not in acl_groups:
                        result_rej["not group"].add(command)
                        bad = True

            # users
            for keyword in ("users_allow", "users_deny"):
                for user_id in getattr(attributes, keyword, []):
                    if type(user_id) != int:
                        result_rej["not user id"].add(command)
                        bad = True

            if bad:
                continue

            # add new rule
            if ACL_rule.get(guild_id, command) is not None and mode != "replace":
                result_rej["duplicate"].add(command)
                continue

            rule: ACL_rule = ACL_rule.add(guild_id, command, getattr(attributes, "default", False))
            # add rule groups
            for group in getattr(attributes, "groups_allow", []):
                pass


def setup(bot) -> None:
    bot.add_cog(ACL(bot))