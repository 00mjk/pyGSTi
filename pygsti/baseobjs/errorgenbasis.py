"""
Defines the ElementaryErrorgenBasis class and supporting functionality.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import itertools as _itertools
import collections as _collections

from pygsti.baseobjs import Basis as _Basis
from pygsti.baseobjs.errorgenlabel import GlobalElementaryErrorgenLabel as _GlobalElementaryErrorgenLabel
from pygsti.tools import optools as _ot


class ElementaryErrorgenBasis(object):
    """
    A basis for error-generator space defined by a set of elementary error generators.

    Elements are ordered (have definite indices) and labeled.
    Intersection and union can be performed as a set.
    """

    def label_indices(self, labels):
        """ TODO: docstring """
        return [self.label_index(lbl) for lbl in labels]

    def __len__(self):
        """ Number of elementary errorgen elements in this basis """
        return len(self.labels)


class ExplicitElementaryErrorgenBasis(ElementaryErrorgenBasis):

    def __init__(self, state_space, labels, basis1q=None):
        # TODO: docstring - labels must be of form (sslbls, elementary_errorgen_lbl)
        self._labels = tuple(labels) if not isinstance(labels, tuple) else labels
        self._label_indices = _collections.OrderedDict([(lbl, i) for i, lbl in enumerate(self._labels)])
        self.basis_1q = basis1q if (basis1q is not None) else _Basis.cast('pp', 4)

        self.state_space = state_space
        assert(self.state_space.is_entirely_qubits), "FOGI only works for models containing just qubits (so far)"
        sslbls = self.state_space.tensor_product_block_labels(0)  # all the model's state space labels
        self.sslbls = sslbls  # the "support" of this space - the qubit labels
        self._cached_elements = None

    @property
    def labels(self):
        return self._labels

    @property
    def elemgen_supports_and_matrices(self):
        if self._cached_elements is None:
            self._cached_elements = tuple(
                ((elemgen_label.sslbls, _ot.lindblad_error_generator(
                    elemgen_label.errorgen_type, elemgen_label.basis_element_labels,
                    self.basis_1q, normalize=True, sparse=False, tensorprod_basis=True))
                 for elemgen_label in self.labels))
        return self._cached_elements

    def label_index(self, label):
        """
        TODO: docstring
        """
        return self._label_indices[label]

    #@property
    #def sslbls(self):
    #    """ The support of this errorgen space, e.g., the qubits where its elements may be nontrivial """
    #    return self.sslbls

    def create_subbasis(self, must_overlap_with_these_sslbls):
        """
        Create a sub-basis of this basis by including only the elements
        that overlap the given support (state space labels)
        """
        sub_sslbls = set(must_overlap_with_these_sslbls)

        def overlaps(sslbls):
            ret = len(set(sslbls).intersection(must_overlap_with_these_sslbls)) > 0
            if ret: sub_sslbls.update(sslbls)  # keep track of all overlaps
            return ret

        sub_labels, sub_indices = zip(*[(lbl, i) for i, lbl in enumerate(self._labels)
                                        if overlaps(lbl[0])])

        sub_state_space = self.state_space.create_subspace(sub_sslbls)
        return ExplicitElementaryErrorgenBasis(sub_state_space, sub_labels, self.basis_1q)

    def union(self, other_basis):
        present_labels = self._label_indices.copy()  # an OrderedDict, indices don't matter here
        if isinstance(other_basis, ExplicitElementaryErrorgenBasis):
            present_labels.update(other_basis._label_indices)
        else:

            for other_lbl in other_basis.labels:
                if other_lbl not in present_labels:
                    present_labels[other_lbl] = True

        union_state_space = self.state_space.union(other_basis.state_space)
        return ExplicitElementaryErrorgenBasis(union_state_space, tuple(present_labels.keys()), self.basis_1q)

    def intersection(self, other_basis):
        if isinstance(other_basis, ExplicitElementaryErrorgenBasis):
            common_labels = tuple((lbl for lbl in self.labels if lbl in other_basis._label_indices))
        else:
            other_labels = set(other_basis.labels)
            common_labels = tuple((lbl for lbl in self.labels if lbl in other_labels))

        intersection_state_space = self.state_space.intersection(other_basis.state_space)
        return ExplicitElementaryErrorgenBasis(intersection_state_space, common_labels, self.basis_1q)

    def difference(self, other_basis):
        if isinstance(other_basis, ExplicitElementaryErrorgenBasis):
            remaining_labels = tuple((lbl for lbl in self.labels if lbl not in other_basis._label_indices))
        else:
            other_labels = set(other_basis.labels)
            remaining_labels = tuple((lbl for lbl in self.labels if lbl not in other_labels))

        remaining_state_space = self.state_space  # TODO: see if we can reduce this space based on remaining_labels?
        return ExplicitElementaryErrorgenBasis(remaining_state_space, remaining_labels, self.basis_1q)


class CompleteElementaryErrorgenBasis(ElementaryErrorgenBasis):
    """
    Spanned by the elementary error generators of given type(s) (e.g. "Hamiltonian" and/or "other")
    and with elements corresponding to a `Basis`, usually of Paulis.
    """

    @classmethod
    def _create_diag_labels_for_support(cls, support, type_str, nontrivial_bels):
        weight = len(support)

        def _basis_el_strs(possible_bels, wt):
            for els in _itertools.product(*([possible_bels] * wt)):
                yield ''.join(els)

        return [_GlobalElementaryErrorgenLabel(type_str, (bel,), support)
                for bel in _basis_el_strs(nontrivial_bels, weight)]

    @classmethod
    def _create_all_labels_for_support(cls, support, left_support, type_str, trivial_bel, nontrivial_bels):
        n = len(support)  # == weight
        all_bels = trivial_bel + nontrivial_bels
        left_weight = len(left_support)
        if len(left_weight) < n:  # n1 < n
            factors = [nontrivial_bels if x in left_support else trivial_bel for x in support] \
                + [all_bels if x in left_support else nontrivial_bels for x in support]
            return [_GlobalElementaryErrorgenLabel(type_str, (''.join(beltup[0:n]), ''.join(beltup[n:])), support)
                    for beltup in _itertools.product(*factors)]
            # (factors == left_factors + right_factors above)
        else:  # n1 == n
            ret = []
            for left_beltup in _itertools.product(*([nontrivial_bels] * n)):  # better itertools call here TODO
                left_bel = ''.join(left_beltup)
                right_it = _itertools.product(*([all_bels] * n))  # better itertools call here TODO
                right_it.next()  # advance past first (all I) element - assume trivial el = first!!
                ret.extend([_GlobalElementaryErrorgenLabel(type_str, (left_bel, ''.join(right_beltup)), support)
                            for right_beltup in right_it])
            return ret

    @classmethod
    def _create_ordered_labels(cls, type_str, basis_1q, state_space, mode='diagonal',
                               max_weight=None, must_overlap_with_these_sslbls=None,
                               include_offsets=False):
        offsets = {}
        labels = []
        #labels_by_support = _collections.OrderedDict()
        #all_bels = basis_1q.labels[0:]
        trivial_bel = [basis_1q.labels[0]]
        nontrivial_bels = basis_1q.labels[1:]  # assume first element is identity

        if max_weight is None:
            assert(state_space.is_entirely_qubits), "FOGI only works for models containing just qubits (so far)"
            sslbls = state_space.tensor_product_block_labels(0)  # all the model's state space labels
            max_weight = len(sslbls)

        # Let k be len(nontrivial_bels)
        if mode == "diagonal":
            # --> for each set of n qubit labels, there are k^n Hamiltonian terms with weight n
            for weight in range(1, max_weight + 1):
                for support in _itertools.combinations(sslbls, weight):  # NOTE: combinations *MUST* be deterministic
                    if (must_overlap_with_these_sslbls is not None
                       and len(set(must_overlap_with_these_sslbls).intersection(support)) == 0):
                        continue
                    offsets[support] = len(labels)
                    labels.extend(cls._create_diag_labels_for_support(support, type_str, nontrivial_bels))

        elif mode == "all":
            # --> for each weight n, must compute all *pairs* that have this weight.
            #  This is done via algorithm:
            #    Given n qubit labels (the support, number of labels == weight),
            #    loop over all left-hand weights n1 ranging from 1 to n
            #      loop over all left-supports of size n1 (choose some number of left factors to be nontrivial)
            #        Note: right-side *must* be nontrivial on complement of left support, can can be anything
            #              on factors in the left support (since the left side is nontrivial here) *except*
            #              the right side can't be all the trivial element.
            #        loop over all left-side elements (nNontrivialBELs^n1 of them)
            #          loop over right factors - the number of elements will be:
            #          nNontrivialBELs^(n-n1) * n1QBasisEls^n1 if (n1 < n) else (n1QBasisEls^n - 1)

            for weight in range(1, max_weight + 1):
                for support in _itertools.combinations(sslbls, weight):
                    if (must_overlap_with_these_sslbls is not None
                       and len(must_overlap_with_these_sslbls.intersection(support)) == 0):
                        continue

                    for left_weight in range(1, weight + 1):
                        for left_support in _itertools.combinations(support, left_weight):
                            offsets[(support, left_support)] = len(labels)
                            labels.extend(cls._create_all_labels_for_support(support, left_support, type_str,
                                                                             trivial_bel, nontrivial_bels))
        else:
            raise ValueError("Invalid mode: %s" % str(mode))
        offsets['END'] = len(labels)

        return (labels, offsets) if include_offsets else labels

    @classmethod
    def _create_ordered_label_offsets(cls, type_str, basis_1q, state_space, mode='diagonal',
                                      max_weight=None, must_overlap_with_these_sslbls=None,
                                      return_total_support=False):
        """ same as _create_ordered_labels but doesn't actually create the labels - just counts them to get offsets. """
        offsets = {}
        off = 0  # current number of labels that we would have created
        n1Q_bels = len(basis_1q.labels)
        n1Q_nontrivial_bels = n1Q_bels - 1  # assume first element is identity
        total_support = set()

        if max_weight is None:
            assert(state_space.is_entirely_qubits), "FOGI only works for models containing just qubits (so far)"
            sslbls = state_space.tensor_product_block_labels(0)  # all the model's state space labels
            max_weight = len(sslbls)

        # Let k be len(nontrivial_bels)
        if mode == "diagonal":
            # --> for each set of n qubit labels, there are k^n Hamiltonian terms with weight n
            for weight in range(1, max_weight + 1):
                for support in _itertools.combinations(sslbls, weight):  # NOTE: combinations *MUST* be deterministic
                    if (must_overlap_with_these_sslbls is not None
                       and len(set(must_overlap_with_these_sslbls).intersection(support)) == 0):
                        continue
                    offsets[support] = off
                    off += n1Q_nontrivial_bels**weight
                    total_support.update(support)

        elif mode == "all":
            # --> for each weight n, must compute all *pairs* that have this weight.
            #  This is done via algorithm:
            #    Given n qubit labels (the support, number of labels == weight),
            #    loop over all left-hand weights n1 ranging from 1 to n
            #      loop over all left-supports of size n1 (choose some number of left factors to be nontrivial)
            #        Note: right-side *must* be nontrivial on complement of left support, can can be anything
            #              on factors in the left support (since the left side is nontrivial here) *except*
            #              the right side can't be all the trivial element.
            #        loop over all left-side elements (nNontrivialBELs^n1 of them)
            #          loop over right factors - the number of elements will be:
            #          nNontrivialBELs^(n-n1) * n1QBasisEls^n1 if (n1 < n) else (n1QBasisEls^n - 1)

            for weight in range(1, max_weight + 1):
                for support in _itertools.combinations(sslbls, weight):
                    if (must_overlap_with_these_sslbls is not None
                       and len(must_overlap_with_these_sslbls.intersection(support)) == 0):
                        continue

                    total_support.update(support)
                    for left_weight in range(1, weight + 1):
                        n, n1 = weight, left_weight
                        for left_support in _itertools.combinations(support, left_weight):
                            offsets[(support, left_support)] = off
                            off += (n1Q_nontrivial_bels**(n - n1) * n1Q_bels**n1) if (n1 < n) else (n1Q_bels**n - 1)
        else:
            raise ValueError("Invalid mode: %s" % str(mode))
        offsets['END'] = off

        return (offsets, total_support) if return_total_support else offsets

    def __init__(self, basis_1q, state_space, other_mode, max_ham_weight=None, max_other_weight=None,
                 must_overlap_with_these_sslbls=None):
        self._basis_1q = basis_1q
        self._other_mode = other_mode
        self.state_space = state_space
        self._max_ham_weight = max_ham_weight
        self._max_other_weight = max_other_weight
        self._must_overlap_with_these_sslbls = must_overlap_with_these_sslbls

        assert(self.state_space.is_entirely_qubits), "FOGI only works for models containing just qubits (so far)"

        self._h_offsets, hsup = self._create_ordered_label_offsets('H', self._basis_1q, self.state_space,
                                                                   'diagonal', self._max_ham_weight,
                                                                   self._must_overlap_with_these_sslbls,
                                                                   return_total_support=True)
        self._hs_border = self._h_offsets['END']
        self._s_offsets, ssup = self._create_ordered_label_offsets('S', self._basis_1q, self.state_space,
                                                                   other_mode, self._max_other_weight,
                                                                   self._must_overlap_with_these_sslbls,
                                                                   return_total_support=True)

        #Note: state space can have additional labels that aren't in support
        # (this is, I think, only true when must_overlap_with_these_sslbls != None)
        sslbls = self.state_space.tensor_product_block_labels(0)  # all the model's state space labels
        present_sslbls = hsup.union(ssup)  # set union
        if set(sslbls) == present_sslbls:
            self.sslbls = sslbls  # the "support" of this space - the qubit labels
        elif present_sslbls.issubset(sslbls):
            self.state_space = self.state_space.create_subspace(present_sslbls)
            self.sslbls = present_sslbls
        else:
            # this should never happen - somehow the statespace doesn't have all the labels!
            assert(False), "Logic error! State space doesn't contain all of the present labels!!"

        #FUTURE: cache these for speed?  - but could just create an explicit basis which would be more transparent
        #self._cached_labels = None
        #self._cached_elements = None

        # Notes on ordering of labels:
        # - let there be k nontrivial 1-qubit basis elements (usually k=3)
        # - loop over all sets of qubit labels, increasing in length
        # - for a set of n qubit labels, there are k^n Hamiltonian terms with weight n,
        #    and either k^n "other" terms of weight n or something much more complicated:
        #    all pairs such that 1 or 2 members is nontrivial for each qubit:

        #    e.g. for 1 qubit: [(ntriv,), (ntriv,)] or  (X,X)  Note: can't have an all-triv element (I..I excluded)
        #    e.g. for 2 qubit: [(triv,ntriv), (ntriv,triv)] or   (IX,XI)  -- k * k elements
        #                      [(triv,ntriv), (ntriv,ntriv)] or   (IX,XX) -- k^3 elements
        #                      [(ntriv,triv), (triv,ntriv)] or   (XI,IX)  -- etc...
        #                      [(ntriv,triv), (ntriv,ntriv)] or   (XI,XX)
        #                      [(ntriv,ntriv), (triv,ntriv)] or   (XX,IX)
        #                      [(ntriv,ntriv), (ntriv,triv)] or   (XX,XI)
        #                      [(ntriv,ntriv), (ntriv,ntriv)] or   (XX,XX) -- k^4 elements (up to k^(2n) in general)
        #    e.g. for 3 qubit: (IIX,XXI)  # start with weight-1's on left
        #                      (IIX,XXX)  #   loop over filling in the (at least 1) nontrivial left-index with trival
        #                      (IXI,XIX)  #                                                     & nontrivial on right
        #                      (IXI,XXX)
        #                      ...
        #                      (IXX,XII) # move to weight-2s on left
        #                      (IXX,XXI) #   on right, loop over all possible choices of at least one, an at most m,
        #                      (IXX,XXX) #    nontrivial indices to place within the m nontriv left indices (1 & 2 here)

    def __len__(self):
        """ Number of elementary errorgen elements in this basis """
        return self._h_offsets['END'] + self._s_offsets['END']

    def to_explicit_basis(self):
        return ExplicitElementaryErrorgenBasis(self.state_space, self.labels, self._basis_1q)

    @property
    def labels(self):
        hlabels = self._create_ordered_labels('H', self._basis_1q, self.state_space,
                                              'diagonal', self._max_ham_weight,
                                              self._must_overlap_with_these_sslbls)
        slabels = self._create_ordered_labels('S', self._basis_1q, self.state_space,
                                              self._other_mode, self._max_other_weight,
                                              self._must_overlap_with_these_sslbls)
        return tuple(hlabels + slabels)

    @property
    def elemgen_supports_and_matrices(self):
        return tuple(((elemgen_label.sslbls,
                       _ot.lindblad_error_generator(elemgen_label.errorgen_type, elemgen_label.basis_element_labels,
                                                    self._basis_1q, normalize=True, sparse=False,
                                                    tensorprod_basis=True))
                      for elemgen_label in self.labels))

    def label_index(self, elemgen_label):
        """
        TODO: docstring
        """
        support = elemgen_label.sslbls
        elemgen_type = elemgen_label.errorgen_type
        bels = elemgen_label.basis_element_labels
        trivial_bel = self._basis_1q.labels[0]  # assumes first element is identity
        nontrivial_bels = self._basis_1q.labels[1:]

        if elemgen_type == 'H' or (elemgen_type == 'S' and self._other_mode == 'diagonal'):
            base = self._h_offsets[support] if (elemgen_type == 'H') else (self._hs_border + self._s_offsets[support])
            indices = {lbl: i for i, lbl in enumerate(self._create_diag_labels_for_support(support, elemgen_type,
                                                                                           nontrivial_bels))}
        elif elemgen_type == 'S':
            assert(self._other_mode == 'all'), "Invalid 'other' mode: %s" % str(self._other_mode)
            assert(len(trivial_bel) == 1)  # assumes this is a single character
            nontrivial_inds = [i for i, letter in enumerate(bels[0]) if letter != trivial_bel]
            left_support = tuple([self.sslbls[i] for i in nontrivial_inds])
            base = self._hs_border + self._s_offsets[(support, left_support)]

            indices = {lbl: i for i, lbl in enumerate(self._create_all_labels_for_support(
                support, left_support, 'S', [trivial_bel], nontrivial_bels))}
        else:
            raise ValueError("Invalid label type: %s" % str(elemgen_type))

        return base + indices[elemgen_label]

    #@property
    #def sslbls(self):
    #    """ The support of this errorgen space, e.g., the qubits where its elements may be nontrivial """
    #    return self.sslbls

    def create_subbasis(self, must_overlap_with_these_sslbls, retain_max_weights=True):
        """
        Create a sub-basis of this basis by including only the elements
        that overlap the given support (state space labels)
        """
        #Note: state_space is automatically reduced within __init__ when necessary, e.g., when
        # `must_overlap_with_these_sslbls` is non-None and considerably reduces the basis.
        return CompleteElementaryErrorgenBasis(self._basis_1q, self.state_space, self._other_mode,
                                               self._max_ham_weight if retain_max_weights else None,
                                               self._max_other_weight if retain_max_weights else None,
                                               must_overlap_with_these_sslbls)

    def union(self, other_basis):
        # don't convert this basis to an explicit one unless it's necessary -
        # if `other_basis` is already an explicit basis then let it do the work.
        if isinstance(other_basis, ExplicitElementaryErrorgenBasis):
            return other_basis.union(self)
        else:
            return self.to_explicit_basis().union(other_basis)

    def intersection(self, other_basis):
        if isinstance(other_basis, ExplicitElementaryErrorgenBasis):
            return other_basis.intersection(self)
        else:
            return self.to_explicit_basis().intersection(other_basis)

    def difference(self, other_basis):
        return self.to_explicit_basis().difference(other_basis)


