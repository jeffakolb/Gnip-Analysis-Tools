import collections
import operator
from gnip_analysis_tools.nlp.utils import token_ok, term_comparator, sanitize_string

"""

This file is just a bunch of class definitions. Each class defines a 
measurement, which make one or more counts of things in the Tweet payload.

To work with the time series building code, each class must implement 
the following methods:
    add_tweet(dict: tweet)
    get()

The 'add_tweet' function is the entry point; it takes a dict representing a
JSON-formatted Tweet payload. The 'get' function is the exit; it returns a 
sequence of tuples of (current count, count name). Any number of counts may
be managed by a single measurement class.

--------------------

MeasurementBase class

MeasurementBase is a convenient base class that defines 'add_tweet' such that the
measurement is only updated by tweets passing a set of filters, as defined
below.  If a tweet passes all filters, it is passed to the 'update' method,
which must be implemented in the child class. MeasurementBase also provides a
naming function, 'get_name'.

Configuration parameters (e.g. the minimum number of counts to return) are 
passed as keyword arguments to the constructor, and must be attached to the object
in all constructors.

Usage:

All classes inheriting from MeasurementBase must define or inherit the methods:
 - update(dict: tweet):
    updates internal data store with Tweet info; no return value
 - get():
    returns a representation of internal data store
Optionally, a class may define:
 - combine(obj: other_measurement)
    updates the current measurement with the data in "other_measurment"
This method defines the way in which two measurement instances of
the same type are combined.

Measurements can be selectively applied to tweets by
defining the class member 'filters', which is a list of 3-tuples:
([list of JSON key names to access the Tweet element]
, comparison_function
, comparison_value).
Tweets will only be parsed if comparison_function(Tweet_element,comparison_value)
is true.


class naming convention: 
    classes that implement 'get' should contain 'Get' in the name
    classes defining counters variables should contain 'Counter' or 'Counters' in the name

"""
class MeasurementBase(object):
    """ 
    Base class for measurement objects.
    It implements 'get_name' and 'add_tweet'. 
    Note that 'add_tweet' calls 'update', 
    which must be defined in a derived class."""
    def __init__(self, **kwargs):
        """ basic ctor to add arguments as class attributes"""
        [setattr(self,key,value) for key,value in kwargs.items()]
    def get_name(self):
        return self.__class__.__name__
    def add_tweet(self,tweet):
        """ this method is called by the aggregator script, for each enriched tweet """
        def get_element(data, key_path):
            """ recursive helper function to get tweet elements """
            key = key_path[0]
            if len(key_path) == 1:
                return data[key]
            else:
                new_key_path = key_path[1:]
                obj = data[key]
                if isinstance(obj,list):
                    results = []
                    for o in obj:
                        results.append( get_element(o,new_key_path) )
                    return results
                else:
                    return get_element(obj,new_key_path)
        # return before calling 'update' if tweet fails any filter
        if hasattr(self,"filters"):
            for key_path,comparator,value in self.filters:
                data = get_element(tweet,key_path)
                if not comparator(data,value):
                    return 
        self.update(tweet)
    def combine(self,_):
        raise NotImplementedError("Please implement a 'combine' method for your measurement class")

class Counter(MeasurementBase):
    """ base class for any single integer counter """
    def __init__(self, **kwargs): 
        super().__init__(**kwargs)
        self.counter = 0
    def get(self):
        return [(self.counter,self.get_name())]
    def combine(self,new_counter):
        self.counter += new_counter.counter

class Counters(MeasurementBase):
    """ base class for multiple integer counters """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.counters = collections.defaultdict(int)
    def get(self):
        return [(count,sanitize_string(name)) for name,count in self.counters.items()]
    def combine(self,new_counters):
        for new_name,new_count in new_counters.counters.items():
            if new_name in self.counters.keys():
                self.counters[new_name] += new_count
            else:
                self.counters[new_name] = new_count


# these classes provide 'get_tokens' methods for
# various tweet components

class TokenizedBody(object):
    """ provides a 'get_tokens' method for tokens in tweet body 
        assumes Stanford NLP or NLTK enrichment was run on Tweet body"""
    def get_tokens(self,tweet):
        good_tokens = [] 
        if 'BodyNLPEnrichment' in tweet['enrichments']:
            tokens = [token 
                    for sentence in tweet['enrichments']['BodyNLPEnrichment']['sentences'] 
                    for token in sentence ]
        elif 'NLTKSpaceTokenizeBody' in tweet['enrichments']:
            tokens = tweet['enrichments']['NLTKSpaceTokenizeBody']
        else:
            raise KeyError('No NLP enrichment found!')

        for token in tokens:
            if token_ok(token):
                good_tokens.append(token)
        return good_tokens
class TokenizedBio(object):
    """ provides a 'get_tokens' method for tokens in user bio 
        assumes Stanford NLP or NLTK enrichment was run on Tweet user bio"""
    def get_tokens(self,tweet):
        good_tokens = [] 
        if 'BioNLPEnrichment' in tweet['enrichments']:
            tokens = [token 
                    for sentence in tweet['enrichments']['BioNLPEnrichment']['sentences'] 
                    for token in sentence ]
        elif 'NLTKSpaceTokenizeBio' in tweet['enrichments']:
            tokens = tweet['enrichments']['NLTKSpaceTokenizeBio']
        else:
            raise KeyError('No NLP enrichment found!')

        for token in tokens: 
            if token_ok(token):
                good_tokens.append(token)
        return good_tokens

# this class provides a generic update method multi-counter classes

class CountersOfTokens(Counters):
    """
    this class provides a generic update method
    for multi-counter classes implementing "get_tokens" 
    """
    def update(self,tweet):
        for token in self.get_tokens(tweet):
            self.counters[token] += 1

