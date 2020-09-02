from sklearn.base import BaseEstimator, TransformerMixin
from rdflib import Graph, URIRef, Namespace  # basic RDF handling
from .kge_models import *
from collections import Counter, defaultdict
from .helper_classes import Data
import torch
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from typing import Dict, Tuple
import math
import random
from scipy.spatial.distance import cosine
from sklearn.neighbors import NearestNeighbors
import hdbscan
import os
import itertools
from .utils import ignore_columns, create_experiment_folder, create_logger
import PYKE
from PYKE.helper_classes import *


class RDFGraphCreator(BaseEstimator, TransformerMixin):
    def __init__(self, path, dformat):

        self.kg_path = path
        self.kg_format = dformat

    def fit(self, x, y=None):
        """

        :param x:
        :param y:
        :return:
        """
        return self

    def transform(self, df):
        """

        :param df:
        :return:
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


class KGCreator(BaseEstimator, TransformerMixin):
    """
    Direct convertion to txt file.
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
    def __valid_triple_create(subject, predicate, obj):
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

    def transform(self, df):
        """

        :param df:
        :return:
        """

        # create dummy variables for nan.
        self.kg_path += '/GeneratedKG.nt'
        if self.logger:
            self.logger.info('Knowledge Graph (KG) is being serialized')
            self.logger.info('Note that we impute missing values by converting a dummy entity per predicate.')
            self.logger.info('We change the *type* column name as *rdf-syntax-ns#type* to make use of PYKE evaluation.')
        else:
            print('Knowledge Graph (KG) is being serialized')
            print('Note that we impute missing values by converting a dummy entity per predicate.')
            print('We change the *type* column name as *rdf-syntax-ns#type* to make use of PYKE evaluation.')
        # Ineffective as df.iterrows is slow, one would improve this by using JIT provided by JAX.

        with open(self.kg_path, 'w') as writer:
            for subject, row in df.iterrows():
                for predicate, obj in row.iteritems():
                    if 'resource/type' in str(predicate):
                        predicate = 'rdf-syntax-ns#type'
                    writer.write(self.__valid_triple_create(subject, predicate, obj))

        return self.kg_path


