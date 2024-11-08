import collections
import logging
import os
import secrets
from io import BytesIO, StringIO

import discord
import requests
from discord.ext import commands
from preston import Preston

from assets import Assets
from callback_server import callback_server
from models import initialize_database, User, Challenge

# Configure the logger
logger = logging.getLogger('discord.main')
logger.setLevel(logging.INFO)

# Initialize the database
initialize_database()

# Setup ESI connection
base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_assets.v1",
)

corp_base_preston = Preston(
    user_agent="Hangar organizing discord bot by larynx.austrene@gmail.com",
    client_id=os.environ["CCP_CLIENT_ID"],
    client_secret=os.environ["CCP_SECRET_KEY"],
    callback_url=os.environ["CCP_REDIRECT_URI"],
    scope="esi-assets.read_corporation_assets.v1",
)

# Setup Discord
intent = discord.Intents.default()
intent.messages = True
intent.message_content = True
bot = commands.Bot(command_prefix='!', intents=intent)


def with_refresh(preston_instance, refresh_token: str):
    new_kwargs = dict(preston_instance._kwargs)
    new_kwargs["refresh_token"] = refresh_token
    new_kwargs["access_token"] = None
    return Preston(**new_kwargs)


async def get_author_assets(author_id: int):
    user = User.get_or_none(User.user_id == str(author_id))
    if user:
        for character in user.characters:
            a = Assets(with_refresh(base_preston, character.token))
            await a.fetch()
            yield a
        for corporation_character in user.corporation_characters:
            try:
                a = Assets(with_refresh(corp_base_preston, corporation_character.token))
                await a.fetch()
            except AssertionError:
                corporation_character.delete_instance()
            else:
                yield a


async def send_large_message(ctx, message, max_chars=2000):
    while len(message) > 0:
        if len(message) <= max_chars:
            await ctx.send(message)
            break

        last_newline_index = message.rfind('\n', 0, max_chars)

        if last_newline_index == -1:
            await ctx.send(message[:max_chars])
            message = message[max_chars:]
        else:
            await ctx.send(message[:last_newline_index])
            message = message[last_newline_index + 1:]


@bot.event
async def on_ready():
    callback_server.start(base_preston)


@bot.command()
async def state(ctx):
    """Returns the current state of all your ships in yaml format. (Useful for first setting things up)"""
    logger.info(f"{ctx.author.name} used !state")

    await ctx.send("Fetching assets...")
    files_to_send = []

    async for assets in get_author_assets(ctx.author.id):
        if assets.is_corporation:
            filename = f"{assets.corporation_name}.yaml"
        else:
            filename = f"{assets.character_name}.yaml"

        yaml_text = assets.save_requirement()
        discord_file = discord.File(StringIO(yaml_text), filename=filename)

        files_to_send.append(discord_file)

    if files_to_send:
        await ctx.send("Here are your current ship states.", files=files_to_send)
    else:
        await ctx.send("You have no authorized characters!")


@bot.command()
async def check(ctx):
    """Returns a bullet point list of what ships are missing things."""
    logger.info(f"{ctx.author.name} used !check")

    await ctx.send("Fetching assets...")
    has_characters = False
    has_errors = False
    message = ""
    async for assets in get_author_assets(ctx.author.id):
        has_characters = True
        if assets.is_corporation:
            name = f"\n## {assets.corporation_name}:\n"
        else:
            name = f"\n## {assets.character_name}\n"

        user = User.get_or_none(User.user_id == str(ctx.author.id))
        if user and user.requirements_file:
            for ship_error_message in assets.check_requirement(user.requirements_file):
                has_errors = True

                if len(message) + len(ship_error_message) + len(name) > 1990:
                    await ctx.send(message)
                    message = ""

                if len(name) > 0:
                    message += name
                    name = ""

                message += f"{ship_error_message}\n"
        else:
            await ctx.send("You have not set a requirements file, use the !set command and upload one!")

    if has_characters:
        if has_errors:
            await ctx.send(message)
        else:
            await ctx.send("**No State Errors found!**")
    else:
        await ctx.send("You have no authorized characters!")