# these classes provide specialized 'get' methods
# for classes with 'counters' members

class GetBase(object):
    """ 
    base class for classes implementing "get";
    sanitizes counter names for output to CSV
    """
    def get_init(self):
        self.counters = {sanitize_string(name):count for name,count in self.counters.items()}

class GetTopCounts(GetBase):
    """ provides a 'get' method that deals with top-n type measurements 
        must define a 'self.counters' variable """
    def get(self):
        self.get_init()
        if not hasattr(self,'top_k'):
            setattr(self,'top_k',20)
        sorted_top = list( reversed(sorted(self.counters.items(),key=operator.itemgetter(1))) ) 
        return [(count,name) for name,count in sorted_top[:self.top_k] ] 
class GetCutoffCounts(GetBase):
    """ drops items with < 'min_n'/3 counts """
    def get(self):
        self.get_init()
        if not hasattr(self,'min_n'):
            setattr(self,'min_n',3)
        self.counters = { token:count for token,count in self.counters.items() if count >= self.min_n }
        return [(count,name) for name,count in self.counters.items() ]
class GetCutoffTopCounts(GetCutoffCounts):
    def get(self):
        self.get_init()
        if not hasattr(self,'top_k'):
            setattr(self,'top_k',20)
        self.counters = super(GetCutoffTopCounts).get()
        sorted_top = list( reversed(sorted(self.counters.items(),key=operator.itemgetter(1))) ) 
        return [(count,name) for name,count in sorted_top[:self.top_k] ]

# term counter helpers

class BodyTermCounters(CountersOfTokens,TokenizedBody):
    """ provides an update method that counts instances of tokens in body """
class BioTermCounters(CountersOfTokens,TokenizedBio):
    """ provides an update method that counts instances of tokens in bio"""

class SpecifiedBodyTermCounters(Counters,TokenizedBody):
    """ base class for integer counts of specified body terms
    derived classes must define 'term_list' """
    def update(self,tweet):
        for token in self.get_tokens(tweet):
            for term in self.term_list:
                if term_comparator(token,term):
                    self.counters[term] += 1
class SpecifiedBioTermCounters(Counters,TokenizedBio):
    """ base class for integer counts of specified body terms
    derived classes must define 'term_list' """
    def update(self,tweet):
        for token in self.get_tokens(tweet):
            for term in self.term_list:
                if term_comparator(token,term):
                    self.counters[term] += 1

# top body term parent classes 

class AllBodyTerms(BodyTermCounters):
    pass
class TopBodyTerms(GetTopCounts,BodyTermCounters):
    pass
class CutoffBodyTerms(GetCutoffCounts,BodyTermCounters):
    pass
class CutoffTopBodyTerms(GetCutoffTopCounts,BodyTermCounters):
    pass

retweet_filter = (["verb"],operator.eq,"share")

class MentionCounters(Counters):
    def update(self,tweet):
        for mention in tweet["twitter_entities"]["user_mentions"]:
            self.counters[mention["name"]] += 1 
class TopMentions(GetTopCounts,MentionCounters):
    pass
class CutoffMentions(GetCutoffCounts,MentionCounters):
    pass
class CutoffTopMentions(GetCutoffTopCounts,MentionCounters):
    pass

#
# NLP
#

# NLTK uses (by default) the Penn Treebank tags:
# http://www.ling.upenn.edu/courses/Fall_2003/ling001/penn_treebank_pos.html

class NLTKBodyPOS():
    def get_tokens(self,tweet):
        tokens = []
        for token,pos in tweet["enrichments"]["NLTKPOSBody"]: 
            if pos == self.requested_pos:
                tokens.append(token)
        return tokens
class NLTKBioPOS():
    def get_tokens(self,tweet):
        tokens = []
        for token,pos in tweet["enrichments"]["NLTKPOSBio"]: 
            if pos == self.requested_pos:
                tokens.append(token)
        return tokens

"""
TODO
class CoreNLPBodyPOS():
    def get_tokens(self,tweet):
        tokens = []
        for token,pos in tweet["enrichments"]["CoreNLPPOSBody"]: 
            if pos == self.requested_pos:
                tokens.append(token)
        return tokens
class CoreNLPBioPOS():
    def get_tokens(self,tweet):
        tokens = []
        for token,pos in tweet["enrichments"]["CoreNLPPOSBio"]: 
            if pos == self.requested_pos:
                tokens.append(token)
        return tokens
"""

class BodyNNCountersNLTK(CountersOfTokens,NLTKBodyPOS):
    """ counts instances of NN tokens in body """
    requested_pos = "NN"
class BioNNCountersNLTK(CountersOfTokens,NLTKBioPOS):
    """ counts instances of NN tokens in bio"""
    requested_pos = "NN"
class BodyNNPCountersNLTK(CountersOfTokens,NLTKBodyPOS):
    """ counts instances of NNP tokens in body """
    requested_pos = "NNP"
class BioNNPCountersNLTK(CountersOfTokens,NLTKBioPOS):
    """ counts instances of NNP tokens in bio"""
    requested_pos = "NNP"
class BodyNNSCountersNLTK(CountersOfTokens,NLTKBodyPOS):
    """ counts instances of NNS tokens in body """
    requested_pos = "NNS"
class BioNNSCountersNLTK(CountersOfTokens,NLTKBioPOS):
    """ counts instances of NNS tokens in bio"""
    requested_pos = "NNS"
class BodyNNPSCountersNLTK(CountersOfTokens,NLTKBodyPOS):
    """ counts instances of NNPS tokens in body """
    requested_pos = "NNPS"
class BioNNPCountersNLTK(CountersOfTokens,NLTKBioPOS):
    """ counts instances of NNP tokens in bio"""
    requested_pos = "NNP"

