from riotwatcher import RiotWatcher
from converters.data2frames import game_to_dataframe as g2df
from converters.data2files import write_json, read_json, save_runes_reforged_json
import pandas as pd
from datetime import datetime as dt
from tqdm import tqdm
import os
import urllib.request
import json
from itertools import chain
from requests.exceptions import HTTPError
from config.constants import RAW_DATA_PATH, EXCEL_EXPORT_PATH, CSV_EXPORT_PATH_MERGED, EXCEL_EXPORT_PATH_MERGED, \
    SCRIMS_POSITIONS_COLS, CUSTOM_PARTICIPANT_COLS, STANDARD_POSITIONS, API_KEY, STATIC_DATA_DIR, LEAGUES_DATA_DICT, \
    CSV_EXPORT_PATH, IDS_FILE_PATH, DTYPES, OFFICIAL_LEAGUE, EXPORTS_DIR, LEAGUES_DATA_DIR, MATCHES_RAW_DATA_DIR, \
    SOLOQ_GAMES_DIR, LCK_GAMES_DIR, SCRIMS_GAMES_DIR, SLO_GAMES_DIR, REGIONS


class FileSystem:
    def __init__(self, region, league):
        self.rw = RiotWatcher(API_KEY)
        self.region = region
        self.league = league

    def generate_dataset(self, read_dir, force_update=False, **kwargs):
        if 'game_ids' in kwargs:
            new = kwargs['game_ids']
            df = pd.DataFrame({'game_id': new})
        else:
            df = pd.read_csv(LEAGUES_DATA_DICT[self.league][IDS_FILE_PATH],
                             dtype=LEAGUES_DATA_DICT[self.league][DTYPES])
            new = list(df.game_id.unique())
        df2 = pd.DataFrame()
        try:
            df2 = pd.read_csv('{}'.format(LEAGUES_DATA_DICT[self.league][CSV_EXPORT_PATH]), index_col=0,
                              encoding="ISO-8859-1")
            old = list(df2.gameId.unique())
            new_ids = self.__get_new_ids(old, new)
        except FileNotFoundError:
            new_ids = new
            force_update = True

        df_result = pd.DataFrame()
        if not force_update:
            if new_ids:
                print('There are {} new ids, merging the old data with the new one.'.format(len(new_ids)))
                if 'game_ids' not in kwargs:
                    df3 = df[df.game_id.isin(new_ids)]
                    df4 = self.__concat_games(df3, read_dir)
                else:
                    df4 = self.__concat_games(pd.DataFrame({'game_id': new_ids}), read_dir)
                df_result = pd.concat([df2, df4.T.reset_index().drop_duplicates(subset='index',
                                                                                keep='first').set_index('index').T])
                return df_result.reset_index(drop=True)
            elif not new_ids:
                return None
        elif force_update:
            if new_ids:
                print('Updating current datasets but there are {} new ids found.'.format(len(new_ids)))
                df_result = self.__concat_games(df, read_dir).T.reset_index()\
                    .drop_duplicates(subset='index', keep='first').set_index('index').T
            elif not new_ids:
                print('Forcing update of the current datasets even though there are not new ids.')
                df_result = self.__concat_games(df, read_dir).T.reset_index()\
                    .drop_duplicates(subset='index', keep='first').set_index('index').T

            return df_result.reset_index(drop=True)

    def download_games(self, ids, save_dir):
        def tournament_match_to_dict(id1, hash1, tournament):
            with urllib.request.urlopen('https://acs.leagueoflegends.com/v1/stats/game/{tr}/{id}'
                                        '?gameHash={hash}'.format(tr=tournament, id=id1, hash=hash1)) as url:
                match = json.loads(url.read().decode())
            with urllib.request.urlopen('https://acs.leagueoflegends.com/v1/stats/game/{tr}/{id}/timeline'
                                        '?gameHash={hash}'.format(tr=tournament, id=id1, hash=hash1)) as url:
                tl = json.loads(url.read().decode())
            return match, tl
        file_names = os.listdir(save_dir)
        curr_ids = list(set([f.split('.')[0].split('_')[1] for f in file_names]))
        new_ids = self.__get_new_ids(curr_ids, ids)
        if new_ids:
            for item in tqdm(new_ids, desc='Downloading games'):
                try:
                    if LEAGUES_DATA_DICT[self.league][OFFICIAL_LEAGUE]:
                        id1 = item.split('#')[0]
                        tr = item.split('#')[1]
                        hash1 = item.split('#')[2]
                        match, timeline = tournament_match_to_dict(id1, hash1, tr)
                        data = {'match': match, 'timeline': timeline}
                        self.__save_match_raw_data(data=data, save_dir=save_dir, hash=hash1)
                    else:
                        match = self.rw.match.by_id(match_id=item, region=REGIONS[self.region])
                        timeline = self.rw.match.timeline_by_match(match_id=item, region=REGIONS[self.region])
                        data = {'match': match, 'timeline': timeline}
                        self.__save_match_raw_data(data=data, save_dir=save_dir)
                except HTTPError:
                    pass
        else:
            print('All games already downloaded.')

    def __save_match_raw_data(self, data, save_dir, **kwargs):
        if isinstance(data, dict):
            if LEAGUES_DATA_DICT[self.league][OFFICIAL_LEAGUE]:
                game_id = str(data['match']['gameId']) + '#' + str(data['match']['platformId'] + '#'
                                                                   + str(kwargs['hash']))
            else:
                game_id = str(data['match']['gameId'])
            game_creation = dt.strftime(dt.fromtimestamp(data['match']['gameCreation'] / 1e3), '%d-%m-%y')
            write_json(data['match'], save_dir=save_dir, file_name='{date}_{id}'.format(date=game_creation, id=game_id))
            write_json(data['timeline'], save_dir=save_dir, file_name='{date}_{id}_tl'
                       .format(date=game_creation, id=game_id))
        else:
            raise TypeError('Dict expected at data param. Should be passed as shown here: {"match": match_dict, '
                            '"timeline": timeline_dict}.')

    def get_league_game_ids(self, **kwargs):
        league_data_path = LEAGUES_DATA_DICT[self.league][IDS_FILE_PATH]
        df = pd.read_csv(league_data_path, dtype=LEAGUES_DATA_DICT[self.league][DTYPES])
        if LEAGUES_DATA_DICT[self.league][OFFICIAL_LEAGUE]:
            return list(df.game_id.map(str) + '#' + df.tournament + '#' + df.hash)
        elif self.league == 'SOLOQ':
            ids = list(df.account_id)
            if 'begin_index' in kwargs:
                begin_index = kwargs['begin_index']
            else:
                begin_index = 0
            return self.__get_soloq_game_ids(acc_ids=ids, n_games=kwargs['n_games'], begin_index=begin_index)
        return list(df.game_id)

    @staticmethod
    def __get_file_names_from_match_id(m_id, save_dir):
        file_names = os.listdir(save_dir)
        match_filename = [val for val in file_names if str(m_id) in val and 'tl' not in val][0]
        tl_filename = [val for val in file_names if str(m_id) in val and 'tl' in val][0]
        return {'match_filename': match_filename.split('.')[0], 'tl_filename': tl_filename.split('.')[0]}

    @staticmethod
    def __get_new_ids(old, new):
        return list(set(map(int, new)) - set(map(int, old)))

    def __concat_games(self, df, read_dir):
        if self.league == 'SLO':
            return pd.concat([g2df(match=read_json(save_dir=read_dir,
                                                   file_name=self.__get_file_names_from_match_id(m_id=g[1]['game_id'],
                                                                                                 save_dir=read_dir)
                                                   ['match_filename']),
                                   timeline=read_json(save_dir=read_dir,
                                                      file_name=self.__get_file_names_from_match_id(
                                                          m_id=g[1]['game_id'], save_dir=read_dir)['tl_filename']),
                                   custom_names=list(g[1][CUSTOM_PARTICIPANT_COLS].T),
                                   custom_positions=STANDARD_POSITIONS,
                                   team_names=list(g[1][['blue', 'red']]),
                                   week=g[1]['week'], custom=True) for g in df.iterrows()])
        elif self.league == 'SCRIMS':
            return pd.concat([g2df(match=read_json(save_dir=read_dir,
                                                   file_name=self.__get_file_names_from_match_id(m_id=g[1]['game_id'],
                                                                                                 save_dir=read_dir)
                                                   ['match_filename']),
                                   timeline=read_json(save_dir=read_dir,
                                                      file_name=self.__get_file_names_from_match_id(
                                                          m_id=g[1]['game_id'], save_dir=read_dir)['tl_filename']),
                                   custom_positions=list(g[1][SCRIMS_POSITIONS_COLS]),
                                   team_names=list(g[1][['blue', 'red']]),
                                   custom_names=list(g[1][CUSTOM_PARTICIPANT_COLS]),
                                   custom=True, enemy=g[1]['enemy'], game_n=g[1]['game_n'], blue_win=g[1]['blue_win']
                                   ) for g in df.iterrows()])
        elif self.league == 'LCK':
            return pd.concat([g2df(match=read_json(save_dir=read_dir,
                                                   file_name=self.__get_file_names_from_match_id(m_id=g[1]['game_id'],
                                                                                                 save_dir=read_dir)
                                                   ['match_filename']),
                                   timeline=read_json(save_dir=read_dir,
                                                      file_name=self.__get_file_names_from_match_id(
                                                          m_id=g[1]['game_id'], save_dir=read_dir)['tl_filename']),
                                   week=g[1]['week'], custom=False,
                                   custom_positions=STANDARD_POSITIONS) for g in df.iterrows()])
        elif self.league == 'SOLOQ':
            return pd.concat([g2df(match=read_json(save_dir=read_dir,
                                                   file_name=self.__get_file_names_from_match_id(m_id=gid,
                                                                                                 save_dir=read_dir)
                                                   ['match_filename']),
                                   timeline=read_json(save_dir=read_dir,
                                                      file_name=self.__get_file_names_from_match_id(
                                                          m_id=gid, save_dir=read_dir)['tl_filename']),
                                   custom=False
                                   ) for gid in list(df.game_id)])

    def save_static_data_files(self):
        versions = self.rw.static_data.versions(region=REGIONS[self.region])
        write_json(versions, STATIC_DATA_DIR, file_name='versions')

        champs = self.rw.static_data.champions(region=REGIONS[self.region], version=versions[0])
        write_json(champs, STATIC_DATA_DIR, file_name='champions')

        items = self.rw.static_data.items(region=REGIONS[self.region], version=versions[0])
        write_json(items, STATIC_DATA_DIR, file_name='items')

        summs = self.rw.static_data.summoner_spells(region=REGIONS[self.region], version=versions[0])
        write_json(summs, STATIC_DATA_DIR, file_name='summoners')

        save_runes_reforged_json()

    def __get_soloq_game_ids(self, acc_ids, **kwargs):
        if 'n_games' in kwargs:
            n_games = kwargs['n_games']
        else:
            n_games = 20

        if 'begin_index' in kwargs:
            begin_index = kwargs['begin_index']
        else:
            begin_index = 0
        matches = list(chain.from_iterable(
            [self.rw.match.matchlist_by_account(account_id=acc, begin_index=begin_index,
                                                end_index=int(begin_index)+int(n_games),
                                                region=self.region, queue=420)['matches']
             for acc in acc_ids]))
        result = list(set([m['gameId'] for m in matches]))
        return result


