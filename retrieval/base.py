#!/usr/bin/env python3

from sklearn.base import TransformerMixin, BaseEstimator
from sklearn.neighbors import NearestNeighbors
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from abc import abstractmethod
import scipy.sparse as sp
import numpy as np
import gist.rank_metrics as rm
import sys

VALID_METRICS = ["mean_reciprocal_rank", "mean_average_precision",
                 "average_ndcg_at_k"]


def TermMatch(X, q):
    """
    X : ndarray of shape (documents, terms)
    q : ndarray of shape (1, terms)
    >>> X = np.array([[0,0,1], [0,1,0], [0,1,1], [1,0,0], [1,0,1], [1,1,0]])
    >>> TermMatch(X, np.array([[0,0,0]]))
    array([], dtype=int64)
    >>> TermMatch(X, np.array([[0,0,1]]))
    array([0, 2, 4])
    >>> TermMatch(X, np.array([[0,1,0]]))
    array([1, 2, 5])
    >>> TermMatch(X, np.array([[0,1,1]]))
    array([0, 1, 2, 4, 5])
    >>> TermMatch(X, np.array([[1,0,0]]))
    array([3, 4, 5])
    >>> TermMatch(X, np.array([[1,0,1]]))
    array([0, 2, 3, 4, 5])
    >>> TermMatch(X, np.array([[1,1,0]]))
    array([1, 2, 3, 4, 5])
    >>> TermMatch(X, np.array([[1,1,1]]))
    array([0, 1, 2, 3, 4, 5])
    >>> TermMatch(X, np.array([0,1,1]))
    Traceback (most recent call last):
      File "/usr/lib64/python3.5/doctest.py", line 1320, in __run
        compileflags, 1), test.globs)
      File "<doctest __main__.TermMatch[9]>", line 1, in <module>
        TermMatch(np.array([0,1,1]), X)
      File "retrieval.py", line 50, in TermMatch
        indices = np.unique(X.transpose()[q.nonzero()[1], :].nonzero()[1])
    IndexError: tuple index out of range
    """
    # indices = np.unique(X.transpose()[q.nonzero()[1], :].nonzero()[1])
    inverted_index = X.transpose()
    query_terms = q.nonzero()[1]
    matching_terms = inverted_index[query_terms, :]
    matching_doc_indices = np.unique(matching_terms.nonzero()[1])
    return matching_doc_indices


def cosine_similarity(X, query, n_retrieve):
    """
    Computes the `n_retrieve` nearest neighbors using cosine similarity
    Xmatched : The documents that have matching terms (if matching='terms')
    q : the query
    n_retrieve : The number of indices to return.
    >>> X = np.array([[10,1,0], [1,10,0], [0,0,10]])
    >>> cosine_similarity(X, np.array([[0,23,0]]), 2)
    array([1, 0])
    >>> cosine_similarity(X, np.array([[1,0,0]]), 2)
    array([0, 1])
    >>> cosine_similarity(X, np.array([[1,0,10]]), 3)
    array([2, 0, 1])
    """
    nn = NearestNeighbors(metric='cosine', algorithm='brute').fit(X)
    ind = nn.kneighbors(query, n_neighbors=n_retrieve, return_distance=False)
    return ind.ravel()  # we want a plain list of indices


def _checkXy(X, y):
    if y is None:
        return
    if len(X) != len(y):
        raise ValueError("Shapes of X and y do not match.")


def average_ndcg_at_k(rs, k, method=0):
    return np.mean([rm.ndcg_at_k(r, k, method) for r in rs])


