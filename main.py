import discord
import requests
import json
import io
import chess.pgn
import pandas as pd
import time
from tabulate import tabulate
import configparser
import asyncio

client = discord.Client()


class GameStats:
    def __init__(self, pgn_string, game_id):
        game = chess.pgn.read_game(io.StringIO(pgn_string))

        self.id = game_id
        self.black = game.headers["Black"].lower()
        self.white = game.headers["White"].lower()
        self.result = game.headers["Result"]

class LichessUtils:

    def __init__(self, print_callback):
        self.print = print_callback

    def get_team_id_from_team_name(self, team_name):

        result = requests.get("https://lichess.org/api/team/search?text={}".format(team_name.lower()))

        jj = json.loads(result.content.decode("utf-8"))

        return jj["currentPageResults"][0]["id"]

    def get_team_name_from_team_name(self, team_name):

        result = requests.get("https://lichess.org/api/team/search?text={}".format(team_name.lower()))

        jj = json.loads(result.content.decode("utf-8"))

        return jj["currentPageResults"][0]["name"]

    async def get_swiss_tournaments_from_team(self, team_name):

        team_id = self.get_team_id_from_team_name(team_name)

        url = "https://lichess.org/api/team/{}/swiss"

        json_response = requests.get(url.format(team_id))
        json_response_string = json_response.content.decode("utf-8")
        json_array = json_response_string.split("\n")
        id_array = list()

        await self.print("Prüfe auf neue Turniere für Team {}".format(team_name))

        for tournament in json_array:

            try:
                obj = json.loads(tournament)
                id_array.append(obj["id"])

            except:
                pass

        return id_array

    def get_all_games_from_swiss_tournament(self, tournament_id):

        response = requests.get("https://lichess.org/api/swiss/{}/games".format(tournament_id))

        all_games_pgn = response.content.decode("utf-8").split("\n\n\n")

        all_parsed_games = list()

        for game in all_games_pgn:
            if game != "":
                all_parsed_games.append(GameStats(game, "foobar"))
        return all_parsed_games

    def build_pandas_stats(self, games):
        df = pd.DataFrame(self.build_stats(games)).T
        df.columns = ["Win", "Draw", "Loss"]
        return df

    def build_stats(self, games):

        player = {}

        for game in games:

            if game.black not in player:
                player[game.black] = [0, 0, 0]

            if game.result == '0-1':
                player[game.black][0] += 1
            elif game.result == '1-0':
                player[game.black][2] += 1
            else:
                player[game.black][1] += 1

            if game.white not in player:
                player[game.white] = [0, 0, 0]

            if game.result == '1-0':
                player[game.white][0] += 1
            elif game.result == '0-1':
                player[game.white][2] += 1
            else:
                player[game.white][1] += 1

        return player

    async def get_statistics(self, team_name):
        global tournament_list
        global team_points

        df = None

        counter = 0
        progress_message = "Fortschritt: {}/{}"

        tournaments = await self.get_swiss_tournaments_from_team(team_name)

        # check for new tournaments that are not yet in tournament_list
        new_tournaments = list(set(tournaments)-set(tournament_list))

        if len(new_tournaments) == 0:
            await self.print("Keine neuen Turniere gefunden, Liste ist auf neustem Stand.")

        # load all data frame if exists
        if team_name not in team_points:
            team_points[team_name] = pd.DataFrame()

        df = team_points[team_name]

        if len(new_tournaments) > 0:
            sent_message = await self.print(progress_message.format(counter, len(tournaments)))

        for t in new_tournaments:

            df_t = self.build_pandas_stats(self.get_all_games_from_swiss_tournament(t))
            df = pd.concat([df, df_t]).reset_index().groupby("index").sum()

            counter += 1
            print(progress_message.format(counter, len(tournaments)))
            await sent_message.edit(content=progress_message.format(counter, len(tournaments)))

        # add new tournaments to list
        tournament_list = tournament_list + new_tournaments

        df["Punkte"] = df.Win+df.Draw/2

        team_points[team_name] = df

        return df


