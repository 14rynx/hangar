# Hangar

A simple discord bot to check if there are any differences in between your ships cargohold 
and their intended state (drugs missing, no capboosters etc.).

![Example Output](https://i.imgur.com/btYS6FS.png)

## Using the Public Instance of the Bot

If you want to set up this bot quickly, you can use the following [invite link](https://discord.com/oauth2/authorize?client_id=1156859100462841907&permissions=3072&integration_type=0&scope=bot).
Type `!help` to see all commands and `!auth` to authorize a character.

For any things regarding maintenance I will try to notify people on my community [discord sever](https://discord.com/invite/fT3eShrg5g).

## Running your own Instance of this Bot

Since we need to connect to both ESI and discord, the setup is sadly somewhat complicated.
This furtherr assumes that you run a [traefik](https://doc.traefik.io/traefik/) container already for reverse-proxy for docker containers.

TLDR: Create an env file and fill it in with the CCP and Discord info, then run with docker compose.

1. Copy the .env file from the example
    ```shell
    cp .env.example .env
    ```
2. Head over to the [Discord Developers Website](https://discord.com/developers/) and create yourself an application.
    - Go to the "Bot" section and reset the token, then copy the new one. Put it in the .env file (`DISCORD_TOKEN=`).
    - Enable the "Message Content Intent" in the Bot section.
    - Invite your bot to your server in the "OAuth2" section. In the URL Generator, click on "Bot" and then
    further down "Send Messages" and "Read Mesasges/View Channels". Follow the generated URL and add the bot to your server.

3. Head over to the [Eve onlone Developers Page](https://developers.eveonline.com/) and create yourself an application.
    - Under "Application Type" select "Authentication & API Access"
    - Under "Permissions" add `esi-corporations.read_structures.v1
    - Under "Callback URL" set `https://yourdomain.com/callback/` (obviously replace your domain)

    Now view the application and copy the values `CCP_REDIRECT_URI`, `CCP_CLIENT_ID` and `CCP_SECRET_KEY` to your .env file.

4. Start the container
    ```shell
    docker-compose up -d --build
    ```

## Using the !url commmand
This bot can automatically fetch your current requirements from an url. In order for that to work the url must return the raw yaml content.
For example you can put your requirements into a github gist and then update it remotely. For this to work you can use the following url:
```
https://gist.githubusercontent.com/YOUR_USER_ID/YOUR_GIST_ID/raw/
```