class RetrievalModel(BaseEstimator, TransformerMixin):
    """
    >>> docs = ["The quick", "Fox jumps", "over the lazy dog"]
    >>> model = RetrievalModel().fit(docs)
    >>> model.query(["quick"])
    array([[0]])
    >>> model.query(["fox"])
    array([[1]])
    >>> model.query(["dog"])
    array([[2]])
    >>> model.query(["the quick fox jumps over the lazy dog"], k=3)
    array([[2, 0, 1]])
    """
    def __init__(self, vectorizer=TfidfVectorizer(), metric='cosine',
                 algorithm='brute', matching='terms', verbose=0, **kwargs):
        """ initializes vectorizer and passes remaining params down to
        NeighborsBase
        """
        self._cv = CountVectorizer()
        self.vectorizer = vectorizer
        self.matching = TermMatch if matching == 'terms' else matching
        self.verbose = verbose

    def fit(self, X, y=None):
        """ Fit the vectorizer and transform X to setup the index,
        if y is given, copy it and return its corresponding values
        on later queries. Consider y as the documents' ids
        """
        _checkXy(X, y)
        self._X = self.vectorizer.fit_transform(X)
        self._inv_X = self._cv.fit_transform(X)
        if y is None:
            n_docs = self._X.shape[0]
            self._y = np.arange(n_docs)
        else:
            self._y = np.asarray(y)
        return self

    def partial_fit(self, X, y=None):
        """ Add some objects into the index """
        _checkXy(X, y)

        Xnew = self.vectorizer.transform(X)
        self._X = sp.vstack([self._X, Xnew])

        self._inv_X = sp.vstack([self._inv_X, self._cv.transform(X)])

        if y is None:
            # Try to find at least reasonable ids
            next_id = np.amax(self._y) + 1
            new_ids = np.arange(next_id, next_id + Xnew.shape[0])
            self._y = np.hstack([self._y, new_ids])
        else:
            self._y = np.hstack([self._y, np.asarray(y)])

        return self

    def transform(self, X):
        return self.vectorizer.transform(X)

    def inverse_transform(self, X):
        return self.vectorizer.inverse_transform(X)

    def index(self, X, y=None):
        if self._X is None:
            self.fit(X, y)
        else:
            self.partial_fit(X, y)

    def query(self, X, k=1, **kwargs):
        Xquery = self.transform(X)
        results = []
        for q in Xquery:
            # Matching
            if self.matching is not None:
                indices = self.matching(self._X, q)
                Xm, ym = self._X[indices], self._y[indices]
            else:
                Xm, ym = self._X, self._y

            # Similarity
            n_ret = min(Xm.shape[0], k)  # dont retrieve more than available
            ind = cosine_similarity(Xm, q, n_ret)
            labels = np.choose(ind, ym)
            results.append(labels)
        return np.asarray(results)

    def score(self, X, Y, k=20, metrics=VALID_METRICS):
        """
        X: Query strings
        Y: relevancy values of shape (n_queries, n_samples) or [dict]
        k: number of documents to retrieve and consider in metrics
        """
        if hasattr(Y, 'shape'):
            assert Y.shape == (len(X), self._X.shape[0])
        else:
            assert len(Y) == len(X)
        rs = []
        for qid, result in enumerate(self.query(X, k)):
            try:
                r = Y[qid, result]
            except TypeError:
                r = np.array([Y[qid][docid] for docid in result])
            rs.append(r)

        rs = np.asarray(rs)
        values = {}
        if "average_ndcg_at_k" in metrics:
            values["average_ndcg_at_k"] = average_ndcg_at_k(rs, k)
        if "mean_reciprocal_rank" in metrics:
            values["mean_reciprocal_rank"] = rm.mean_reciprocal_rank(rs)
        if "mean_average_precision" in metrics:
            values["mean_average_precision"] = rm.mean_average_precision(rs)

        return values


class RetrievalBase(BaseEstimator):
    """
    Provides:
    _fit_X : the source documents
    _inv_X : the (pseudo-) inverted index
    _y: the document ids
    such that _fit_X[i] ~ _inv_X[i] ~ _y[i] corresponds to each other.
    _matching(Xquery) : returns the matching subset of _fit_X
    For subclassing, the query method should return doc ids which are stored in
    _y.
    >>> retrieval = RetrievalBase()
    >>> retrieval._init_params()
    >>> docs = ["the quick brown fox", "jumps over the lazy dog"]
    >>> _ = retrieval._fit(docs, [0,1])
    >>> retrieval._inv_X.dtype
    dtype('bool')
    >>> retrieval.n_docs
    2
    >>> retrieval._inv_X.shape
    (2, 8)
    >>> retrieval._fit_X.shape
    (2,)
    >>> retrieval._y.shape
    (2,)
    >>> docs, ids = retrieval._matching( "fox" )
    >>> str(docs[0])
    'the quick brown fox'
    >>> ids
    array([0])
    >>> len(retrieval._matching( "brown dog" ))
    2
    """
    @abstractmethod
    def __init__(self, **kwargs):
        pass

    def _init_params(self, matching='term', **kwargs):
        # reasonable defaults for indexing use case
        binary = kwargs.pop('binary', True)
        dtype = kwargs.pop('dtype', np.bool_)
        self._match_fn = TermMatch if matching == 'term' else matching
        self._cv = CountVectorizer(binary=binary, dtype=dtype, **kwargs)

    def _fit(self, X, y=None):
        """
        learn vocab and construct (pseudo-inverted) index
        """
        cv = self._cv
        self._inv_X = cv.fit_transform(X)
        self._fit_X = np.asarray(X)
        n_docs = len(X)
        self._y = np.arange(n_docs) if y is None else np.asarray(y)
        self.n_docs = n_docs
        assert len(self._fit_X) == len(self._y)
        return self

    def _partial_fix(self, X, y=None):
        self._inv_X = sp.vstack([self._inv_X, self._cv.transform(X)])
        self._fit_X = np.hstack([self._fit_X, np.asarray(X)])
        n_new_docs = len(X)
        if y is None:
            y = np.arange(self.n_docs, self.n_docs + n_new_docs)
        else:
            y = np.asarray(y)
        self._y = np.hstack([self._y, y])

        self.n_docs += n_new_docs
        return self

    def _matching(self, query):
        match_fn = self._match_fn
        # _X = self._inv_X if self._inv_X is not None else self._fit_X
        _X = self._inv_X
        q = self._cv.transform(np.asarray([query]))
        if match_fn is not None:
            ind = match_fn(_X, q)
            return self._fit_X[ind], self._y[ind]
        else:
            return self._fit_X, self._y