#OLD - maybe not needed?
#class LowWeightElementaryErrorgenBasis(ElementaryErrorgenBasis):
#    """
#    Spanned by the elementary error generators of given type(s) (e.g. "Hamiltonian" and/or "other")
#    and with elements corresponding to a `Basis`, usually of Paulis.
#    """
#
#    def __init__(self, basis_1q, state_space, other_mode, max_ham_weight=None, max_other_weight=None,
#                 must_overlap_with_these_sslbls=None):
#        self._basis_1q = basis_1q
#        self._other_mode = other_mode
#        self.state_space = state_space
#        self._max_ham_weight = max_ham_weight
#        self._max_other_weight = max_other_weight
#        self._must_overlap_with_these_sslbls = must_overlap_with_these_sslbls
#
#        assert(self.state_space.is_entirely_qubits), "FOGI only works for models containing just qubits (so far)"
#        sslbls = self.state_space.tensor_product_block_labels(0)  # all the model's state space labels
#        self.sslbls = sslbls  # the "support" of this space - the qubit labels
#
#        self._cached_label_indices = None
#        self._cached_labels_by_support = None
#        self._cached_elements = None
#
#        #Needed?
#        # self.dim = len(self.labels)  # TODO - update this so we don't always need to build labels
#        # # (this defeats lazy building via property below) - we can just compute this, especially if
#        # # not too fancy
#
#    @property
#    def labels(self):
#        if self._cached_label_indices is None:
#
#            def _basis_el_strs(possible_bels, wt):
#                for els in _itertools.product(*([possible_bels] * wt)):
#                    yield ''.join(els)
#
#            labels = {}
#            all_bels = self.basis_1q.labels[1:]  # assume first element is identity
#            nontrivial_bels = self.basis_1q.labels[1:]  # assume first element is identity
#
#            max_weight = self._max_ham_weight if (self._max_ham_weight is not None) else len(self.sslbls)
#            for weight in range(1, max_weight + 1):
#                for support in _itertools.combinations(self.sslbls, weight):
#                    if (self._must_overlap_with_these_sslbls is not None
#                       and len(self._must_overlap_with_these_sslbls.intersection(support)) == 0):
#                        continue
#                    if support not in labels: labels[support] = []  # always True?
#                    labels[support].extend([('H', bel) for bel in _basis_el_strs(nontrivial_bels, weight)])
#
#            max_weight = self._max_other_weight if (self._max_other_weight is not None) else len(self.sslbls)
#            if self._other_mode != "all":
#                for weight in range(1, max_weight + 1):
#                    for support in _itertools.combinations(self.sslbls, weight):
#                        if (self._must_overlap_with_these_sslbls is not None
#                           and len(self._must_overlap_with_these_sslbls.intersection(support)) == 0):
#                            continue
#                        if support not in labels: labels[support] = []
#                        labels[support].extend([('S', bel) for bel in _basis_el_strs(nontrivial_bels, weight)])
#            else:
#                #This is messy code that relies on basis labels being single characters -- TODO improve(?)
#                idle_char = self.basis_1q.labels[1:]  # assume first element is identity
#                assert(len(idle_char) == 1 and all([len(c) == 1 for c in nontrivial_bels])), \
#                    "All basis el labels must be single chars for other_mode=='all'!"
#                for support in _itertools.combinations(self.sslbls, max_weight):
#                    # Loop over all possible basis elements for this max-weight support, computing the actual support
#                    # of each one individually and appending it to the appropriate list
#                    for bel1 in _basis_el_strs(all_bels, max_weight):
#                        nonidle_indices1 = [i for i in range(max_weight) if bel1[i] != idle_char]
#                        for bel2 in _basis_el_strs(all_bels, max_weight):
#                            nonidle_indices2 = [i for i in range(max_weight) if bel2[i] != idle_char]
#                            nonidle_indices = list(sorted(set(nonidle_indices1) + set(nonidle_indices2)))
#                            bel1 = ''.join([bel1[i] for i in nonidle_indices])  # trim to actual support
#                            bel2 = ''.join([bel2[i] for i in nonidle_indices])  # trim to actual support
#                            actual_support = tuple([support[i] for i in nonidle_indices])
#
#                            if (self._must_overlap_with_these_sslbls is not None
#                               and len(self._must_overlap_with_these_sslbls.intersection(actual_support)) == 0):
#                                continue
#
#                            if actual_support not in labels: labels[actual_support] = []
#                            labels[actual_support].append(('S', bel1, bel2))
#
#            self._cached_labels_by_support = labels
#            self._cached_label_indices = _collections.OrderedDict(((support_lbl, i) for i, support_lbl in enumerate(
#                ((support, lbl) for support, lst in labels.items() for lbl in lst))))
#
#        return tuple(self._cached_label_indices.keys())
#
#    @property
#    def element_supports_and_matrices(self):
#        if self._cached_elements is None:
#            self._cached_elements = tuple(
#                ((support, _ot.lindblad_error_generator(elemgen_label, self.basis_1q, normalize=True, sparse=False))
#                 for support, elemgen_label in self.labels))
#        return self._cached_elements
#
#    def element_index(self, label):
#        """
#        TODO: docstring
#        """
#        if self._cached_label_indices is None:
#            self.labels  # triggers building of labels
#        return self._cached_label_indices[label]
#
#    @property
#    def sslbls(self):
#        """ The support of this errorgen space, e.g., the qubits where its elements may be nontrivial """
#        return self.sslbls
#
#    def create_subbasis(self, must_overlap_with_these_sslbls, retain_max_weights=True):
#        """
#        Create a sub-basis of this basis by including only the elements
#        that overlap the given support (state space labels)
#        """
#        #Note: can we reduce self.state_space?
#        return CompleteErrorgenBasis(self._basis_1q, self.state_space, self._other_mode,
#                                     self._max_ham_weight if retain_max_weights else None,
#                                     self._max_other_weight if retain_max_weights else None,
#                                     self._must_overlap_with_these_sslbls)
