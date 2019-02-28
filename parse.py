import os, json, sys, logging, csv
from datetime import datetime
import pandas as pd
import spacy, pycountry, multiprocessing, arrow
from  more_itertools import unique_everseen

from utils.placenames import us_states, ca_prov, countries


class AttributeParser:
    def __init__(self, limit: str):
        self.rpath = '/media/ntfs/st_2017'
        self.wpath = './data/csv/'
        self.logpath = './log/io/csv/'

        self.files = [f for f in os.listdir(self.rpath) if os.path.isfile(os.path.join(self.rpath, f))]
        self.files.sort()
        self.files = self.files[:next(self.files.index(x) for x in self.files if x.endswith(limit))]

    def logger(self):
        """ Sets the logger configuration to report to both std.out and to log to ./log/io/csv/
        Also sets the formatting instructions for the log file, prints Time, Current Thread, Logging Type, Message.

        """
        logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
                handlers=[
                    logging.FileHandler("{0}/{1}_log ({2}).log".format(self.logpath, str(datetime.now())[:-7],'metadata_csv')),
                    logging.StreamHandler(sys.stdout)
                ])
    
    def parse(self, l) -> tuple:
        """ Takes in a single line and attempts to retrieve user and item information for feature engineering.
        
        Will return a tuple filled with None values if:
            * No cashtags are found with at least one industry tag.
        If there are no cashtags at all in a single tweet, the line will be skipped.

        Returns:
            tuple: Returns a tuple of User ID, User location data, Item ID, Item Timestamp, Item Body, Cashtag Titles, Cashtag Industries, Cashtag Sectors

        """

        d = json.loads(l)['data']
        symbols = d.get('symbols', False)
        titles, cashtags, industries, sectors = [], [], [], []

        if symbols:                     # Checks to see if cashtags exist in tweet
            for s in symbols:
                s_title, s_symbol, s_industry, s_sector = s.get('title'), s.get('symbol'), s.get('industry'), s.get('sector')  # Check to see if a cashtag contains an 'Industry' tag, otherwise skip
                if not s_industry:
                    continue

                user_id, user_location = d.get('user').get('id'), d.get('user').get('location')
                item_id, item_timestamp, item_body = d.get('id'), d.get('created_at'), d.get('body').replace('\t',' ').replace('\n','')

                titles[len(titles):], cashtags[len(cashtags):], industries[len(industries):], sectors[len(sectors):] = tuple(zip((s_title, s_symbol, s_industry, s_sector)))

        return (user_id, user_location, item_id, item_timestamp, item_body, titles, cashtags, industries, sectors) if industries else ((None),)*9
                 
    def file_writer(self) -> int:
        """ Responsible for writing to ct_industry.csv in ./data/csv/ and logging each file read.
        
        Passes single line into self.parse which returns a tuple of metadata, this is then written
        to a single row in the CSV, provided the tuple returned by self.parse does not contain any None values.

        Returns:
            int: Returns the number of documents in the file.

        """

        logger = logging.getLogger()

        with open (os.path.join(self.wpath, 'metadata.csv'), 'w', newline='') as stocktwits_csv:
            fields = ['user_id', 'item_id', 'user_location', 'item_timestamp', 'item_body','item_titles','item_cashtags','item_industries','item_sectors']
            writer = csv.DictWriter(stocktwits_csv, fieldnames=fields, delimiter='\t')
            writer.writeheader()
            line_count = 0

            for fp in self.files:
                logger.info('Reading file {0}'.format(fp))
                with open(os.path.join(self.rpath, fp)) as f:
                    for l in f:
                        if not all(self.parse(l)):
                            continue
                        user_id, user_location, item_id, item_timestamp, item_body, titles, cashtags, industries, sectors = self.parse(l)
                        writer.writerow({'user_id':user_id, 'item_id':item_id, 'user_location':user_location, 'item_body':item_body,'item_timestamp':item_timestamp, 'item_titles':'|'.join(map(str, titles)),'item_cashtags':'|'.join(map(str, cashtags)), 'item_industries':'|'.join(map(str, industries)),'item_sectors':'|'.join(map(str, sectors))})
                        line_count+=1
        
        return line_count

    def run(self):
        self.logger()
        logger = logging.getLogger()
        logger.info("Starting CSV write")

        line_count = self.file_writer()

        logger.info("Finished CSV write with {0} documents".format(line_count))



