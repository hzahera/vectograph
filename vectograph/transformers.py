from sklearn.base import BaseEstimator, TransformerMixin
from rdflib import Graph, URIRef, Namespace  # basic RDF handling
import pandas as pd
from typing import  List


class RDFGraphCreator(BaseEstimator, TransformerMixin):
    """
    RDFGraphCreator Class inherits from  BaseEstimator and  TransformerMixin so that it can be used in sklearn Pipeline

    Given a Pandas Dataframe df, an instance of this class transforms df into knowledge graph and serialize it
    by using the rdflib library.

    Note that our initial experiments show that using rdflib (generated Graph and iterativly adding triples)
    appears to be slow.
    """

    def __init__(self, path, kg_format):

        self.kg_path = path
        self.kg_format = kg_format

    def fit(self, x, y=None):
        """

        :param x:
        :param y:
        :return:
        """
        return self

    def transform(self, df):
        """
        Tabular data into Graph conversion.
        The index of df indivating the row in df considered as an event while each column considered as predicate.
        Consequently. Given a df having the following form
                                    index        col1    col2
                                    Event_0     a      c
                                    Event_1     b      d

        We generate   triples as shown below
                                    Event_0   col1   a
                                    Event_0   col2   c
                                    Event_1   col2   b
                                    Event_1   col2   d

        Note that a,b,c,d can have numerical types --including interger, float, double.
        as well as category type generated by discretization
        consider i.th row as eventgenerate

        index of the df consideres
        Update parameters using Adam

        Arguments:
        df -- a Pandas Dataframe
        Returns:
        g -- an instance of Graph() class from the rdflib library.

        self.kg_path - a string indicating the path where g is serialized.
        """
        print('Transformation starts')
        df.index = 'Event_' + df.index.astype(str)

        g = Graph()
        ppl = Namespace('http://dakiri.org/index/')
        schema = Namespace('http://schema.org/')

        for subject, row in df.iterrows():
            for predicate, obj in row.iteritems():
                if isinstance(obj, int):
                    g.add(
                        (URIRef(ppl + 'Event_' + subject), URIRef(schema + predicate), URIRef(ppl + 'num_' + str(obj))))
                elif isinstance(obj, float):
                    g.add((URIRef(ppl + 'Event_' + subject), URIRef(schema + predicate),
                           URIRef(ppl + 'float_' + str(obj))))
                elif isinstance(obj, str):
                    g.add(
                        (URIRef(ppl + 'Event_' + subject), URIRef(schema + predicate), URIRef(ppl + 'str_' + str(obj))))
                else:
                    raise ValueError

        self.kg_path += '.nt'
        g.serialize(self.kg_path, format='ntriples')

        return g, self.kg_path,


class KGSave(BaseEstimator, TransformerMixin):
    """
    KGCreator Class inherits from  BaseEstimator and  TransformerMixin so that it can be used in sklearn Pipeline

    Given a Pandas Dataframe df, an instance of this class transforms df into RDF knowledge graph in n-triples format
    and serialize it.

    Note that KGCreator class appears to be significantly faster RDFGraphCreator due to omitting rdflib.
    """

    def __init__(self, path, logger=None):
        self.kg_path = path
        self.logger = logger

    def fit(self, x, y=None):
        """
        :param x:
        :param y:
        :return:
        """
        return self

    @staticmethod
    def __valid_triple_create(subject, predicate, obj) -> str:
        """
        Given subject, predicate and obj we generate an RDF triple in the n-triple format.
        :param subject:
        :param predicate:
        :param obj:
        :return:
        """
        if str(obj) == 'nan':
            obj = str(predicate) + 'Dummy'

        if isinstance(obj, str):
            obj = '<' + obj.replace(" ", "") + '>'
        elif isinstance(obj, int):
            obj = '"' + str(obj) + '"^^<http://www.w3.org/2001/XMLSchema#integer>'
        elif isinstance(obj, float):
            obj = '"' + str(obj) + '"^^<http://www.w3.org/2001/XMLSchema#double>'
        else:
            print(type(obj))
            print('Literal is not understood:', obj)
            raise TypeError
        return '<' + subject + '>' + ' ' + '<' + predicate + '>' + ' ' + obj + ' .\n'

    def transform(self, df) -> str:
        """ Tabular data into Graph conversion.
        The index of df indicating the row in df considered as an event while each column considered as predicate.
        Consequently. Given a df having the following form
                                    index        col1    col2
                                    Event_0     a      c
                                    Event_1     b      d

        We generate   triples as shown below
                                    Event_0   col1   a
                                    Event_0   col2   c
                                    Event_1   col2   b
                                    Event_1   col2   d

        Note that a,b,c,d can have
                * numerical types --including integer, float, double.
                * category type
                * string (called object in pandas)
                * datetime
        Arguments:
        df -- a Pandas Dataframe
        Returns:
        self.kg_path - a string indicating the path where g is serialized.
        """
        if self.logger:
            self.logger.info('Knowledge Graph (KG) is being serialized')
            self.logger.info('Note that we impute missing values by converting a dummy entity per predicate.')
            # self.logger.info('We change the *type* column name as *rdf-syntax-ns#type* to make use of PYKE evaluation.')
        else:
            print('Knowledge Graph (KG) is being serialized')
            print('Note that we impute missing values by converting a dummy entity per predicate.')
            # print('We change the *type* column name as *rdf-syntax-ns#type* to make use of PYKE evaluation.')

        # Ineffective as df.iterrows is slow, one would improve this by using JIT provided by JAX.
        with open(self.kg_path, 'w') as writer:
            for subject, row in df.iterrows():
                for predicate, obj in row.iteritems():
                    writer.write(self.__valid_triple_create(subject, predicate, obj))

        return self.kg_path


