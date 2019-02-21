import os, json, sys, logging, csv
from datetime import datetime
import pandas as pd


class AttributeParser:
    def __init__(self, limit: str):
        self.rpath = '/media/ntfs/st_2017'
        self.wpath = './data/csv/'
        self.logpath = './log/io/'

        self.files = [f for f in os.listdir(self.rpath) if os.path.isfile(os.path.join(self.rpath, f))]
        self.files.sort()
        self.files = self.files[:next(self.files.index(x) for x in self.files if x.endswith(limit))]

    def logger(self):
        """ Sets the logger configuration to report to both std.out and to log to ./log/io/
        Also sets the formatting instructions for the log file, prints Time, Current Thread, Logging Type, Message.

        """
        logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s",
                handlers=[
                    logging.FileHandler("{0}/{1}_log ({2}).log".format(self.logpath, str(datetime.now())[:-7],'ct_industry_csv')),
                    logging.StreamHandler(sys.stdout)
                ])
    
    def parse(self, l) -> tuple:
        """ Takes in a single line and attempts to retrieve User ID, Item ID, list of Industry Tags, list of Cashtags.
        Will return a tuple filled with None values if:
            * No cashtags are found with at least one industry tag.
        If there are no cashtags at all in a single tweet, the line will be skipped.

        """

        d = json.loads(l)['data']
        symbols = d.get('symbols', False)
        industries, sectors, cashtags = [], [], []

        if symbols:                     # Checks to see if cashtags exist in tweet
            for s in symbols:
                industry, sector = s.get('industry'), s.get('sector')  # Check to see if a cashtag contains an 'Industry' tag, otherwise skip
                if not industry:
                    continue

                uid, uloc, iid, ii, isec, ic = d['user']['id'], d['user']['location'],d['id'], industry, sector, s['symbol']
                industries.append(ii)
                sectors.append(isec)
                cashtags.append(ic)

        return (uid, uloc, iid, industries, sectors, cashtags) if industries else ((None),)*6
                 
    def file_writer(self):
        """ Responsible for writing to ct_industry.csv in ./data/csv/ and logging each file read.
        Passes single line into self.parse which returns a tuple of metadata, this is then written
        to a single row in the CSV, provided the tuple returned by self.parse does not contain any None values.

        """

        logger = logging.getLogger()

        with open (os.path.join(self.wpath, 'metadata.csv'), 'w', newline='') as stocktwits_csv:
            fields = ['user_id', 'location','item_id', 'item_industries','item_sectors','item_cashtags']
            writer = csv.DictWriter(stocktwits_csv, fieldnames=fields, delimiter='\t')
            writer.writeheader()
            line_count = 0

            for fp in self.files:
                logger.info('Reading file {0}'.format(fp))
                with open(os.path.join(self.rpath, fp)) as f:
                    for l in f:
                        if not all(self.parse(l)):
                            continue
                        uid, uloc, iid, ii, isec, ic = self.parse(l)
                        # ii, isec, ic = "|".join(ii), "|".join(isec), "|".join(ic)
                        writer.writerow({'user_id':uid, 'location':uloc,'item_id':iid, 'item_industries':','.join(map(str, ii)),'item_sectors':','.join(map(str, isec)),'item_cashtags':','.join(map(str, ic))})
                        line_count+=1
        
        return line_count



    def run(self):
        self.logger()
        logger = logging.getLogger()
        logger.info("Starting CSV write")

        line_count = self.file_writer()

        logger.info("Finished CSV write with {0} documents".format(line_count))



class AttributeCleaner:
    def __init__(self):
        self.rpath = './data/csv/metadata.csv'
        self.df = self.csv_to_dataframe()

    def csv_to_dataframe(self):
        data = pd.read_csv(self.rpath, delimiter='\t')
        print("Read file with {0} entries".format(len(data.index)))
        return data

    def dataframe_to_csv(self):
        self.df.to_csv(path_or_buf='./data/csv/metadata_clean.csv', index=False, sep='\t')
        print("Written CSV at {0}".format(str(datetime.now())[:-7]))

    # def clean_user_locations(self):
    #     print(self.df)

    def clean_rare_users(self):
        data_count, k = len(self.df.index), 10
        cleaned_users = self.df.groupby('user_id').filter(lambda x: len(x) > k)
        print("Removed users with less than {0} tweets. Size of DataFrame: {1} -> {2}".format(k, data_count, len(cleaned_users.index)))
        self.df = cleaned_users


    def run(self):
        self.clean_rare_users()
        self.dataframe_to_csv()
        # self.clean_user_locations()






if __name__ == "__main__":
    ab = AttributeParser('2017_03_01')
    ab.run()
    ac = AttributeCleaner()
    ac.run()