from os import listdir
from os.path import isfile, join
import time
from datetime import timedelta
import spacy

nlp = spacy.load('en')
path = "./data/"

def tokens():
    store = []
    files = [f for f in listdir(path) if isfile(join(path, f))]

    start_time = time.monotonic()
#    for filename in nlp.pipe(files, batch_size=10000, n_threads=3):
    for filename in files:
        with open(path+filename) as f:
            #head = [next(f) for x in range(5)]
            for line in f:
                tokens = nlp(line.lower(), disable=['parser', 'tagger', 'ner'])
                tokens = [token.lemma_ for token in tokens if not token.orth_.isspace() and token.is_alpha and not token.is_stop and token.lemma_ != '-PRON-' and len(token.orth_) != 1]
                if len(tokens) != 0: store.append(tokens)

    end_time = time.monotonic()
    print("Time taken to tokenize:",timedelta(seconds=end_time - start_time))

    return store