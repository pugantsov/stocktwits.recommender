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
import math

class Queryer:
    def __init__(self, source='dbpedia', query_type='q_entity', query_rate='individual'):
        def wikidata():
            try:
                self.results = pd.read_csv(self._rpath+'tag_cat_results.csv', sep='\t')
                self.df = self.results
            except FileNotFoundError:
                self.results = pd.DataFrame()
                self.df = pd.read_csv(self._rpath+'tag_cat_cashtags_clean.csv', sep='\t')
                self.df = self.clean_results(self.df, 'standard')
                self.df = self.df[['id', 'title', 'target', 'symbol', 'exchange']]
        
        def dbpedia():
            try:
                self.results = pd.read_csv(self._rpath+'tag_cat_dbpedia_results.csv', sep='\t')
                self.df = self.results
            except FileNotFoundError:
                self.results = pd.DataFrame()
                self.df = pd.read_csv(self._rpath+'tag_cat_results_new.csv', sep='\t')

        self._logpath = '../log/database/dbquery'
        self._rpath = '../data/csv/'
        self._wpath = '../data/txt/queryer/levenshtein/'
        self.source = source
        self.query_type = query_type
        self.query_rate = query_rate

        locals()[self.source.lower()]()

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
        if keyword is 'dbpedia':
            sparql = SPARQLWrapper("http://dbpedia.org/sparql")
            query = symbols
        else:
            sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
            query = queryFormatter(keyword, symbols)
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()
        results_df = pd.DataFrame()

        try:
            if results['results']['bindings']:
                results_df = pd.io.json.json_normalize(results['results']['bindings'])
                if keyword is not 'dbpedia':
                    results_df['exchangeLabel.value'] = results_df['exchangeLabel.value'].str.replace("New York Stock Exchange","NYSE")            
                    results_df = results_df[['symbol.value','exchangeLabel.value','title.value','itemDescription.value', 'item.value']] if keyword is 'standard' else results_df[['exchangeLabel.value','title.value','itemDescription.value', 'item.value']]  
                    results_df = results_df.rename(columns={
                        'symbol.value':'symbol', 
                        'exchangeLabel.value':'exchange', 
                        'title.value': 'title',
                        'itemDescription.value': 'wdDescription',
                        'item.value':'wdEntity'
                    })
                else:
                    cols = [s for s in list(results_df) if s.endswith('.value')]
                    results_df = results_df[cols]
                    results_df = results_df.replace(regex={r'\t': ' '}) 
                    results_df = results_df.rename(columns = lambda x : str(x)[:-6])
        except KeyError: return None
        return results_df

    def dbp_symbols_query_gen(self):

        def q_entity(symbols: list):
            results = pd.DataFrame()
            for i, s in enumerate(symbols):
                s_members = s.split('|')
                exchange_symbol_string = ''.join(s_members[:-2])
                wd_sym_link = s_members[2]
                value = """( "{}" <{}>) """.format(exchange_symbol_string, wd_sym_link)
                print("Parsing symbol: {}, List: {}/{}".format(exchange_symbol_string, i+1, len(symbols)))
                query = """
                    PREFIX yago: <http://dbpedia.org/class/yago/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX owl: <http://www.w3.org/2002/07/owl#>

                    SELECT DISTINCT ?key ?title ?dbpDescription ?symbol ?exchange ?dbpEntity ?wdEntity
                    WHERE {{
                        ?dbpEntity rdfs:label ?title.
                        ?dbpEntity rdfs:comment ?comment.
                        OPTIONAL {{ ?dbpEntity dbp:symbol ?symbol . ?dbpEntity rdf:type ?exchange.}}
                        ?dbpEntity owl:sameAs ?wdEntity.
                        FILTER (lang(?title) = "en" && lang(?comment) = "en").
                        VALUES ( ?key ?wdEntity ) 
                            {{ {} }}
                    }}
                    """.format(value)
                results_df = self.run_query(query, 'dbpedia')
                results = results.append(results_df, ignore_index = True) 
                time.sleep(0.2)
            return results

        def q_categorised_entity(symbols: list):
            results = pd.DataFrame()
            symbols_split = [list(c) for c in mit.divide(512, symbols)]
            for i, split in enumerate(symbols_split):
                print("Parsing symbol list of size: {}, List: {}/{}".format(len(split), i+1, len(symbols_split)))
                values = []
                for s in split:
                    s_members = s.split('|')
                    exchange_symbol_string = ''.join(s_members[:-2])
                    exchange = s_members[0]
                    wd_sym_link = s_members[2]
                    values.append("""( "{}" "{}" <{}>) """.format(exchange_symbol_string, exchange, wd_sym_link))
                values = ''.join(values)

                #FILTER(?exchange IN (yago:WikicatCompaniesListedOnNASDAQ,yago:WikicatCompaniesListedOnTheNewYorkStockExchange))
                query = """
                    PREFIX yago: <http://dbpedia.org/class/yago/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                    PREFIX owl: <http://www.w3.org/2002/07/owl#>

                    SELECT ?key ?title ?dbpDescription ?symbol ?exchange ?dbpEntity ?wdEntity
                    WHERE {{
                        ?dbpEntity rdfs:label ?title.
                        ?dbpEntity rdfs:comment ?comment.
                        OPTIONAL {{ ?dbpEntity dbp:symbol ?symbol . }}
                        ?dbpEntity rdf:type ?exchange.
                        ?dbpEntity owl:sameAs ?wdEntity.
                        FILTER (lang(?title) = "en" && lang(?comment) = "en").
                        FILTER(STRENDS(STR(?exchange),?exch))
                        VALUES ( ?key ?exch ?wdEntity ) 
                            {{ {} }}
                    }}
                    """.format(values)

                results_df = self.run_query(query, 'dbpedia')
                results = results.append(results_df, ignore_index = True) 
                time.sleep(1)
            return results

        def q_categorised_by_symbol(symbols: list):
            results = pd.DataFrame()
            for i, s in enumerate(symbols):
                s_members = s.split('|')
                exchange, symbol = s_members[:-2]
                exchange_symbol_string = ''.join(s_members[:-2])
                value = """( "{}" "{}" "{}") """.format(exchange_symbol_string, exchange, symbol)
                print("Parsing symbol: {}, List: {}/{}".format(exchange_symbol_string, i+1, len(symbols)))
            
                query = """
                            PREFIX yago: <http://dbpedia.org/class/yago/>
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                            PREFIX owl: <http://www.w3.org/2002/07/owl#>

                            SELECT DISTINCT ?key ?title ?dbpDescription ?symbol ?exchange ?dbpEntity
                            WHERE {{
                                ?dbpEntity rdfs:label ?title.
                                ?dbpEntity rdfs:comment ?dbpDescription.
                                ?dbpEntity dbp:symbol ?symbol .
                                ?dbpEntity rdf:type ?exchange.
                                FILTER (lang(?title) = "en" && lang(?dbpDescription) = "en" && contains(str(?symbol),?sym))
                                FILTER(STRENDS(STR(?exchange),?exch))
                                VALUES ( ?key ?exch ?sym  ) 
                                    {{ {} }}
                            }}
                            """.format(value)
                        
                results_df = self.run_query(query, 'dbpedia')
                results = results.append(results_df, ignore_index = True) 
                time.sleep(0.2)
            return results

        def q_categorised_title(symbols: list):
            def batch():
                results = pd.DataFrame()
                symbols_split = [list(c) for c in mit.divide(5, symbols)]
                for i, split in enumerate(symbols_split):
                    print("Parsing symbol list of size: {}, List: {}/{}".format(len(split), i+1, len(symbols_split)))
                    values = []
                    for s in split:
                        s_members = s.split('|')
                        exchange_symbol_string = ''.join(s_members[:-2])
                        exchange = s_members[0]
                        title = s_members[3]
                        values.append("""( "{}" "{}") """.format(exchange_symbol_string, title))
                    values = ''.join(values)
                        
                    query = """
                            PREFIX yago: <http://dbpedia.org/class/yago/>
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                            PREFIX owl: <http://www.w3.org/2002/07/owl#>

                            SELECT DISTINCT ?key ?title ?dbpDescription ?symbol ?exchange ?dbpEntity ?wdEntity
                            WHERE {{
                                ?dbpEntity rdfs:label ?title.
                                ?dbpEntity rdfs:comment ?dbpDescription.
                                OPTIONAL {{ ?dbpEntity dbp:symbol ?symbol .}}
                                ?dbpEntity owl:sameAs ?wdEntity.
                                ?dbpEntity rdf:type ?exchange.
                                FILTER (lang(?title) = "en" && lang(?dbpDescription) = "en" && contains(lcase(?title),?label) && strstarts(str(?wdEntity),"http://www.wikidata.org/entity/")).
                                FILTER(?exchange IN (yago:WikicatCompaniesListedOnNASDAQ,yago:WikicatCompaniesListedOnTheNewYorkStockExchange))
                                VALUES ( ?key ?label ) 
                                    {{ {} }}
                            }}
                            """.format(values)
                    results_df = self.run_query(query, 'dbpedia')
                    results = results.append(results_df, ignore_index = True) 
                    time.sleep(0.5)
                return results

            def individual():
                results = pd.DataFrame()
                for i, s in enumerate(symbols):
                    s_members = s.split('|')
                    exchange, symbol = s_members[:-2]
                    exchange_symbol_string = ''.join(s_members[:-2])
                    title = s_members[3]
                    value = """( "{}" "{}") """.format(exchange_symbol_string, title)
                    print("Parsing symbol: {}, List: {}/{}".format(exchange_symbol_string, i+1, len(symbols)))
                    
                    # ?dbpEntity owl:sameAs ?wdEntity.
                    query = """
                            PREFIX yago: <http://dbpedia.org/class/yago/>
                            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                            PREFIX owl: <http://www.w3.org/2002/07/owl#>

                            SELECT DISTINCT ?key ?title ?dbpDescription ?symbol ?exchange ?dbpEntity
                            WHERE {{
                                ?dbpEntity rdfs:label ?title.
                                ?dbpEntity rdfs:comment ?dbpDescription.
                                OPTIONAL {{ ?dbpEntity dbp:symbol ?symbol .}}
                                ?dbpEntity rdf:type ?exchange.
                                FILTER (lang(?title) = "en" && lang(?dbpDescription) = "en" && contains(lcase(?title),?label)).
                                FILTER(?exchange IN (yago:WikicatCompaniesListedOnNASDAQ,yago:WikicatCompaniesListedOnTheNewYorkStockExchange))
                                VALUES ( ?key ?label ) 
                                    {{ {} }}
                            }}
                            """.format(value)
                    results_df = self.run_query(query, 'dbpedia')
                    results = results.append(results_df, ignore_index = True)
                    time.sleep(0.15)
                return results

            results = locals()[self.query_rate.lower()]()
            return results

        def q_title_tradedas(symbols: str):
            results = pd.DataFrame()
            for i, s in enumerate(symbols):
                s_members = s.split('|')
                exchange, symbol = s_members[:-2]
                exchange_symbol_string = ''.join(s_members[:-2])
                title = s_members[3]
                if title.endswith('co'):
                    title = title.replace(' co', '')
                if exchange == "NYSE":
                    exchange = "New_York_Stock_Exchange"
                #value = """( "{}" "{}") """.format(exchange_symbol_string, title)
                print("Parsing symbol: {}, List: {}/{}".format(exchange_symbol_string, i+1, len(symbols)))

                # query = """
                # PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                # PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                # PREFIX dbpedia2: <http://dbpedia.org/property/>

                # PREFIX dbpedia2: <http://dbpedia.org/property/>

                # SELECT DISTINCT ?key ?item ?title ?traded ?dbpDescription
                # WHERE {{
                # ?item rdfs:label ?title.
                # ?item rdfs:comment ?dbpDescription.
                # ?item dbpedia2:tradedAs ?traded.
                # FILTER(contains(str(lcase(?title)),?label) && lang(?dbpDescription) = "en")
                # VALUES (?key ?label) {{ {} }}
                # }}
                # """.format(value)
                query = """
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                PREFIX dbpedia2: <http://dbpedia.org/property/>
                PREFIX dct: <http://purl.org/dc/terms/>

                SELECT DISTINCT ?key ?item ?title ?subject ?dbpDescription
                                WHERE {{
                                ?item rdfs:label ?title.
                                ?item rdfs:comment ?dbpDescription.
                                ?item dct:subject ?subject.
                                ?title bif:contains "'{}'".
                                FILTER(contains(str(?subject), "{}") && lang(?dbpDescription) = "en").
                                VALUES (?key) {{ ("{}") }}
                                }}
                """.format(title, exchange, exchange_symbol_string)
                results_df = self.run_query(query, 'dbpedia')
                results = results.append(results_df, ignore_index = True)
                time.sleep(0.15)
            return results

        symbols = []
        for _, row in self.not_found.iterrows():
            symbol = row.exchange+'|'+row.symbol+'|'+str(row.wdEntity)+'|'+row.title
            symbols.append(symbol)

        results = locals()[self.query_type.lower()](symbols)
            
        print("Size of results returned: {}".format(results.shape[0]))
        return results

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

    def merge_and_remove_duplicates(self, merge_on, variables):
        def clean_duplicates(df):
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

        self.df = self.df.merge(self.results, on=merge_on, how='left')
        duplicate_df = pd.concat(g for _, g in self.df.groupby(merge_on[0]) if len(g) > 1)
        if 'symbol' in merge_on:
            duplicate_df = duplicate_df[['title_x', 'title_y']]
            indexes = clean_duplicates(duplicate_df)
            self.df = self.df.drop(self.df.index[indexes])
        for v in variables:
            self.df[v] = self.df[v+'_x'].where(self.df[v+'_y'].isnull(), self.df[v+'_y'])
            if 'symbol' in merge_on:
                cols = list(self.df)
                cols.insert(1, cols.pop(cols.index('title')))
                self.df = self.df.ix[:, cols]
            self.df = self.df.drop(columns=[v+'_x', v+'_y'])
        if 'title' in merge_on: self.df = self.df.drop_duplicates(subset=['symbol', 'exchange'])

    def dbpedia_cleaner(self):
        def levenshtein_comparison(df):
            results = pd.DataFrame()
            tickers = pd.read_csv('./utils/secwiki_tickers.csv')
            rows = {}
            for _, row in df.iterrows():
                if row.key == "NASDAQ|FBMS": continue
                match_col = tickers.loc[tickers['Ticker'] == row.symbol]
                if not match_col.empty and not pd.isna(match_col.Name.values[0]):
                    lev = _levenshtein.ratio(row.title, match_col.Name.values[0])
                    if lev > 0.55:
                        if row.key in rows and lev > rows[row.key][1]:
                            rows[row.key] = [row, lev]
                        else:
                            rows[row.key] = [row,lev]
                        print(row.dbpDescription[:50], row.key, row.title, colored("MATCH", "blue"), match_col.Name.values[0], match_col.Ticker.values[0], lev)
            for _, v in rows.items():
                results = results.append(v[0], ignore_index = True)
            #print(results[['dbpDescription', 'exchange', 'key', 'symbol', 'title']])
            sys.exit(0)
            return results

        self.results = pd.read_csv(self._rpath+'tag_cat_results_new.csv', sep='\t')
        # self.df = self.df.rename(columns={
        #                 'symbol':'wdSymbol',
        #                 'exchange':'wdExchange'
        #             })
        self.df['key'] = self.df['key'].str.replace('NYSE','NYSE|')
        self.df['key'] = self.df['key'].str.replace('NASDAQ','NASDAQ|')
        # self.df['wdExchange'] = self.df['wdExchange'].str.replace('NewYorkStockExchange','NYSE')
        self.df['exchange'], self.df['symbol'] = self.df['key'].str.split('|', 1).str
        # self.df['keep'] = False
        # for i, row in self.df.iterrows():
        #     self.df.at[i, 'keep'] = row.wdExchange.endswith(row.exchange)
        # self.df = self.df[self.df['keep']]
        self.df = levenshtein_comparison(self.df)
        for i, row in self.results.iterrows():
            match_row = self.df.loc[self.df['symbol'] == row.symbol]
            
            if not match_row.empty and pd.isna(row.dbpEntity):
                if 'wdEntity' in self.df.index and pd.isna(match_row.wdEntity.values[0]):
                    self.results.at[i, 'wdEntity'] = match_row.wdEntity.values[0]
                self.results.at[i, 'dbpEntity'], self.results.at[i, 'dbpDescription'] = match_row.item.values[0], match_row.dbpDescription.values[0]

    def clean_results(self, df: pd.DataFrame, keyword: str):
        def levenshtein_comparison(results_df: pd.DataFrame):
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

        df = df.copy()
        df = df[df.exchange.str.contains('^NASDAQ$|^NYSE$')]
        regex_companies = re.compile(r'(?:\s+(?:Incorporated|Corporation|Company|Inc Common Stock|QQQ|ETF|PLC|SA|Inc|Corp|Ltd|LP|plc|Group|The|Limited|Partners|nv|Financial|Services|bancshares|semiconductor|foods|energy))+\s*$', flags=re.IGNORECASE)
        df['title'] = df['title'].str.replace('[^\w\s]','')
        df['title'] = df['title'].str.strip()
        df['title'] = df['title'].str.replace(' +|The ', ' ', regex=True)
        df['title'] = df['title'].str.replace('Company', 'Co', regex=True)
        df['title'] = df['title'].str.replace(regex_companies, '')
        df['title'] = df['title'].str.strip()
        df['title'] = df['title'].str.lower()

        #AFTER RESULTS
        if keyword is 'match_names':
            return levenshtein_comparison(df)
        print("Size of results after cleaning exchanges: {}".format(df.shape[0]))
        return df

    def run(self):
        def wikidata():
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

        def dbpedia():
            if self.results.empty:                
                self.not_found = self.df[self.df.wdEntity.isna() & self.df.dbpEntity.isna()]
                self.results = self.dbp_symbols_query_gen()
                self.results.to_csv(self._rpath+'tag_cat_dbpedia_results.csv', sep='\t', index=False)
                return
            self.dbpedia_cleaner()
            self.results.to_csv(self._rpath+'tag_cat_results_new.csv', sep='\t', index=False)

        locals()[self.source.lower()]()
            

if __name__ == "__main__":
    queryer = Queryer('dbpedia', 'q_title_tradedas', 'individual')
    queryer.run()