def is_user_timed_out(user_name):
    if user_name not in user_timeout or time.time() - user_timeout[user_name] > timeout_interval_seconds:
        user_timeout[user_name] = time.time()
        return False, 0

    remaining_cooldown = timeout_interval_seconds - int(time.time() - user_timeout[user_name])
    return True, remaining_cooldown

@client.event
async def on_message(message):
    # we do not want the bot to reply to itself

    if message.author == client.user:
        return

    if message.content.startswith("!commands"):

        msg = "```\n" +\
            "!tabelle <team_name> <top output>  -  Gibt die top <top output> Tabelle für Team <team_name> aus\n" + \
            "!punkte <spieler_name> <team_name> -  Gibt den Score und die Position für Spieler <spieler_name> im Team <team_name> aus" + \
            "```"

        await message.channel.send(msg)

    if message.content.startswith("!punkte"):

        timeouted, cooldown = is_user_timed_out(message.author.mention)
        if timeouted:
            await message.channel.send("@{}: {} Sekunden Timeout verbleibend".format(message.author.mention, cooldown))
            return

        stats_object = LichessUtils(message.channel.send)

        _, player_name, team_name = message.content.split(" ")

        player_name = player_name.lower()
        real_team_name = stats_object.get_team_name_from_team_name(team_name)

        if real_team_name in processing_list:
            await message.channel.send("Daten für Team {} werden bereits abgefragt. Bitte warten...".format(real_team_name))
            return

        processing_list.append(real_team_name)
        data = await stats_object.get_statistics(real_team_name)
        processing_list.remove(real_team_name)

        if player_name in data.index:
            entry = data.loc[player_name]
            await message.channel.send("Statistiken für {}. Win: {}  Draw: {}  Loss: {}".format(player_name, entry["Win"], entry["Draw"], entry["Loss"]))
        else:
            await message.channel.send("Spieler {} hat noch nicht in einem Turnier von Team {} teilgenommen.".format(player_name, real_team_name))


    if message.content.startswith("!tabelle"):

        timeouted, cooldown = is_user_timed_out(message.author.mention)
        if timeouted:
            await message.channel.send("{}: {} Sekunden Timeout verbleibend".format(message.author.mention, cooldown))
            return

        stats_object = LichessUtils(message.channel.send)

        message_split = message.content.split(" ")

        team_name = message_split[1]

        top_count = 10

        real_team_name = stats_object.get_team_name_from_team_name(team_name)

        if real_team_name in processing_list:
            await message.channel.send("Daten für Team {} werden bereits abgefragt. Bitte warten...".format(real_team_name))
            return

        team_id = stats_object.get_team_id_from_team_name(team_name)

        if len(message_split) > 2:
            top_count = int(message_split[2])

        processing_list.append(real_team_name)
        data = await stats_object.get_statistics(real_team_name)
        processing_list.remove(real_team_name)

        await message.channel.send("Hier sind die Spielergebnisse:")

        # message_post_split = tabulate(data).split("\n")

        # for m in message_post_split:
        # await message.channel.send(m)

        display_data = data.sort_values(["Punkte"], ascending=[False]).head(top_count)

        tabulated_message = tabulate(display_data, headers=["Win", "Draw", "Loss", "Punkte"])

        # only do 10 rows at a time

        tabulated_message_split = tabulated_message.split("\n")

        chunk_size = 40
        chunks = [tabulated_message_split[x:x + chunk_size] for x in range(0, len(tabulated_message_split), chunk_size)]

        for chunk in chunks:
            out_message = "\n".join(chunk)
            await message.channel.send("```" + out_message + "```")


@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')


config = configparser.ConfigParser()
config.read("config.txt")


TOKEN = config["DEFAULT"]["DiscordToken"]
timeout_interval_seconds = int(config["DEFAULT"]["Timeout"])

team_points = {}
user_timeout = {}
processing_list = list()
tournament_list = list()

client.run(TOKEN)