class AttributeCleaner:
    def __init__(self, tweet_frequency=160):
        self.logpath = './log/io/csv/cleaner/'
        self.rpath = './data/csv/metadata.csv'
        self.df = self.csv_to_dataframe()
        spacy.prefer_gpu()
        self.nlp = spacy.load('en')

        self.tweet_freq = tweet_frequency

    def logger(self):
        """ Sets the logger configuration to report to both std.out and to log to ./log/io/csv/cleaner/
        Also sets the formatting instructions for the log file, prints Time, Current Thread, Logging Type, Message.

        """

        logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
                handlers=[
                    logging.FileHandler("{0}/{1}_log ({2}).log".format(self.logpath, str(datetime.now())[:-7],'metadata_csv_clean')),
                    logging.StreamHandler(sys.stdout)
                ])

    def csv_to_dataframe(self) -> pd.DataFrame:
        """Reads in CSV file declared in __init__ (self.rpath) and converts it to a number of Pandas DataFrames.
            
        Returns:
            pandas.DataFrame: Returns metadata CSV file as pandas DataFrame.

        """

        logger = logging.getLogger()
        data = pd.read_csv(self.rpath, delimiter='\t')
        logger.info("Read file with {0} entries".format(len(data.index)))
        return data

    def dataframe_to_csv(self):
        """Writes cleaned dataset back to CSV format.

        """
        
        logger = logging.getLogger()
        self.df.to_csv(path_or_buf='./data/csv/metadata_clean.csv', index=False, sep='\t')
        logger.info("Written CSV at {0} with {1} entries".format(str(datetime.now())[:-7], len(self.df.index)))

    def clean_timestamps(self):
        logger = logging.getLogger()
        self.df['item_timestamp'] = self.df['item_timestamp'].str.replace('T', ' ')
        self.df['item_timestamp'] = self.df['item_timestamp'].str.replace('Z', '')
        logger.info('Starting formatted timestamp to UNIX timestamp conversion...')
        for i, data in self.df.iterrows():
            ts = arrow.get(data['item_timestamp'], 'YYYY-MM-DD HH:mm:ss').timestamp
            self.df.at[i, 'item_timestamp'] = ts
        logger.info('UNIX timestamp conversion complete')

    def iterate_location_data(self, d) -> pd.DataFrame:
        """Uses spaCy's NER to detect locations in 'user_location' DataFrame field. Malformed locations are marked and later dropped.
        
        Function is ran as a process containing a chunk of the input DataFrame. The Named Entity Recognition
        in spaCy is then used to detect placenames and malformed or otherwise undetectable entries in
        'user_location' are marked in the 'user_loc_check' as False. Rows where this is marked as false
        are later dropped from the recompiled DataFrame once the entire process has been carried out.

        Country names are converted to their 3-letter ISO code equivalent, eg. 'Germany' -> 'DEU'.
        A lookup is performed for U.S. states and Canadian provinces in a combined, imported dictionary
        and then converted to their full name equivalent, ie. 'MD' -> 'Maryland', 'BC' -> 'British Columbia'.
        Each entity is then converted to lowercase and spaces removed.
            
        Returns:
            pandas.DataFrame: Returns chunked pandas DataFrame to be recompiled in self.clean_user_locations.

        """

        logger = logging.getLogger()
        lookup = {**us_states, **ca_prov}

        for i, data in d.iterrows():
            doc = self.nlp(data['user_location'])
            gpe_check = all(ent.label_ == 'GPE' for ent in doc.ents)
            if gpe_check and doc.ents:
                location = [str(x) for x in list(doc.ents)]
                try:
                    for p in location:
                        if p.lower() in countries:
                            country_conversions = {'taiwan':'twn', 'czech republic': 'cze'}
                            location[location.index(p)] = country_conversions[p.lower()] if p.lower() in country_conversions else pycountry.countries.get(name=p).alpha_3
                        if len(p) == 2:
                            province_full = lookup.get(p.upper(), None)
                            if province_full:
                                if province_full is 'Louisiana' and location.index(p) is 0: province_full = 'Los Angeles'
                                location = [province_full if x==p else x for x in location]
                    location = list(unique_everseen([x.replace(' ','').lower() for x in location]))
                    d.at[i, 'user_location'], d.at[i, 'user_loc_check'] = '|'.join(location), True
                except AttributeError:
                    continue
        return d

    def clean_user_locations(self):
        """Cleans DataFrame of malformed location files and only keeps rows with NER-parseable locations.

        Begins a python multiprocessing pool which iterates through the DataFrame row-by-row
        as seen in self.iterate_location_data. Results from each process are then compiled
        into a single DataFrame and the rows containing malformed locations are dropped.

        """

        logger = logging.getLogger()
        num_processes = multiprocessing.cpu_count()

        self.df['user_location'] = self.df['user_location'].astype(str)
        self.df['user_loc_check'] = False
        self.df = self.df[~self.df.user_location.str.contains(r'[0-9]')]

        chunk_size = int(self.df.shape[0]/(num_processes*4))
        chunks = [self.df.ix[self.df.index[i:i + chunk_size]] for i in range(0, self.df.shape[0], chunk_size)]
        index_size_original = len(self.df.index)

        logging.info('Beginning NER parsing...')
        pool = multiprocessing.Pool(processes=num_processes)
        result = pool.map(self.iterate_location_data, chunks)
        logging.info('Parsing complete, recompiling DataFrame...')

        for i in range(len(result)):
            self.df.ix[result[i].index] = result[i]

        cleaned_users = self.df[self.df.user_loc_check]
        logger.info("Removed users with malformed location information. Size of DataFrame: {0} -> {1}".format(index_size_original, len(cleaned_users.index)))
        self.df = cleaned_users
        self.df.drop('user_loc_check', axis=1)

    def clean_rare_users(self):
        """Removes users who have made less than k tweets, as defined in __init__ by self.tweet_freq.
            
        """

        logger = logging.getLogger()
        data_count, k = len(self.df.index), self.tweet_freq
        cleaned_users = self.df.groupby('user_id').filter(lambda x: len(x) > k)
        logger.info("Removed users with less than {0} tweets. Size of DataFrame: {1} -> {2}".format(k, data_count, len(cleaned_users.index)))
        self.df = cleaned_users


    def run(self):
        self.logger()
        self.clean_timestamps()
        self.clean_rare_users()
        self.clean_user_locations()
        self.dataframe_to_csv()
        # self.dataframe_to_csv()
        # self.clean_user_locations()






if __name__ == "__main__":
    # ab = AttributeParser('2017_02_01') # 2017_02_01
    # ab.run()
    ac = AttributeCleaner(tweet_frequency=160)
    ac.run()