class GraphGenerator(BaseEstimator, TransformerMixin):

    def __init__(self, kg_path='.', kg_name='SimpleKG.txt'):
        """

        :param kg_path: a path for serializing knowedge graph
        :param logger:
        :param kg_name:
        """
        self.kg_path = kg_path
        self.kg_name = kg_name

    @property
    def path(self):
        return self.kg_path + '/' + self.kg_name

    def fit(self, x, y=None):
        """
        :param x:
        :param y:
        :return:
        """
        return self

    @staticmethod
    def __valid_triple_create(subject, predicate, obj) -> str:
        """
        Given subject, predicate and obj we generate an RDF triple in the n-triple format.
        :param subject:
        :param predicate:
        :param obj:
        :return:
        """
        if str(obj) == 'nan':
            obj = str(predicate) + 'Dummy'

        if isinstance(obj, str):
            obj = '<' + obj.replace(" ", "") + '>'
        elif isinstance(obj, int):
            obj = '"' + str(obj) + '"^^<http://www.w3.org/2001/XMLSchema#integer>'
        elif isinstance(obj, float):
            obj = '"' + str(obj) + '"^^<http://www.w3.org/2001/XMLSchema#double>'
        else:
            print(type(obj))
            print('Literal is not understood:', obj)
            raise TypeError
        try:
            t = '<' + subject + '>' + ' ' + '<' + predicate + '>' + ' ' + obj + ' .\n'
        except TypeError as e:
            print(subject)
            print(predicate)
            print(obj)
            print('Wrong type')
            exit(1)

        return t

    @staticmethod
    def __sanity_checking(x):
        try:
            assert isinstance(x, pd.DataFrame)
        except AssertionError:
            print('Input must be dataframe. Exiting')
            exit(1)
        return x

    def transform(self, df) -> List:
        """ Tabular data into Graph conversion.
        The index of df indicating the row in df considered as an event while each column considered as predicate.
        Consequently. Given a df having the following form
                                    index        col1    col2
                                    Event_0     a      c
                                    Event_1     b      d

        We generate   triples as shown below
                                    Event_0   col1   a
                                    Event_0   col2   c
                                    Event_1   col2   b
                                    Event_1   col2   d

        Note that a,b,c,d can have
                * numerical types --including integer, float, double.
                * category type
                * string (called object in pandas)
                * datetime
        Arguments:
        df -- a Pandas Dataframe
        Returns:
        kg - a string indicating the path where g is serialized.
        """
        self.__sanity_checking(df)
        kg = []
        if self.kg_path is None and self.kg_name is None:
            for subject, row in df.iterrows():
                for predicate, obj in row.iteritems():
                    kg.append((subject, predicate, obj))
            return kg
        else:
            full_kg_path = self.kg_path + '/' + self.kg_name
            print('Knowledge Graph (KG) is being serialized')
            print('Note that we impute missing values by converting a dummy entity per predicate.')

            # Ineffective as df.iterrows is slow, one would improve this by using JIT provided by JAX.
            with open(full_kg_path, 'w') as writer:
                for subject, row in df.iterrows():
                    for predicate, obj in row.iteritems():
                        kg.append((subject, predicate, obj))
                        writer.write(self.__valid_triple_create(subject, predicate, obj))
            return kg