@bot.command()
async def buy(ctx):
    """Returns a multibuy of all the things missing in your ships."""
    logger.info(f"{ctx.author.name} used !buy")

    await ctx.send("Fetching assets...")
    buy_list = collections.Counter()
    has_characters = False
    async for assets in get_author_assets(ctx.author.id):
        has_characters = True

        # Get the user's requirements from the database
        user = User.get_or_none(User.user_id == str(ctx.author.id))
        if user and user.requirements_file:
            buy_list = assets.get_buy_list(user.requirements_file, buy_list=buy_list)
        else:
            await ctx.send("You have not set a requirements file, use the !set command and upload one!")

    buy_list_body = "\n".join([f"{item} {amount}" for item, amount in buy_list.items()])
    if buy_list_body:
        await send_large_message(ctx, f"**Buy List:**\n```{buy_list_body}```")
    else:
        if has_characters:
            await ctx.send("**Nothing to buy!**")
        else:
            await ctx.send("You have no authorized characters!")


@bot.command()
async def set(ctx, attachment: discord.Attachment):
    """Sets your current requirement file to the one attached to this command."""
    logger.info(f"{ctx.author.name} used !set")

    if attachment:
        response = requests.get(attachment.url, allow_redirects=True)
        requirements_content = response.content.decode('utf-8')  # Decode the content to a string

        # Upsert the user's requirements file into the database
        user = User.get_or_none(user_id=str(ctx.author.id))
        if user:
            user.requirements_file = requirements_content
            user.save()
            await ctx.send("Set new requirements file!")
        else:
            await ctx.send("You currently have no linked characters, so having requirements makes no sense.")

    else:
        await ctx.send("You forgot to attach a new requirement file!")


@bot.command()
async def get(ctx):
    """Returns your current requirements."""
    logger.info(f"{ctx.author.name} used !get")

    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user and user.requirements_file:
        requirements = discord.File(fp=BytesIO(user.requirements_file.encode('utf-8')), filename="requirements.yaml")
        await ctx.send("Here is your current requirement file.", file=requirements)
    else:
        await ctx.send("You don't have a requirements file set.")


@bot.command()
async def auth(ctx, corporation=False):
    """Sends you an authorization link for a character.
    :corporation: Set true if you want to authorize for your corporation"""
    logger.info(f"{ctx.author.name} used !auth")

    secret_state = secrets.token_urlsafe(60)

    user, created = User.get_or_create(user_id=str(ctx.author.id))
    Challenge.delete().where(Challenge.user == user).execute()
    Challenge.create(user=user, state=secret_state)

    if corporation:
        full_link = f"{corp_base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(
            f"Use this [authentication link]({full_link}) to authorize a character in your corporation "
            f"with the required role (Accountant).")
    else:
        full_link = f"{base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(f"Use this [authentication link]({full_link}) to authorize your characters.")


@bot.command()
async def characters(ctx):
    """Displays your currently authorized characters."""
    logger.info(f"{ctx.author.name} used !characters")

    character_names = []
    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user:
        for character in user.characters:
            char_auth = with_refresh(base_preston, character.token)
            character_name = char_auth.whoami()['CharacterName']
            character_names.append(f"- {character_name}")

        for corporation_character in user.corporation_characters:
            char_auth = with_refresh(corp_base_preston, corporation_character.token)
            character_name = char_auth.whoami()['CharacterName']
            corporation_name = char_auth.get_op("get_corporations_corporation_id",
                                                corporation_id=corporation_character.corporation_id).get("name")
            character_names.append(f"- {corporation_name} (via {character_name})")

    if character_names:
        character_names_body = "\n".join(character_names)
        await ctx.send(f"You have the following character(s) authenticated:\n{character_names_body}")
    else:
        await ctx.send("You have no authorized characters!")


@bot.command()
async def revoke(ctx):
    """Revokes ESI access from all your characters."""
    logger.info(f"{ctx.author.name} used !revoke")
    await ctx.send("Currently not implemented!")


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
