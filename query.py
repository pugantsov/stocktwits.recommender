from datetime import datetime
from SPARQLWrapper import SPARQLWrapper, JSON

from utils.queries import queryFormatter
from Levenshtein import _levenshtein
from termcolor import colored

import pandas as pd
import more_itertools as mit

import logging
import sys
import time
import os
import re
import codecs, difflib

class Queryer:
    def __init__(self):
        self._logpath = './log/database/dbquery'
        self._rpath = './data/csv/'
        self._wpath = './data/txt/queryer/levenshtein/'
        
        try:
            self.results = pd.read_csv(self._rpath+'tag_cat_results.csv', sep='\t')
            self.df = self.results
        except FileNotFoundError:
            self.results = pd.DataFrame()
            self.df = pd.read_csv(self._rpath+'tag_cat_cashtags_clean.csv', sep='\t')
            self.df = self.clean_results(self.df, 'standard')
            self.df = self.df[['id', 'title', 'target', 'symbol', 'exchange']]
        self.not_found = pd.DataFrame()

    def logger(self):
        """Sets logger config to both std.out and log ./log/io/dbquery

        Also sets the formatting instructions for the log file, prints Time,
        Current Thread, Logging Type, Message.

        """
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
            handlers=[
                logging.FileHandler("{0}/{1} ({2}).log".format(
                    self._logpath,
                    str(datetime.now())[:-7],
                    'dbquery',
                )),
                logging.StreamHandler(sys.stdout)
            ])

    def run_query(self, symbols: str, keyword: str):
        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        query = queryFormatter(keyword, symbols)
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
        results_df = pd.DataFrame()

        try:
            if results['results']['bindings']:
                results_df = pd.io.json.json_normalize(results['results']['bindings'])
                results_df['exchangeLabel.value'] = results_df['exchangeLabel.value'].str.replace("New York Stock Exchange","NYSE")            
                results_df = results_df[['symbol.value','exchangeLabel.value','title.value','itemDescription.value', 'item.value']] if keyword is 'standard' else results_df[['exchangeLabel.value','title.value','itemDescription.value', 'item.value']]  
                results_df = results_df.rename(columns={
                    'symbol.value':'symbol', 
                    'exchangeLabel.value':'exchange', 
                    'title.value': 'title',
                    'itemDescription.value': 'wdDescription',
                    'item.value':'wdEntity'
                })
        except KeyError: return None
        return results_df

    def query_loop(self, df: pd.DataFrame, query: str):
        if query is 'standard':
            symbols = ['^'+s+'$' for s in df.symbol.tolist()]
        elif query is 'by_name':
            symbols = [str(s).strip() for s in df.title.tolist()]
            symbols = [re.sub(' +', ' ', s) for s in symbols]
        symbols_split = [list(c) for c in mit.divide(8, symbols)]

        results = pd.DataFrame()
        for i, s in enumerate(symbols_split):
            print("Parsing symbol list of size: {}, List: {}/{}".format(len(s), i+1, len(symbols_split)))
            symbols = '|'.join(s)
            query_results = self.run_query(symbols, query)
            results = results.append(query_results)
        print("Size of results returned: {}".format(results.shape[0]))
        return results

    # def fuzzy_string_comparison(self, df: pd.DataFrame, df_old: pd.DataFrame, keyword: str):
    #     cashtags_main = df_old['title'].tolist()
    #     cashtags_main = [s.lower() for s in cashtags_main]
    #     df['keep'] = True
    #     print("Size of results DataFrame (NYSE/NASDAQ only): {}".format(df.shape[0]))
    #     for i, row in df.iterrows():
    #         title = row['title'].lower()
    #         ratios = {}
    #         for tag in cashtags_main:
    #             # lev = difflib.SequenceMatcher(None, tag, title).ratio()
    #             lev = _levenshtein.ratio(tag, title)
    #             ratios[tag] = lev
    #         matched_string = max(ratios, key=lambda key: ratios[key])
    #         matched_ratio = ratios[matched_string]
    #         if keyword is 'remove_found':
    #             if matched_ratio == 1.0:
    #                 df.at[i, 'keep'] = False
    #             else:
    #                 print("Title in query DF: {}, Title in original DF: {}, Ratio: {}\n".format(colored(title, 'blue'), colored(matched_string, 'blue'), matched_ratio))
    #                 time.sleep(1.5)
    #     df = df[df.keep == True]
    #     print("Size of results DataFrame after string comparison: {}".format(df.shape[0]))
    #     sys.exit(0)
    #     return df
    def fuzzy_string_comparison(self, results_df: pd.DataFrame):
        print("Size of result_df: {}".format(results_df.shape[0]))
        cashtags_not_found = self.not_found['title'].tolist()
        results_df['keep'] = False
        match_count = 0
        for i, row in results_df.iterrows():
            curr_title = row['title'].lower()
            ratios = {}
            for tag_not_found in cashtags_not_found:
                # lev = difflib.SequenceMatcher(None, tag, title).ratio()
                lev = _levenshtein.ratio(curr_title, tag_not_found)
                ratios[tag_not_found] = lev
            matched_string = max(ratios, key=lambda key: ratios[key])
            matched_ratio = ratios[matched_string]
            if matched_ratio == 1.0:
                results_df.at[i, 'keep'], match_count = True, match_count+1
        results_df = results_df[results_df.keep]
        results_df = results_df.drop(columns=['keep'])
        print("Size of result_df: {}".format(results_df.shape[0]))
        return results_df

    def merge_and_remove_duplicates(self, merge_on, variables):
        self.df = self.df.merge(self.results, on=merge_on, how='left')
        duplicate_df = pd.concat(g for _, g in self.df.groupby(merge_on[0]) if len(g) > 1)
        if 'symbol' in merge_on:
            duplicate_df = duplicate_df[['title_x', 'title_y']]
            indexes = self.clean_duplicates(duplicate_df)
            self.df = self.df.drop(self.df.index[indexes])
        for v in variables:
            self.df[v] = self.df[v+'_x'].where(self.df[v+'_y'].isnull(), self.df[v+'_y'])
            if 'symbol' in merge_on:
                cols = list(self.df)
                cols.insert(1, cols.pop(cols.index('title')))
                self.df = self.df.ix[:, cols]
            self.df = self.df.drop(columns=[v+'_x', v+'_y'])
        if 'title' in merge_on: self.df = self.df.drop_duplicates()

    def clean_duplicates(self, df):
        maxes = {}
        for i, row in df.iterrows():
            lev = _levenshtein.ratio(row.title_x, row.title_y)
            if row.title_x not in maxes:
                maxes[row.title_x] = (i, lev)
            else:
                if lev > maxes[row.title_x][1]:
                    maxes[row.title_x] = (i, lev)
        maxes = [val[0] for val in maxes.values()]
        indexes = df.index.values.tolist()
        return list(set(indexes) - set(maxes))

    def clean_results(self, df: pd.DataFrame, keyword: str):
        #STANDARD
        df = df.copy()
        df = df[df.exchange.str.contains('^NASDAQ$|^NYSE$')]
        regex_companies = re.compile(r'(?:\s+(?:Incorporated|Corporation|Company|Inc Common Stock|QQQ|ETF|PLC|SA|Inc|Corp|Ltd|LP|plc|Group|The|Limited|Partners|nv|Financial|Services|bancshares|semiconductor|foods|energy))+\s*$', flags=re.IGNORECASE)
        #regex_tld = re.compile(r'.*([^\.]+)(com|net|org|info|int|co\.uk|org\.uk|ac\.uk|uk)$', flags=re.IGNORECASE) 
        df['title'] = df['title'].str.replace('[^\w\s]','')
        df['title'] = df['title'].str.strip()
        df['title'] = df['title'].str.replace(' +|The ', ' ', regex=True)
        df['title'] = df['title'].str.replace('Company', 'Co', regex=True)
        df['title'] = df['title'].str.replace(regex_companies, '')
        #df['title'] = df['title'].str.replace(regex_tld, '')
        df['title'] = df['title'].str.strip()
        df['title'] = df['title'].str.lower()

        #AFTER RESULTS
        if keyword is 'match_names':
            return self.fuzzy_string_comparison(df)
        print("Size of results after cleaning exchanges: {}".format(df.shape[0]))
        return df

    def run(self, source=None):
        if source is 'Wikidata':
            if self.results.empty:
                self.results = self.query_loop(self.df, 'standard')
                self.results = self.clean_results(self.results, 'standard')
                self.results = self.results.drop_duplicates()
                self.merge_and_remove_duplicates(['symbol', 'exchange'], ['title'])

            self.not_found = self.df[self.df.wdEntity.isna()]
            print("Remaining symbols: {}".format(self.not_found.shape[0]))
            self.results = self.query_loop(self.not_found, 'by_name')
            self.results = self.clean_results(self.results, 'match_names')
            self.merge_and_remove_duplicates(['title', 'exchange'], ['wdDescription', 'wdEntity'])
            self.df.to_csv(self._rpath+'tag_cat_results.csv', sep="\t", index=False)
            print("Items with wikidata entries: {}".format(self.df[~self.df.wdEntity.isna()].shape[0]))
        if source is 'DBPedia':
            

        # try:
        #     self.results = pd.read_csv(self._rpath+'tag_cat_by_name_temp.csv', sep='\t')
        #     self.results = self.clean_results(self.results, 'match_names')
        #     self.merge_and_remove_duplicates(['title', 'exchange'], ['wdDescription', 'wdEntity'])
        # except FileNotFoundError:
        
            #results = self.clean_results(results, 'match_names')

if __name__ == "__main__":
    queryer = Queryer()
    queryer.run('Wikidata')