def create_dirs():
    if not os.path.exists(EXPORTS_DIR):
        os.makedirs(EXPORTS_DIR)

    if not os.path.exists(LEAGUES_DATA_DIR):
        os.makedirs(LEAGUES_DATA_DIR)

    if not os.path.exists(MATCHES_RAW_DATA_DIR):
        os.makedirs(MATCHES_RAW_DATA_DIR)

    if not os.path.exists(STATIC_DATA_DIR):
        os.makedirs(STATIC_DATA_DIR)

    if not os.path.exists(LCK_GAMES_DIR):
        os.makedirs(LCK_GAMES_DIR)

    if not os.path.exists(SLO_GAMES_DIR):
        os.makedirs(SLO_GAMES_DIR)

    if not os.path.exists(SOLOQ_GAMES_DIR):
        os.makedirs(SOLOQ_GAMES_DIR)

    if not os.path.exists(SCRIMS_GAMES_DIR):
        os.makedirs(SCRIMS_GAMES_DIR)


def parse_args(args):
    create_dirs()
    league = args.league.upper()
    if args.region:
        region = args.region.upper()
    else:
        region = 'EUW1'
    fs = FileSystem(region, league)
    if args.download:
        if league == 'SOLOQ':
            if args.n_games:
                n_games = args.n_games
            else:
                n_games = 20

            if args.begin_index:
                begin_index = args.begin_index
            else:
                begin_index = 0
            ids = fs.get_league_game_ids(n_games=n_games, begin_index=begin_index)
        else:
            ids = fs.get_league_game_ids()
        fs.download_games(ids=ids, save_dir=LEAGUES_DATA_DICT[league][RAW_DATA_PATH])
        print("Games downloaded.")

    if args.update_static_data:
        fs.save_static_data_files()
        print("Static data updated.")

    if args.export:
        if league == 'SOLOQ':
            files = os.listdir(LEAGUES_DATA_DICT[league][RAW_DATA_PATH])
            l1 = [f.split('_')[1] for f in files]
            ids = list(map(int, set([i.split('.')[0] for i in l1])))
            df = fs.generate_dataset(read_dir=LEAGUES_DATA_DICT[league][RAW_DATA_PATH],
                                     force_update=args.force_update, game_ids=ids)
        else:
            df = fs.generate_dataset(read_dir=LEAGUES_DATA_DICT[league][RAW_DATA_PATH],
                                     force_update=args.force_update)

        if df is not None:
            if args.xlsx:
                df.to_excel('{}'.format(LEAGUES_DATA_DICT[league][EXCEL_EXPORT_PATH]))
            if args.csv:
                df.to_csv('{}'.format(LEAGUES_DATA_DICT[league][CSV_EXPORT_PATH]))
            if not args.csv and not args.xlsx:
                df.to_excel('{}'.format(LEAGUES_DATA_DICT[league][EXCEL_EXPORT_PATH]))
                df.to_csv('{}'.format(LEAGUES_DATA_DICT[league][CSV_EXPORT_PATH]))
            print("Export finished.")
        else:
            print("No export done.")

    if args.merge_soloq and league == 'SOLOQ':
        df1 = pd.read_csv(LEAGUES_DATA_DICT['SOLOQ'][IDS_FILE_PATH], encoding='ISO-8859-1',
                          dtype=LEAGUES_DATA_DICT['SOLOQ']['dtypes'])
        df2 = pd.read_csv(LEAGUES_DATA_DICT['SOLOQ'][CSV_EXPORT_PATH], index_col=0, encoding='ISO-8859-1')
        df3 = df2[pd.notnull(df2.currentAccountId)]
        df3.currentAccountId = df3.currentAccountId.map(int)
        df4 = df3.merge(df1, left_on='currentAccountId', right_on='account_id', how='left')
        df4.to_csv(LEAGUES_DATA_DICT['SOLOQ'][CSV_EXPORT_PATH_MERGED])
        df4.to_excel(LEAGUES_DATA_DICT['SOLOQ'][EXCEL_EXPORT_PATH_MERGED])
        print("Solo Q data merged with pro players data.")