class RetriEvalMixin():
    @abstractmethod
    def init(self, **kwargs):
        pass

    def score(self, X, Y, k=20, metrics=VALID_METRICS):
        """
        assumes a query(X,q) -> sorted_doc_ids method
        X: Query strings
        Y: relevancy values of shape (n_queries, n_samples) or [dict]
        k: number of documents to retrieve and consider in metrics
        """
        if hasattr(Y, 'shape'):
            assert Y.shape == (len(X), self._X.shape[0])
        else:
            assert len(Y) == len(X)
        rs = []
        for qid, result in enumerate(self.query(X, k)):
            try:
                r = Y[qid, result]
            except TypeError:
                r = np.array([Y[qid][docid] for docid in result])
            rs.append(r)

        rs = np.asarray(rs)
        values = {}
        if "average_ndcg_at_k" in metrics:
            values["average_ndcg_at_k"] = average_ndcg_at_k(rs, k)
        if "mean_reciprocal_rank" in metrics:
            values["mean_reciprocal_rank"] = rm.mean_reciprocal_rank(rs)
        if "mean_average_precision" in metrics:
            values["mean_average_precision"] = rm.mean_average_precision(rs)

        return values


class TfidfRetrieval(RetrievalBase, RetriEvalMixin):
    """
    Class for tfidf based retrieval
    >>> tfidf = TfidfRetrieval(input='content')
    >>> docs = ["The quick", "brown fox", "jumps over", "the lazy dog"]
    >>> _ = tfidf.fit(docs)
    >>> tfidf._fit_X.shape
    (4,)
    >>> values = tfidf.score(["fox","dog"], [[0,1,0,0],[0,0,0,1]], k=20)
    >>> import pprint
    >>> pprint.pprint(values)
    {'average_ndcg_at_k': 1.0,
     'mean_average_precision': 1.0,
     'mean_reciprocal_rank': 1.0}
    """

    def __init__(self, **kwargs):
        self.vectorizer = TfidfVectorizer(**kwargs)
        self._init_params()

    def fit(self, X, y=None):
        self._fit(X, y)
        self.vectorizer.fit(X, y)
        return self

    def partial_fit(self, X, y=None):
        self._partial_fit(X, y)
        return self

    def query(self, queries, k=1):
        for query in queries:
            # matching step
            matched_docs, matched_doc_ids = self._matching(query)
            # calculate elements to retrieve
            n_ret = min(len(matched_docs), k)
            if n_ret < 0:
                yield []
            # model dependent transformation
            Xm = self.vectorizer.transform(matched_docs)
            q = self.vectorizer.transform(query)
            # model dependent nearest neighbor search or scoring or whatever
            nn = NearestNeighbors(metric='cosine', algorithm='brute').fit(Xm)
            # abuse kneighbors in this case
            ind = nn.kneighbors(q,
                                n_neighbors=n_ret,
                                return_distance=False).ravel()
            # dont forget to convert the indices to document ids of matching
            # labels = np.choose(ind, matched_doc_ids)
            labels = matched_doc_ids[ind]
            yield labels


if __name__ == '__main__':
    import doctest
    doctest.testmod()