class ApplyKGE(BaseEstimator, TransformerMixin):
    def __init__(self, params):
        self.params = params
        self.cuda = torch.cuda.is_available()

        if 'logger' not in params:
            self.storage_path, _ = create_experiment_folder()
            self.logger = create_logger(name='Vectograph', p=self.storage_path)
        else:
            self.logger = params['logger']

    def fit(self, x, y=None):
        """
        :param x:
        :param y:
        :return:
        """
        return self

    def __evaluate_quality_of_link_prediction(self, data: Data, trained_model):
        """

        :param data:
        :param trained_model:
        :return:
        """
        self.logger.info(
            'The quality of embeddings are quantified. To this end, we randomly sampled 10 percent of ***the '
            'training dataset***.')
        hits = []
        ranks = []
        rank_per_relation = dict()
        for i in range(10):
            hits.append([])
        test_data_idxs = random.sample(data.train_data_idxs, len(data.train_data_idxs) // 10)
        inverse_relation_idx = dict(zip(data.relation_idxs.values(), data.relation_idxs.keys()))
        er_vocab = data.get_er_vocab(data.get_data_idxs(data.triples))

        for i in range(0, len(test_data_idxs), self.params['batch_size']):
            data_batch, _ = data.get_batch(er_vocab, test_data_idxs, i, self.params['batch_size'])
            e1_idx = torch.tensor(data_batch[:, 0])
            r_idx = torch.tensor(data_batch[:, 1])
            e2_idx = torch.tensor(data_batch[:, 2])
            if self.cuda:
                e1_idx = e1_idx.cuda()
                r_idx = r_idx.cuda()
                e2_idx = e2_idx.cuda()
            predictions = trained_model.forward(e1_idx, r_idx)

            for j in range(data_batch.shape[0]):
                filt = er_vocab[(data_batch[j][0], data_batch[j][1])]
                target_value = predictions[j, e2_idx[j]].item()
                predictions[j, filt] = 0.0
                predictions[j, e2_idx[j]] = target_value

            sort_values, sort_idxs = torch.sort(predictions, dim=1, descending=True)

            sort_idxs = sort_idxs.cpu().numpy()
            for j in range(data_batch.shape[0]):
                rank = np.where(sort_idxs[j] == e2_idx[j].item())[0][0]
                ranks.append(rank + 1)

                rank_per_relation.setdefault(inverse_relation_idx[data_batch[j][1]], []).append(rank + 1)

                for hits_level in range(10):
                    if rank <= hits_level:
                        hits[hits_level].append(1.0)

        self.logger.info('Hits@10: {0}'.format(sum(hits[9]) / (float(len(test_data_idxs)))))
        self.logger.info('Hits@3: {0}'.format(sum(hits[2]) / (float(len(test_data_idxs)))))
        self.logger.info('Hits@1: {0}'.format(sum(hits[0]) / (float(len(test_data_idxs)))))
        self.logger.info('Mean rank: {0}'.format(np.mean(ranks)))
        self.logger.info('Mean reciprocal rank: {0}'.format(np.mean(1. / np.array(ranks))))
        self.logger.info('###################### Hits per relation ####################################\n')
        for relations, ranks_ in rank_per_relation.items():
            rank_per_relation[relations] = np.array(ranks_)

            self.logger.info(
                '{0}: Mean Reciprocal Rank: {1}'.format(relations, np.mean(1. / rank_per_relation[relations])))

            hit10 = (rank_per_relation[relations] <= 10).sum() / len(rank_per_relation[relations])
            hit3 = (rank_per_relation[relations] <= 3).sum() / len(rank_per_relation[relations])
            hit1 = (rank_per_relation[relations] == 1).sum() / len(rank_per_relation[relations])

            self.logger.info('Hits@10 for {0}: {1}'.format(relations, hit10))
            self.logger.info('Hits@3 for {0}: {1}'.format(relations, hit3))
            self.logger.info('Hits@1 for {0}: {1}'.format(relations, hit1))
        self.logger.info('##########################################################\n')

    def __run_link_prediction_base_models(self, path_of_kg):
        self.logger.info('KG is being deserialized.')
        data = Data(path_of_kg)
        self.logger.info('|KG|={0} after pruning literals.'.format(len(data.triples)))

        model = None
        if self.params['model'] == 'Distmult':
            model = Distmult(
                params={'num_entities': len(data.entities), 'embedding_dim': self.params['embedding_dim'],
                        'num_relations': len(data.relations), 'input_dropout': self.params['input_dropout']})
        elif self.params['model'] == 'Tucker':
            model = Tucker(
                params={'num_entities': len(data.entities), 'embedding_dim': self.params['embedding_dim'],
                        'num_relations': len(data.relations), 'input_dropout': self.params['input_dropout']})
        elif self.params['model'] == 'Conve':
            model = Conve(
                params={'num_entities': len(data.entities), 'embedding_dim': self.params['embedding_dim'],
                        'num_relations': len(data.relations), 'input_dropout': self.params['input_dropout'],
                        'feature_map_dropout': 0.1,
                        'conv_out': 4, 'hidden_dropout': 0.2, 'projection_size': 24})
        elif self.params['model'] == 'Complex':
            model = Complex(
                params={'num_entities': len(data.entities), 'embedding_dim': self.params['embedding_dim'],
                        'num_relations': len(data.relations), 'input_dropout': 0.2})
        else:
            print('{0} is not found'.format(kge_name))
            raise ValueError

        assert model
        model.init()

        train_data_idxs = data.get_data_idxs(data.triples)
        er_vocab = data.get_er_vocab(train_data_idxs)
        er_vocab_pairs = list(er_vocab.keys())

        opt = torch.optim.Adam(model.parameters())
        num_iter = self.params['num_iterations'] + 1
        batch_size = self.params['batch_size']

        if 'K_for_PYKE' in self.params:
            del self.params['K_for_PYKE']
        self.logger.info('Training starts with following parameters:{0}'.format(self.params))
        for it in range(1, num_iter):
            model.train()
            np.random.shuffle(er_vocab_pairs)
            for j in range(0, len(er_vocab_pairs), batch_size):
                data_batch, targets = data.get_batch(er_vocab, er_vocab_pairs, j, batch_size)
                opt.zero_grad()
                e1_idx = torch.tensor(data_batch[:, 0])
                r_idx = torch.tensor(data_batch[:, 1])
                predictions = model.forward(e1_idx, r_idx)
                loss = model.loss(predictions, targets)
                loss.backward()
                opt.step()
        self.logger.info('Training ends.')

        # Perform Evaluation
        self.__evaluate_quality_of_link_prediction(data, model)

        # This depends on the model as some KGE learns core tensor, complex numbers etc.
        entity_emb = model.state_dict()['emb_e.weight'].numpy()  # E.weight, R.weight
        relation_emb = model.state_dict()['emb_rel.weight'].numpy()
        emb = pd.DataFrame(entity_emb, index=data.entities)
        rel = pd.DataFrame(relation_emb, index=data.relations)
        df = pd.concat([emb, rel])
        df.to_csv(self.params['storage_path'] + '/' + model.name + '_embeddings.csv')

        return df, data, self.logger

    def __run_pyke(self, path_of_kg):
        self.logger.info('PYKE being executed.')

        parser = Parser(p_folder=self.params['storage_path'], k=self.params['K_for_PYKE'])
        parser.set_logger(self.logger)
        parser.set_similarity_measure(PPMI)

        model = PYKE(logger=self.logger)
        holder = parser.pipeline_of_preprocessing(path_of_kg)
        vocab_size = len(holder)

        embeddings = randomly_initialize_embedding_space(vocab_size, self.params['embedding_dim'])
        learned_embeddings = model.pipeline_of_learning_embeddings(e=embeddings,
                                                                   max_iteration=self.params['num_iterations'],
                                                                   energy_release_at_epoch=0.0414,
                                                                   holder=holder, omega=0.45557)
        del embeddings
        del holder

        vocab = deserializer(path=self.params['storage_path'], serialized_name='vocabulary')
        learned_embeddings.index = [i for i in vocab]
        learned_embeddings.to_csv(
            self.params['storage_path'] + '/PYKE_' + str(self.params['embedding_dim']) + '_embd.csv')

        # This crude workaround performed to serialize dataframe with corresponding terms.
        learned_embeddings.index = [i for i in range(len(vocab))]

        df = pd.read_csv(self.params['storage_path'] + '/PYKE_50_embd.csv', index_col=0)
        return df, Data(path_of_kg), self.logger

    def transform(self, path_of_kg: str):
        """

        :param path_of_kg:
        :return:
        """

        if self.params['model'] == 'Pyke':
            return self.__run_pyke(path_of_kg)
        elif self.params['model'] in ['Distmult', 'Tucker', 'Conve', 'Complex']:
            return self.__run_link_prediction_base_models(path_of_kg)
        else:
            raise ValueError


class TypePrediction(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.logger = None

    def fit(self, x, y=None):
        """
        :param x:
        :param y:
        :return:
        """
        return self

    def transform(self, t: Tuple):
        """
        :param t:
        :param path_of_kg:
        :return:
        """

        def create_binary_type_vector(t_types, a_types):
            vector = np.zeros(len(all_types))
            i = [a_types.index(_) for _ in t_types]
            vector[i] = 1
            return vector

        def create_binary_type_prediction_vector(t_types, a_types):
            vector = np.zeros(len(all_types))
            i = [a_types.index(_) for _ in itertools.chain.from_iterable(t_types)]
            vector[i] += 1
            return vector

        embeddings, data, self.logger = t
        based_on_num_neigh = 3
        type_info = defaultdict(set)
        # get the types. Mapping from the index of subject to the index of object
        for triple in data.triples:  # literals are removed.
            s, p, o = triple

            if 'rdf-syntax-ns#type' in p:
                type_info[s].add(o)

        # get the index of objects / get type information =>>> s #type o
        all_types = sorted(set.union(*list(type_info.values())))

        # Consider only points with type infos.
        e_w_types = embeddings.loc[list(type_info.keys())]

        self.logger.info('# of entities having type information:{0}'.format(len(e_w_types)))

        neigh = NearestNeighbors(n_neighbors=based_on_num_neigh, algorithm='kd_tree', metric='euclidean',
                                 n_jobs=-1).fit(e_w_types)

        # Get similarity results for selected entities
        df_most_similars = pd.DataFrame(neigh.kneighbors(e_w_types, return_distance=False))

        # Reindex the target
        df_most_similars.index = e_w_types.index.values

        # As sklearn implementation of kneighbors returns the point itself as most similar point
        df_most_similars.drop(columns=[0], inplace=True)

        # Map back to the original indexes. KNN does not consider the index of Dataframe.
        mapper = dict(zip(list(range(len(e_w_types))), e_w_types.index.values))
        # The values of most similars are mapped to original vocabulary positions
        df_most_similars = df_most_similars.applymap(lambda x: mapper[x])

        k_values = [1, 3, 5, 10, 15, 30, 50, 100]

        self.logger.info('K values: {0}'.format(k_values))
        for k in k_values:
            self.logger.info('##### {0} #####'.format(k))
            similarities = list()
            for _, S in df_most_similars.iterrows():
                true_types = type_info[_]
                type_predictions = [type_info[_] for _ in S.values[:k]]

                vector_true = create_binary_type_vector(true_types, all_types)
                vector_prediction = create_binary_type_prediction_vector(type_predictions, all_types)

                sim = cosine(vector_true, vector_prediction)
                similarities.append(1 - sim)

            report = pd.DataFrame(similarities)
            self.logger.info('Mean type prediction: {0}'.format(report.mean().values))

        return embeddings, data, self.logger


class ClusterPurity(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.logger = None

    def fit(self, x, y=None):
        """
        :param x:
        :param y:
        :return:
        """
        return self

    def transform(self, t: Tuple):
        """
        :param t:
        :param path_of_kg:
        :return:
        """

        def create_binary_type_vector(t_types, a_types):
            vector = np.zeros(len(all_types))
            i = [a_types.index(_) for _ in t_types]
            vector[i] = 1
            return vector

        embeddings, data, self.logger = t

        type_info = defaultdict(set)

        # get the types. Mapping from the index of subject to the index of object
        for triple in data.triples:  # literals are removed.
            s, p, o = triple

            if 'rdf-syntax-ns#type' in p:
                type_info[s].add(o)

        # get the index of objects / get type information =>>> s #type o
        all_types = sorted(set.union(*list(type_info.values())))

        # Consider only points with type infos.
        e_w_types = embeddings.loc[list(type_info.keys())]

        self.logger.info('# of entities having type information:{0}'.format(len(e_w_types)))

        # Apply clustering
        clusterer = hdbscan.HDBSCAN().fit(e_w_types)
        e_w_types['labels'] = clusterer.labels_

        clusters = pd.unique(e_w_types.labels)

        sum_purity = 0
        for c in clusters:

            valid_indexes_in_c = e_w_types[e_w_types.labels == c].index.values
            sum_of_cosines = 0
            self.logger.info('##### CLUSTER {0} #####'.format(c))

            for i in valid_indexes_in_c:

                # returns a set of indexes
                types_i = type_info[i]

                vector_type_i = create_binary_type_vector(types_i, all_types)

                for j in valid_indexes_in_c:
                    types_j = type_info[j]
                    vector_type_j = create_binary_type_vector(types_j, all_types)
                    sum_of_cosines += 1 - cosine(vector_type_i, vector_type_j)

            purity = sum_of_cosines / (len(valid_indexes_in_c) ** 2)

            sum_purity += purity

        mean_of_scores = sum_purity / len(clusters)
        self.logger.info('Mean of cluster purity:{0}'.format(mean_of_scores))
