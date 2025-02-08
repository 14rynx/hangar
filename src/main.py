import collections
import functools
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
from models import initialize_database, User, Challenge, CorporationCharacter, Character
from utils import lookup, send_large_message

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


def command_error_handler(func):
    """Decorator for handling bot command logging and exceptions."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = args[0]
        logger.info(f"{ctx.author.name} used !{func.__name__}")

        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in !{func.__name__} command: {e}", exc_info=True)
            await ctx.send(f"An error occurred in !{func.__name__}.")

    return wrapper


def update_requirements(user):
    if user.update_url is not None:
        response = requests.get(user.update_url, allow_redirects=True)
        user.requirements_file = response.text


@bot.event
async def on_ready():
    callback_server.start(base_preston)


@bot.command()
@command_error_handler
async def state(ctx):
    """Returns the current state of all your ships in yaml format. (Useful for first setting things up)"""

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
@command_error_handler
async def check(ctx):
    """Returns a bullet point list of what ships are missing things."""

    await ctx.send("Fetching assets...")

    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user is None:
        await ctx.send("You are not a registered user!")
        return

    if user.update_url is not None:
        update_requirements(user)

    if user.requirements_file is None:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")
        return

    has_characters = False
    has_errors = False
    message = ""
    async for assets in get_author_assets(ctx.author.id):
        has_characters = True
        if assets.is_corporation:
            name = f"\n## {assets.corporation_name}:\n"
        else:
            name = f"\n## {assets.character_name}\n"

        for ship_error_message in assets.check_requirement(user.requirements_file):
            has_errors = True

            if len(message) + len(ship_error_message) + len(name) > 1990:
                await ctx.send(message)
                message = ""

            if len(name) > 0:
                message += name
                name = ""

            message += f"{ship_error_message}\n"

    if not has_characters:
        await ctx.send("You have no authorized characters!")
        return

    if has_errors:
        await ctx.send(message)
    else:
        await ctx.send("**No State Errors found!**")


@bot.command()
@command_error_handler
async def buy(ctx):
    """Returns a multibuy of all the things missing in your ships."""

    await ctx.send("Fetching assets...")

    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user is None:
        await ctx.send("You are not a registered user!")
        return

    if user.update_url is not None:
        update_requirements(user)

    if user.requirements_file is None:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")
        return

    has_characters = False
    buy_list = collections.Counter()
    async for assets in get_author_assets(ctx.author.id):
        has_characters = True
        buy_list = assets.get_buy_list(user.requirements_file, buy_list=buy_list)

    if not has_characters:
        await ctx.send("You have no authorized characters!")
        return

    buy_list_body = "\n".join([f"{item} {amount}" for item, amount in buy_list.items()])

    if buy_list_body:
        await send_large_message(ctx, f"**Buy List:**\n```{buy_list_body}```")
    else:
        await ctx.send("**Nothing to buy!**")


@bot.command()
@command_error_handler
async def set(ctx, attachment: discord.Attachment):
    """Sets your current requirement file to the one attached to this command."""

    if not attachment:
        await ctx.send("You forgot to attach a new requirement file!")
        return

    response = requests.get(attachment.url, allow_redirects=True)
    requirements_content = response.content.decode('utf-8')  # Decode the content to a string

    user = User.get_or_none(user_id=str(ctx.author.id))
    if user is None:
        await ctx.send("You currently have no linked characters, so having requirements makes no sense.")
        return

    if user.update_url:
        await ctx.send("Setting a requirements file doesn't make sense as you have an update-url. Unset that first.")
        return

    user.requirements_file = requirements_content
    user.save()
    await ctx.send("Set new requirements file!")


@bot.command()
@command_error_handler
async def get(ctx):
    """Returns your current requirements."""

    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user is None:
        await ctx.send("You are not a registered user!")
        return

    if user.update_url is not None:
        update_requirements(user)

    if user.requirements_file is None:
        await ctx.send("You have not set a requirements file, use the !set command and upload one!")
        return

    requirements = discord.File(
        fp=BytesIO(user.requirements_file.encode('utf-8')),
        filename="requirements.yaml"
    )

    await ctx.send("Here is your current requirement file.", file=requirements)


@bot.command()
@command_error_handler
async def auth(ctx, args):
    """Sends you an authorization link for a character.
    :args: -c: authorize for your corporation"""

    secret_state = secrets.token_urlsafe(60)

    user, created = User.get_or_create(user_id=str(ctx.author.id))
    Challenge.delete().where(Challenge.user == user).execute()
    Challenge.create(user=user, state=secret_state)

    if "-c" in args:
        full_link = f"{corp_base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(
            f"Use this [authentication link]({full_link}) to authorize a character in your corporation "
            f"with the required role (Accountant).")
    else:
        full_link = f"{base_preston.get_authorize_url()}&state={secret_state}"
        await ctx.author.send(f"Use this [authentication link]({full_link}) to authorize your characters.")


@bot.command()
@command_error_handler
async def characters(ctx):
    """Displays your currently authorized characters."""

    character_names = []
    user = User.get_or_none(User.user_id == str(ctx.author.id))
    if user is None:
        await ctx.send("You are not a registered user!")
        return

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
@command_error_handler
async def revoke(ctx, *args):
    """Revokes ESI access from all your characters.
    :args: Character that you want to revoke access to.
    Use -c <corporation_name> to revoke corp access."""

    try:
        user = User.get(User.user_id == str(ctx.author.id))

        if len(args) == 0:
            user_characters = Character.select().where(Character.user == user)
            if user_characters:
                for character in user_characters:
                    character.delete_instance()

            user_corp_characters = CorporationCharacter.select().where(CorporationCharacter.user == user)
            if user_corp_characters:
                for corp_character in user_corp_characters:
                    corp_character.delete_instance()

            user.delete_instance()

            await ctx.send(f"Successfully revoked access to all your characters.")

        elif args[0] == '-c' and len(args) > 1:
            corp_id = await lookup(base_preston, " ".join(args[1:]), return_type="corporations")
            corp_characters = user.corporation_characters.select().where(CorporationCharacter.corporation_id == corp_id)

            for corp_character in corp_characters:
                corp_character.delete_instance()

            if len(corp_characters) == 0:
                await ctx.send(f"You did not have any characters linking this corporation")
            else:
                await ctx.send(
                    f"Successfully removed {len(corp_characters)} characters linked to you and this corporation.")

        else:
            character_id = await lookup(base_preston, " ".join(args), return_type="characters")
            character = user.characters.select().where(Character.character_id == character_id).first()
            if character:
                character.delete_instance()
                await ctx.send(f"Successfully removed your character.")
            else:
                await ctx.send("You have no character with that name linked.")

    except User.DoesNotExist:
        await ctx.send(f"You did not have any authorized characters in the first place.")
    except ValueError:
        args_concatenated = " ".join(args)
        await ctx.send(f"Args `{args_concatenated}` could not be parsed or looked up.")


@bot.command()
@command_error_handler
async def url(ctx, url=None):
    """Set an url from which to update your requirements file before other actions."""
    # Upsert the user's requirements file into the database
    user = User.get_or_none(user_id=str(ctx.author.id))
    if user:
        user.update_url = url
        user.save()
        await ctx.send("Set new update url!")
    else:
        await ctx.send("You currently have no linked characters, so having an update url makes no sense.")


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
