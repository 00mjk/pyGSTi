""" Defines objective-function objects """
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import time as _time
import numpy as _np
import itertools as _itertools
import sys as _sys

from .verbosityprinter import VerbosityPrinter as _VerbosityPrinter
from .. import optimize as _opt, tools as _tools
from ..tools import slicetools as _slct, mpitools as _mpit
from . import profiler as _profiler
from .computationcache import ComputationCache as _ComputationCache
from .bulkcircuitlist import BulkCircuitList as _BulkCircuitList
from .resourceallocation import ResourceAllocation as _ResourceAllocation

CHECK = False
CHECK_JACOBIAN = False
FLOATSIZE = 8  # TODO - get bytes-in-float a better way!


def objfn(objfn_cls, model, dataset, circuits=None,
          regularization=None, penalties=None, op_label_aliases=None,
          cache=None, comm=None, mem_limit=None, **addl_args):
    """ TODO: docstring """

    if circuits is None:
        circuits = list(dataset.keys())

    if op_label_aliases:
        circuits = _BulkCircuitList(circuits, op_label_aliases)

    resource_alloc = _ResourceAllocation(comm, mem_limit)
    ofn = objfn_cls(model, dataset, circuits, regularization, penalties, cache,
                    resource_alloc, verbosity=0, *addl_args)
    return ofn

    #def __len__(self):
    #    return len(self.circuits_to_use)


class ObjectiveFunctionBuilder(object):
    @classmethod
    def simple(cls, objective='logl', freq_weighted_chi2=False):
        if objective == "chi2":
            if freq_weighted_chi2:
                builder = FreqWeightedChi2Function.builder(
                    name='fwchi2',
                    description="Freq-weighted sum of Chi^2",
                    regularization={'min_prob_clip_for_weighting': 1e-4,
                                    'radius': 1e-4})
            else:
                builder = Chi2Function.builder(
                    name='chi2',
                    description="Sum of Chi^2",
                    regularization={'min_prob_clip_for_weighting': 1e-4})

        elif objective == "logl":
            builder = PoissonPicDeltaLogLFunction.builder(
                name='dlogl',
                description="2*Delta(log(L))",
                regularization={'min_prob_clip': 1e-4,
                                'radius': 1e-4},
                penalties={'cptp_penalty_factor': 0,
                           'spam_penalty_factor': 0})

        elif objective == "tvd":
            builder = TVDFunction.builder(
                name='tvd',
                description="Total Variational Distance (TVD)")

        else:
            raise ValueError("Invalid objective: %s" % objective)
        assert(isinstance(builder, cls)), "This function should always return an ObjectiveFunctionBuilder!"
        return builder

    def __init__(self, cls_to_build, name=None, description=None, regularization=None, penalties=None, **kwargs):
        self.name = name if (name is not None) else cls_to_build.__name__
        self.description = description if (description is not None) else "objfn"  # "Sum of Chi^2"  OR "2*Delta(log(L))"
        self.cls_to_build = cls_to_build
        self.regularization = regularization
        self.penalties = penalties
        self.additional_args = kwargs

    def build(self, mdl, dataset, circuit_list, resource_alloc=None, cache=None, verbosity=0):
        return self.cls_to_build(mdl=mdl, dataset=dataset, circuit_list=circuit_list,
                                 resource_alloc=resource_alloc, cache=cache, verbosity=verbosity,
                                 regularization=self.regularization, penalties=self.penalties,
                                 name=self.name, description=self.description, **self.additional_args)


class ObjectiveFunction(object):
    """So far, this is just a base class for organizational purposes"""

    def get_chi2k_distributed_qty(self, objective_function_value):
        raise ValueError("This objective function does not have chi2_k distributed values!")


class RawObjectiveFunction(ObjectiveFunction):
    """ A "raw" objective function whose probabilities and counts are given directly """

    def __init__(self, regularization=None, resource_alloc=None, name=None, description=None, verbosity=0):
        """
        TODO: docstring
        """
        resource_alloc = _ResourceAllocation.build_resource_allocation(resource_alloc)
        self.comm = resource_alloc.comm
        self.profiler = resource_alloc.profiler
        self.mem_limit = resource_alloc.mem_limit
        self.distribute_method = resource_alloc.distribute_method

        self.printer = _VerbosityPrinter.build_printer(verbosity, self.comm)
        self.name = name if (name is not None) else self.__class__.__name__
        self.description = description if (description is not None) else "objfn"

        if regularization is None: regularization = {}
        self.set_regularization(**regularization)

    def set_regularization(self):
        pass  # no regularization parameters

    def _intermediates(self, probs, counts, total_counts, freqs):
        """ Intermediate values used by multiple functions (similar to a temporary cache) """
        return ()  # no intermdiate values

    def fn(self, probs, counts, total_counts, freqs):
        return _np.sum(self.terms(probs, counts, total_counts, freqs))

    def jacobian(self, probs, counts, total_counts, freqs):
        return _np.sum(self.dterms(probs, counts, total_counts, freqs), axis=0)

    def hessian(self, probs, counts, total_counts, freqs):
        return _np.sum(self.hterms(probs, counts, total_counts, freqs), axis=0)

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        return self.lsvec(probs, counts, total_counts, freqs, intermediates)**2

    def lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        return _np.sqrt(self.terms(probs, counts, total_counts, freqs, intermediates))

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        return 2 * self.lsvec(probs, counts, total_counts, freqs, intermediates) \
            * self.dlsvec(probs, counts, total_counts, freqs, intermediates)

    def dlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        # lsvec = sqrt(terms)
        # dlsvec = 0.5/lsvec * dterms
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        lsvec = self.lsvec(probs, counts, total_counts, freqs, intermediates)
        lsvec = _np.maximum(lsvec, 1e-100)  # avoids 0/0 elements that should be 0 below
        dterms = self.dterms(probs, counts, total_counts, freqs, intermediates)
        return (0.5 / lsvec) * dterms

    def dlsvec_and_lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        #Similar to above, just return lsvec too
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        lsvec = self.lsvec(probs, counts, total_counts, freqs, intermediates)
        dlsvec = self.dlsvec(probs, counts, total_counts, freqs, intermediates)
        return dlsvec, lsvec

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        # terms = lsvec**2
        # dterms/dp = 2*lsvec*dlsvec/dp
        # d2terms/dp2 = 2*[ (dlsvec/dp)^2 + lsvec*d2lsvec/dp2 ]
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        return 2 * (self.dlsvec(probs, counts, total_counts, freqs, intermediates)**2
                    + self.lsvec(probs, counts, total_counts, freqs, intermediates)
                    * self.hlsvec(probs, counts, total_counts, freqs, intermediates))

    def hlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        # lsvec = sqrt(terms)
        # dlsvec/dp = 0.5 * terms^(-0.5) * dterms/dp
        # d2lsvec/dp2 = -0.25 * terms^(-1.5) * (dterms/dp)^2 + 0.5 * terms^(-0.5) * d2terms_dp2
        #             = 0.5 / sqrt(terms) * (d2terms_dp2 - 0.5 * (dterms/dp)^2 / terms)
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        terms = self.terms(probs, counts, total_counts, freqs, intermediates)
        dterms = self.dterms(probs, counts, total_counts, freqs, intermediates)
        hterms = self.hterms(probs, counts, total_counts, freqs, intermediates)
        return 0.5 / _np.sqrt(terms) * (hterms - 0.5 * dterms**2 / terms)

    #Required zero-term methods for omitted probs support in model-based objective functions
    def zero_freq_terms(self, total_counts, probs):
        raise NotImplementedError("Derived classes must implement this!")

    def zero_freq_dterms(self, total_counts, probs):
        raise NotImplementedError("Derived classes must implement this!")

    def zero_freq_hterms(self, total_counts, probs):
        raise NotImplementedError("Derived classes must implement this!")


class MDSObjectiveFunction(ObjectiveFunction):
    """ An objective function whose probabilities and counts are given by a Model and DataSet, respectively """

    def __init__(self, raw_objfn, mdl, dataset, circuit_list, cache=None, enable_hessian=False):
        """
        TODO: docstring - note: 'cache' is for repeated calls with same mdl, circuit_list,
        and dataset (but different derived objective fn class).  Note: circuit_list can be
        either a normal list of Circuits or a BulkCircuitList object (or None)
        """
        self.raw_objfn = raw_objfn
        self.dataset = dataset
        self.mdl = mdl
        self.nparams = mdl.num_params()
        self.opBasis = mdl.basis
        self.enable_hessian = enable_hessian
        self.gthrMem = None  # set below

        self.time_dependent = False
        self.check = CHECK
        self.check_jacobian = CHECK_JACOBIAN

        circuit_list = circuit_list if (circuit_list is not None) else list(dataset.keys())
        bulk_circuit_list = circuit_list if isinstance(
            circuit_list, _BulkCircuitList) else _BulkCircuitList(circuit_list)
        self.circuits_to_use = bulk_circuit_list[:]
        self.circuit_weights = bulk_circuit_list.circuit_weights
        self.ds_circuits_to_use = _tools.apply_aliases_to_circuit_list(self.circuits_to_use,
                                                                       bulk_circuit_list.op_label_aliases)

        # Memory check
        persistent_mem = self.get_persistent_memory_estimate()
        in_gb = 1.0 / 1024.0**3  # in gigabytes
        if self.raw_objfn.mem_limit:
            in_gb = 1.0 / 1024.0**3  # in gigabytes
            if self.raw_objfn.mem_limit < persistent_mem:
                raise MemoryError("Memory limit ({} GB) is < memory required to hold final results "
                                  "({} GB)".format(self.raw_objfn.mem_limit * in_gb, persistent_mem * in_gb))

            cur_mem = _profiler._get_max_mem_usage(self.raw_objfn.comm)  # is this what we want??
            self.gthrMem = int(0.1 * (self.raw_objfn.mem_limit - persistent_mem))
            evt_mlim = self.raw_objfn.mem_limit - persistent_mem - self.gthrMem - cur_mem
            self.raw_objfn.printer.log("Memory limit = %.2fGB" % (self.raw_objfn.mem_limit * in_gb))
            self.raw_objfn.printer.log("Cur, Persist, Gather = %.2f, %.2f, %.2f GB" %
                                       (cur_mem * in_gb, persistent_mem * in_gb, self.gthrMem * in_gb))
            assert(evt_mlim > 0), 'Not enough memory, exiting..'
        else:
            evt_mlim = None

        self.cache = cache if (cache is not None) else _ComputationCache()
        if not self.cache.has_evaltree():
            subcalls = self.get_evaltree_subcalls()
            evt_resource_alloc = _ResourceAllocation(self.raw_objfn.comm, evt_mlim,
                                                     self.raw_objfn.profiler, self.raw_objfn.distribute_method)
            self.cache.add_evaltree(self.mdl, self.dataset, self.circuits_to_use, evt_resource_alloc,
                                    subcalls, self.raw_objfn.printer - 1)

        self.eval_tree = self.cache.eval_tree
        self.lookup = self.cache.lookup
        self.outcomes_lookup = self.cache.outcomes_lookup
        self.wrt_blk_size = self.cache.wrt_blk_size
        self.wrt_blk_size2 = self.cache.wrt_blk_size2

        self.nelements = self.eval_tree.num_final_elements()  # shorthand for combined spam+circuit dimension
        self.firsts = None  # no omitted probs by default

    @property
    def name(self):
        return self.raw_objfn.name

    @property
    def description(self):
        return self.raw_objfn.description

    def get_chi2k_distributed_qty(self, objective_function_value):
        return self.raw_objfn.get_chi2k_distributed_qty(objective_function_value)

    def lsvec(self, paramvec=None, oob_check=False):
        raise NotImplementedError("Derived classes should implement this!")

    def dlsvec(self, paramvec=None):
        raise NotImplementedError("Derived classes should implement this!")

    def terms(self, paramvec=None):
        return self.lsvec(paramvec)**2

    def dterms(self, paramvec=None):
        lsvec = self.lsvec(paramvec)  # least-squares objective fn: v is a vector s.t. obj_fn = ||v||^2 (L2 norm)
        dlsvec = self.dlsvec(paramvec)  # jacobian of dim N x M where N = len(v) and M = len(pv)
        assert(dlsvec.shape == (len(lsvec), len(paramvec))), "dlsvec returned a Jacobian with the wrong shape!"
        return 2.0 * lsvec[:, None] * dlsvec  # terms = lsvec**2, so dterms = 2*lsvec*dlsvec

    def percircuit(self, paramvec=None):
        terms = self.terms(paramvec)

        #Aggregate over outcomes:
        # obj_per_el[iElement] contains contributions per element - now aggregate over outcomes
        # percircuit[iCircuit] will contain contributions for each original circuit (aggregated over outcomes)
        num_circuits = len(self.circuits_to_use)
        percircuit = _np.empty(num_circuits, 'd')
        for i in range(num_circuits):
            percircuit[i] = _np.sum(terms[self.lookup[i]], axis=0)
        return percircuit

    def dpercircuit(self, paramvec=None):
        dterms = self.dterms(paramvec)

        #Aggregate over outcomes:
        # obj_per_el[iElement] contains contributions per element - now aggregate over outcomes
        # percircuit[iCircuit] will contain contributions for each original circuit (aggregated over outcomes)
        num_circuits = len(self.circuits_to_use)
        dpercircuit = _np.empty((num_circuits, self.nparams), 'd')
        for i in range(num_circuits):
            dpercircuit[i] = _np.sum(dterms[self.lookup[i]], axis=0)
        return dpercircuit

    def fn(self, paramvec=None):
        return _np.sum(self.terms(paramvec))

    def jacobian(self, paramvec=None):
        return _np.sum(self.dterms(paramvec), axis=0)

    def hessian(self, paramvec=None):
        raise NotImplementedError("Derived classes should implement this!")

    def approximate_hessian(self, paramvec=None):
        raise NotImplementedError("Derived classes should implement this!")

    def get_persistent_memory_estimate(self, num_elements=None):
        #  Estimate & check persistent memory (from allocs within objective function)
        if num_elements is None:
            nout = int(round(_np.sqrt(self.mdl.dim)))  # estimate of avg number of outcomes per string
            nc = len(self.circuits_to_use)
            ne = nc * nout  # estimate of the number of elements (e.g. probabilities, # LS terms, etc) to compute
        else:
            ne = num_elements
        np = self.mdl.num_params()

        # "persistent" memory is that used to store the final results.
        obj_fn_mem = FLOATSIZE * ne
        jac_mem = FLOATSIZE * ne * np
        hess_mem = FLOATSIZE * ne * np**2
        persistent_mem = 4 * obj_fn_mem + jac_mem  # 4 different objective-function sized arrays, 1 jacobian array?
        if any([nm == "bulk_fill_hprobs" for nm in self.get_evaltree_subcalls()]):
            persistent_mem += hess_mem  # we need room for the hessian too!
        # TODO: what about "bulk_hprobs_by_block"?

        return persistent_mem

    def get_evaltree_subcalls(self):
        calls = ["bulk_fill_probs", "bulk_fill_dprobs"]
        if self.enable_hessian: calls.append("bulk_fill_hprobs")
        return calls

    def get_num_data_params(self):
        return self.dataset.get_degrees_of_freedom(
            self.ds_circuits_to_use, aggregate_times=not self.time_dependent)

    def precompute_omitted_freqs(self):
        #Detect omitted frequences (assumed to be 0) so we can compute objective fn correctly
        self.firsts = []; self.indicesOfCircuitsWithOmittedData = []
        for i, c in enumerate(self.circuits_to_use):
            lklen = _slct.length(self.lookup[i])
            if 0 < lklen < self.mdl.get_num_outcomes(c):
                self.firsts.append(_slct.as_array(self.lookup[i])[0])
                self.indicesOfCircuitsWithOmittedData.append(i)
        if len(self.firsts) > 0:
            self.firsts = _np.array(self.firsts, 'i')
            self.indicesOfCircuitsWithOmittedData = _np.array(self.indicesOfCircuitsWithOmittedData, 'i')
            self.dprobs_omitted_rowsum = _np.empty((len(self.firsts), self.nparams), 'd')
            self.raw_objfn.printer.log("SPARSE DATA: %d of %d rows have sparse data" %
                                       (len(self.firsts), len(self.circuits_to_use)))
        else:
            self.firsts = None  # no omitted probs

    def compute_count_vectors(self):
        if not self.cache.has_count_vectors():
            self.cache.add_count_vectors(self.dataset, self.circuits_to_use,
                                         self.ds_circuits_to_use, self.circuit_weights)
        return self.cache.counts, self.cache.total_counts

    def _construct_hessian(self, counts_all, total_counts_all, prob_clip_interval):
        """
        Framework for constructing a hessian matrix row by row using a derived
        class's `_hessian_from_hprobs` method.  This function expects that this
        objective function has been setup for hessian computation, and it's evaltree
        may be split in order to facilitate this.
        """
        #Note - we could in the future use comm to distribute over
        # subtrees here.  We currently don't because we parallelize
        # over columns and it seems that in almost all cases of
        # interest there will be more hessian columns than processors,
        # so adding the additional ability to parallelize over
        # subtrees would just add unnecessary complication.

        #get distribution across subtrees (groups if needed)
        subtrees = self.eval_tree.get_sub_trees()
        my_subtree_indices, subtree_owners, my_subcomm = self.eval_tree.distribute(self.raw_objfn.comm)

        nparams = self.mdl.num_params()
        blk_size1, blk_size2 = self.wrt_blk_size, self.wrt_blk_size2
        row_parts = int(round(nparams / blk_size1)) if (blk_size1 is not None) else 1
        col_parts = int(round(nparams / blk_size2)) if (blk_size2 is not None) else 1

        #  Allocate memory (alloc max required & take views)
        max_nelements = max([subtrees[i].num_final_elements() for i in my_subtree_indices])
        probs_mem = _np.empty(max_nelements, 'd')

        #  Allocate persistent memory
        final_hessian = _np.zeros((nparams, nparams), 'd')

        tm = _time.time()

        #Loop over subtrees
        for subtree_index in my_subtree_indices:
            eval_subtree = subtrees[subtree_index]
            sub_nelements = eval_subtree.num_final_elements()

            if eval_subtree.myFinalElsToParentFinalElsMap is not None:
                #Then `eval_subtree` is a nontrivial sub-tree and its .spamtuple_indices
                # will index the *parent's* final index array space, which we
                # usually want but NOT here, where we fill arrays just big
                # enough for each subtree separately - so re-init spamtuple_indices
                eval_subtree = eval_subtree.copy()
                eval_subtree.recompute_spamtuple_indices(bLocal=True)

            # Create views into pre-allocated memory
            probs = probs_mem[0:sub_nelements]

            # Take portions of count arrays for this subtree
            counts = counts_all[eval_subtree.final_element_indices(self.eval_tree)]
            total_counts = total_counts_all[eval_subtree.final_element_indices(self.eval_tree)]
            freqs = counts / total_counts
            assert(len(counts) == len(probs))

            #compute probs separately
            self.mdl.bulk_fill_probs(probs, eval_subtree,
                                     clip_to=prob_clip_interval, check=self.check,
                                     comm=my_subcomm)

            num_cols = self.mdl.num_params()
            blocks1 = _mpit.slice_up_range(num_cols, row_parts)
            blocks2 = _mpit.slice_up_range(num_cols, col_parts)
            slicetup_list_all = list(_itertools.product(blocks1, blocks2))
            #cull out lower triangle blocks, which have no overlap with
            # the upper triangle of the hessian
            slicetup_list = [(slc1, slc2) for slc1, slc2 in slicetup_list_all
                             if slc1.start <= slc2.stop]

            loc_iblks, blk_owners, blk_comm = \
                _mpit.distribute_indices(list(range(len(slicetup_list))), my_subcomm)
            my_slicetup_list = [slicetup_list[i] for i in loc_iblks]

            subtree_hessian = _np.zeros((nparams, nparams), 'd')

            k, kmax = 0, len(my_slicetup_list)
            for (slice1, slice2, hprobs, dprobs12) in self.mdl.bulk_hprobs_by_block(
                    eval_subtree, my_slicetup_list, True, blk_comm):
                rank = self.raw_objfn.comm.Get_rank() if (self.raw_objfn.comm is not None) else 0

                if self.raw_objfn.printer.verbosity > 3 or (self.raw_objfn.printer.verbosity == 3 and rank == 0):
                    isub = my_subtree_indices.index(subtree_index)
                    print("rank %d: %gs: block %d/%d, sub-tree %d/%d, sub-tree-len = %d"
                          % (rank, _time.time() - tm, k, kmax, isub,
                             len(my_subtree_indices), len(eval_subtree)))
                    _sys.stdout.flush(); k += 1

                subtree_hessian[slice1, slice2] = \
                    self._hessian_from_block(hprobs, dprobs12, probs, counts,
                                             total_counts, freqs)
                #NOTE: _hessian_from_hprobs MAY modify hprobs and dprobs12

            #Gather columns from different procs and add to running final hessian
            #_mpit.gather_slices_by_owner(slicesIOwn, subtree_hessian,[], (0,1), mySubComm)
            _mpit.gather_slices(slicetup_list, blk_owners, subtree_hessian, [], (0, 1), my_subcomm)
            final_hessian += subtree_hessian

        #gather (add together) final_hessians from different processors
        if self.raw_objfn.comm is not None and len(set(subtree_owners.values())) > 1:
            if self.raw_objfn.comm.Get_rank() not in subtree_owners.values():
                # this proc is not the "owner" of its subtrees and should not send a contribution to the sum
                final_hessian[:, :] = 0.0  # zero out hessian so it won't contribute
            final_hessian = self.raw_objfn.comm.allreduce(final_hessian)

        #copy upper triangle to lower triangle (we only compute upper)
        for i in range(final_hessian.shape[0]):
            for j in range(i + 1, final_hessian.shape[1]):
                final_hessian[j, i] = final_hessian[i, j]

        return final_hessian  # (N,N)

    def _hessian_from_block(self, hprobs, dprobs12, probs, counts, total_counts, freqs):
        raise NotImplementedError("Derived classes should implement this!")


#NOTE on chi^2 expressions:
#in general case:   chi^2 = sum (p_i-f_i)^2/p_i  (for i summed over outcomes)
#in 2-outcome case: chi^2 = (p+ - f+)^2/p+ + (p- - f-)^2/p-
#                         = (p - f)^2/p + (1-p - (1-f))^2/(1-p)
#                         = (p - f)^2 * (1/p + 1/(1-p))
#                         = (p - f)^2 * ( ((1-p) + p)/(p*(1-p)) )
#                         = 1/(p*(1-p)) * (p - f)^2

class RawChi2Function(RawObjectiveFunction):
    def __init__(self, regularization=None, resource_alloc=None, name="chi2", description="Sum of Chi^2", verbosity=0):
        super().__init__(regularization, resource_alloc, name, description, verbosity)

    def get_chi2k_distributed_qty(self, objective_function_value):
        return objective_function_value

    def set_regularization(self, min_prob_clip_for_weighting=1e-4):
        self.min_prob_clip_for_weighting = min_prob_clip_for_weighting

    def lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        return (probs - freqs) * self.get_weights(probs, freqs, total_counts)  # Note: ok if this is negative

    def dlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        weights = self.get_weights(probs, freqs, total_counts)
        return weights + (probs - freqs) * self.get_dweights(probs, freqs, weights)

    def hlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        # lsvec = (p-f)*sqrt(N/cp) = (p-f)*w
        # dlsvec/dp = w + (p-f)*dw/dp
        # d2lsvec/dp2 = dw/dp + (p-f)*d2w/dp2
        weights = self.get_weights(probs, freqs, total_counts)
        return self.get_dweights(probs, freqs, weights) + (probs - freqs) * self.get_hweights(probs, freqs, weights)

    def hterms_alt(self, probs, counts, total_counts, freqs, intermediates=None):
        """ Unnecessary - should be the same as hterms, and maybe faster? """
        # v = N * (p-f)**2 / p  => dv/dp = 2N * (p-f)/p - N * (p-f)**2 / p**2 = 2N * t - N * t**2
        # => d2v/dp2 = 2N*dt - 2N*t*dt = 2N(1-t)*dt
        cprobs = _np.clip(probs, self.min_prob_clip_for_weighting, None)
        iclip = (cprobs == self.min_prob_clip_for_weighting)
        t = ((probs - freqs) / cprobs)  # should think of as (p-f)/p
        dtdp = (1.0 - t) / cprobs  # 1/p - (p-f)/p**2 => 1/cp - (p-f)/cp**2 = (1-t)/cp
        d2v_dp2 = 2 * total_counts * (1.0 - t) * dtdp
        d2v_dp2[iclip] = 2 * total_counts[iclip] / self.min_prob_clip_for_weighting
        # with cp constant v = N*(p-f)**2/cp => dv/dp = 2N*(p-f)/cp => d2v/dp2 = 2N/cp
        return d2v_dp2

    #Required zero-term methods for omitted probs support in model-based objective functions
    def zero_freq_terms(self, total_counts, probs):
        clipped_probs = _np.clip(probs, self.min_prob_clip_for_weighting, None)
        return total_counts * probs**2 / clipped_probs

    def zero_freq_dterms(self, total_counts, probs):
        clipped_probs = _np.clip(probs, self.min_prob_clip_for_weighting, None)
        return _np.where(probs == clipped_probs, total_counts, 2 * total_counts * probs / clipped_probs)

    def zero_freq_hterms(self, total_counts, probs):
        clipped_probs = _np.clip(probs, self.min_prob_clip_for_weighting, None)
        return _np.where(probs == clipped_probs, 0.0, 2 * total_counts / clipped_probs)

    #Support functions
    def get_weights(self, p, f, total_counts):
        cp = _np.clip(p, self.min_prob_clip_for_weighting, None)
        return _np.sqrt(total_counts / cp)  # nSpamLabels x nCircuits array (K x M)

    def get_dweights(self, p, f, wts):  # derivative of weights w.r.t. p
        cp = _np.clip(p, self.min_prob_clip_for_weighting, None)
        dw = -0.5 * wts / cp   # nSpamLabels x nCircuits array (K x M)
        dw[p < self.min_prob_clip_for_weighting] = 0.0
        return dw

    def get_hweights(self, p, f, wts):  # 2nd derivative of weights w.r.t. p
        # wts = sqrt(N/cp), dwts = (-1/2) sqrt(N) *cp^(-3/2), hwts = (3/4) sqrt(N) cp^(-5/2)
        cp = _np.clip(p, self.min_prob_clip_for_weighting, None)
        hw = 0.75 * wts / cp**2   # nSpamLabels x nCircuits array (K x M)
        hw[p < self.min_prob_clip_for_weighting] = 0.0
        return hw


class RawChiAlphaFunction(RawObjectiveFunction):
    def __init__(self, regularization=None, resource_alloc=None, name="chialpha", description="Sum of ChiAlpha",
                 verbosity=0, alpha=1):
        super().__init__(regularization, resource_alloc, name, description, verbosity)
        self.alpha = alpha

    def get_chi2k_distributed_qty(self, objective_function_value):
        return objective_function_value

    def set_regularization(self, pfratio_stitchpt=0.01, pfratio_derivpt=0.01, radius=None):
        self.x0 = pfratio_stitchpt
        self.x1 = pfratio_derivpt

        if radius is None:
            #Infer the curvature of the regularized zero-f-term functions from
            # the largest curvature we use at the stitch-points of nonzero-f terms.
            self.radius = None
            self.zero_freq_terms = self._zero_freq_terms_relaxed
            self.zero_freq_dterms = self._zero_freq_dterms_relaxed
            self.zero_freq_hterms = None  # no hessian support
        else:
            #Use radius to specify the curvature/"roundness" of f == 0 terms,
            # though this uses a more aggressive p^3 function to penalize negative probs.
            self.radius = radius
            self.zero_freq_terms = self._zero_freq_terms_harsh
            self.zero_freq_dterms = self._zero_freq_dterms_harsh
            self.zero_freq_hterms = None  # no hessian support

    def _intermediates(self, probs, counts, total_counts, freqs):
        """ Intermediate values used by both terms(...) and dterms(...) """
        freqs_nozeros = _np.where(counts == 0, 1.0, freqs)
        x = probs / freqs_nozeros
        itaylor = x < self.x0  # indices where we patch objective function with taylor series
        c0 = 1. - 1. / (self.x1**(1 + self.alpha))
        c1 = 0.5 * (1. + self.alpha) / self.x1**(2 + self.alpha)
        return x, itaylor, c0, c1

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        x0 = self.x0
        x, itaylor, c0, c1 = intermediates
        xt = x.copy(); xt[itaylor] = x0  # so we evaluate expression below at x0 (first taylor term) at itaylor indices
        terms = counts * (xt + 1.0 / (self.alpha * xt**self.alpha) - (1.0 + 1.0 / self.alpha))
        terms = _np.where(itaylor, terms + c0 * counts * (x - x0) + c1 * counts * (x - x0)**2, terms)
        terms = _np.where(counts == 0, self.zero_freq_terms(total_counts, probs), terms)

        #DEBUG TODO REMOVE
        #if debug and (self.comm is None or self.comm.Get_rank() == 0):
        #    print("ALPHA OBJECTIVE: ", c0, S2)
        #    print(" KM=",len(x), " nTaylored=",_np.count_nonzero(itaylor), " nZero=",_np.count_nonzero(self.counts==0))
        #    print(" xrange = ",_np.min(x),_np.max(x))
        #    print(" vrange = ",_np.min(terms),_np.max(terms))
        #    print(" |v|^2 = ",_np.sum(terms))
        #    print(" |v(normal)|^2 = ",_np.sum(terms[x >= x0]))
        #    print(" |v(taylor)|^2 = ",_np.sum(terms[x < x0]))
        #    imax = _np.argmax(terms)
        #    print(" MAX: v=",terms[imax]," x=",x[imax]," p=",self.probs[imax]," f=",self.freqs[imax])
        return terms

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        x0 = self.x0
        x, itaylor, c0, c1 = intermediates
        dterms = total_counts * (1 - 1. / x**(1. + self.alpha))
        dterms_taylor = total_counts * (c0 + 2 * c1 * (x - x0))
        dterms[itaylor] = dterms_taylor[itaylor]
        dterms = _np.where(counts == 0, self.zero_freq_dterms(total_counts, probs), dterms)
        return dterms

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        raise NotImplementedError("Hessian not implemented for ChiAlpha function yet")

    def hlsvec(self, probs, counts, total_counts, freqs):
        raise NotImplementedError("Hessian not implemented for ChiAlpha function yet")

    #Required zero-term methods for omitted probs support in model-based objective functions
    def _zero_freq_terms_harsh(self, total_counts, probs):
        a = self.a
        return total_counts * _np.where(probs >= a, probs,
                                        (-1.0 / (3 * a**2)) * probs**3 + probs**2 / a + a / 3.0)

    def _zero_freq_dterms_harsh(self, total_counts, probs):
        a = self.a
        return total_counts * _np.where(probs >= a, 1.0, (-1.0 / a**2) * probs**2 + 2 * probs / a)

    def _zero_freq_terms_relaxed(self, total_counts, probs):
        c1 = (0.5 / self.fmin) * (1. + self.alpha) / (self.x1**(2 + self.alpha))
        p0 = 1.0 / c1
        return total_counts * _np.where(probs > p0, probs, c1 * probs**2)

    def _zero_freq_dterms_relaxed(self, total_counts, probs):
        c1 = (0.5 / self.fmin) * (1. + self.alpha) / (self.x1**(2 + self.alpha))
        p0 = 1.0 / c1
        return total_counts * _np.where(probs > p0, 1.0, 2 * c1 * probs)


class RawFreqWeightedChi2Function(RawChi2Function):

    def __init__(self, regularization=None, resource_alloc=None, name="fwchi2",
                 description="Sum of freq-weighted Chi^2", verbosity=0):
        super().__init__(regularization, resource_alloc, name, description, verbosity)

    def get_chi2k_distributed_qty(self, objective_function_value):
        return objective_function_value  # default is to assume the value *is* chi2_k distributed

    def set_regularization(self, min_prob_clip_for_weighting=1e-4, radius=1e-4):
        super().set_regularization(min_prob_clip_for_weighting)
        self.radius = radius

    def get_weights(self, p, f, total_counts):
        #Note: this could be computed once and cached?
        return _np.sqrt(total_counts / _np.clip(f, 1e-7, None))

    def get_dweights(self, p, f, wts):
        return _np.zeros(len(p), 'd')

    def get_hweights(self, p, f, wts):
        return _np.zeros(len(p), 'd')

    def zero_freq_terms(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, probs,
                                        (-1.0 / (3 * a**2)) * probs**3 + probs**2 / a + a / 3.0)

    def zero_freq_dterms(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, 1.0,
                                        (-1.0 / a**2) * probs**2 + 2 * probs / a)

    def zero_freq_hterms(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, 0.0,
                                        (-2.0 / a**2) * probs + 2 / a)


# The log(Likelihood) within the Poisson picture is:                                                                                                    # noqa
#                                                                                                                                                       # noqa
# L = prod_{i,sl} lambda_{i,sl}^N_{i,sl} e^{-lambda_{i,sl}} / N_{i,sl}!                                                                                 # noqa
#                                                                                                                                                       # noqa
# Where lamba_{i,sl} := p_{i,sl}*N[i] is a rate, i indexes the operation sequence,                                                                      # noqa
#  and sl indexes the spam label.  N[i] is the total counts for the i-th circuit, and                                                                   # noqa
#  so sum_{sl} N_{i,sl} == N[i]. We can ignore the p-independent N_j! and take the log:                                                                 # noqa
#                                                                                                                                                       # noqa
# log L = sum_{i,sl} N_{i,sl} log(N[i]*p_{i,sl}) - N[i]*p_{i,sl}                                                                                        # noqa
#       = sum_{i,sl} N_{i,sl} log(p_{i,sl}) - N[i]*p_{i,sl}   (where we ignore the p-independent log(N[i]) terms)                                       # noqa
#                                                                                                                                                       # noqa
# The objective function computes the negative log(Likelihood) as a vector of leastsq                                                                   # noqa
#  terms, where each term == sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} )                                                                        # noqa
#                                                                                                                                                       # noqa
# See LikelihoodFunctions.py for details on patching                                                                                                    # noqa
# The log(Likelihood) within the standard picture is:
#
# L = prod_{i,sl} p_{i,sl}^N_{i,sl}
#
# Where i indexes the operation sequence, and sl indexes the spam label.
#  N[i] is the total counts for the i-th circuit, and
#  so sum_{sl} N_{i,sl} == N[i]. We take the log:
#
# log L = sum_{i,sl} N_{i,sl} log(p_{i,sl})
#
# The objective function computes the negative log(Likelihood) as a vector of leastsq
#  terms, where each term == sqrt( N_{i,sl} * -log(p_{i,sl}) )
#
# See LikelihoodFunction.py for details on patching
class RawPoissonPicDeltaLogLFunction(RawObjectiveFunction):
    def __init__(self, regularization=None,
                 resource_alloc=None, name='dlogl', description="2*Delta(log(L))", verbosity=0):
        super().__init__(regularization, resource_alloc, name, description, verbosity)

    def get_chi2k_distributed_qty(self, objective_function_value):
        return 2 * objective_function_value  # 2 * deltaLogL is what is chi2_k distributed

    def set_regularization(self, min_prob_clip=1e-4, pfratio_stitchpt=None, pfratio_derivpt=None,
                           radius=1e-4, fmin=None):
        if min_prob_clip is not None:
            assert(pfratio_stitchpt is None and pfratio_derivpt is None), \
                "Cannot specify pfratio and min_prob_clip arguments as non-None!"
            self.min_p = min_prob_clip
            self.regtype = "minp"
        else:
            assert(min_prob_clip is None), "Cannot specify pfratio and min_prob_clip arguments as non-None!"
            self.x0 = pfratio_stitchpt
            self.x1 = pfratio_derivpt
            self.regtype = "pfratio"

        if radius is None:
            #Infer the curvature of the regularized zero-f-term functions from
            # the largest curvature we use at the stitch-points of nonzero-f terms.
            assert(self.regtype == 'pfratio'), "Must specify `radius` when %s regularization type" % self.regtype
            assert(fmin is not None), "Must specify 'fmin' when radius is None (should be smalled allowed frequency)."
            self.radius = None
            self.zero_freq_terms = self._zero_freq_terms_relaxed
            self.zero_freq_dterms = self._zero_freq_dterms_relaxed
            self.zero_freq_hterms = self._zero_freq_hterms_relaxed
            self.fmin = fmin  # = max(1e-7, _np.min(freqs_nozeros))  # lowest non-zero frequency
        else:
            #Use radius to specify the curvature/"roundness" of f == 0 terms,
            # though this uses a more aggressive p^3 function to penalize negative probs.
            assert(fmin is None), "Cannot specify 'fmin' when radius is specified."
            self.radius = radius
            self.zero_freq_terms = self._zero_freq_terms_harsh
            self.zero_freq_dterms = self._zero_freq_dterms_harsh
            self.zero_freq_hterms = self._zero_freq_hterms_harsh
            self.fmin = None

    def _intermediates(self, probs, counts, total_counts, freqs):
        """ Intermediate values used by both terms(...) and dterms(...) """
        # Quantities depending on data only (not probs): could be computed once and
        # passed in as arguments to this (and other) functions?
        freqs_nozeros = _np.where(counts == 0, 1.0, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x1 = self.x1
            x = probs / freqs_nozeros  # objective is -Nf*(log(x) + 1 - x)
            pos_x = _np.where(x < x0, x0, x)
            c0 = counts * (1 - 1 / x1)  # deriv wrt x at x == x1 (=min_p)
            c1 = 0.5 * counts / (x1**2)  # 0.5 * 2nd deriv at x1

            #DEBUG TODO REMOVE
            #if self.comm.Get_rank() == 0 and debug:
            #    print(">>>> DEBUG ----------------------------------")
            #    print("x range = ",_np.min(x), _np.max(x))
            #    print("p range = ",_np.min(self.probs), _np.max(self.probs))
            #    #print("f range = ",_np.min(self.freqs), _np.max(self.freqs))
            #    #print("fnz range = ",_np.min(self.freqs_nozeros), _np.max(self.freqs_nozeros))
            #    #print("TVD = ", _np.sum(_np.abs(self.probs - self.freqs)))
            #    print(" KM=",len(x), " nTaylored=",_np.count_nonzero(x < x0),
            #          " nZero=",_np.count_nonzero(self.minusCntVecMx==0))
            #    #for i,el in enumerate(x):
            #    #    if el < 0.1 or el > 10.0:
            #    #        print("-> x=%g  p=%g  f=%g  fnz=%g" % (el, self.probs[i],
            #                   self.freqs[i], self.freqs_nozeros[i]))
            #    print("<<<<< DEBUG ----------------------------------")

            #pos_x = _np.where(x > 1 / x0, 1 / x0, pos_x)
            #T = self.minusCntVecMx * (x0 - 1)  # deriv wrt x at x == 1/x0
            #T2 = -0.5 * self.minusCntVecMx / (1 / x0**2)  # 0.5 * 2nd deriv at 1/x0

            return x, pos_x, c0, c1, freqs_nozeros

        elif self.regtype == 'minp':
            freq_term = counts * (_np.log(freqs_nozeros) - 1.0)
            pos_probs = _np.where(probs < self.min_p, self.min_p, probs)
            c0 = total_counts - counts / self.min_p
            c1 = 0.5 * counts / (self.min_p**2)
            return freq_term, pos_probs, c0, c1, freqs_nozeros

        else:
            raise ValueError("Invalid regularization type: %s" % self.regtype)

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x, pos_x, c0, c1, _ = intermediates
            terms = -counts * (1.0 - pos_x + _np.log(pos_x))
            #Note: order of +/- terms above is important to avoid roundoff errors when x is near 1.0
            # (see patching line below).  For example, using log(x) + 1 - x causes significant loss
            # of precision because log(x) is tiny and so is |1-x| but log(x) + 1 == 1.0.

            # remove small negative elements due to roundoff error (above expression *cannot* really be negative)
            terms = _np.maximum(terms, 0)
            # quadratic extrapolation of logl at x0 for probabilities/frequencies < x0
            terms = _np.where(x < x0, terms + c0 * (x - x0) + c1 * (x - x0)**2, terms)
            #terms = _np.where(x > 1 / x0, terms + T * (x - x0) + T2 * (x - x0)**2, terms)

        elif self.regtype == 'minp':
            freq_term, pos_probs, c0, c1, _ = intermediates
            terms = freq_term - counts * _np.log(pos_probs) + total_counts * pos_probs

            # remove small negative elements due to roundoff error (above expression *cannot* really be negative)
            terms = _np.maximum(terms, 0)
            # quadratic extrapolation of logl at min_p for probabilities < min_p
            terms = _np.where(probs < self.min_p,
                              terms + c0 * (probs - self.min_p) + c1 * (probs - self.min_p)**2, terms)
        else:
            raise ValueError("Invalid regularization type: %s" % self.regtype)

        terms = _np.where(counts == 0, self.zero_freq_terms(total_counts, probs), terms)
        # special handling for f == 0 terms
        # using cubit rounding of function that smooths N*p for p>0:
        #  has minimum at p=0; matches value, 1st, & 2nd derivs at p=a.

        if _np.min(terms) < 0.0:
            #Since we set terms = _np.maximum(terms, 0) above we know it was the regularization that caused this
            if self.regtype == 'minp':
                raise ValueError(("Regularization => negative terms!  Is min_prob_clip (%g) too large? "
                                  "(it should be smaller than the smallest frequency)") % self.min_p)
            else:
                raise ValueError("Regularization => negative terms!")


        #DEBUG TODO REMOVE
        #if debug and (self.comm is None or self.comm.Get_rank() == 0):
        #    print("LOGL OBJECTIVE: ")
        #    #print(" KM=",len(x), " nTaylored=",_np.count_nonzero(x < x0),
        #           " nZero=",_np.count_nonzero(self.minusCntVecMx==0))
        #    print(" KM=",len(self.probs), " nTaylored=",_np.count_nonzero(self.probs < self.min_p),
        #          " nZero=",_np.count_nonzero(self.minusCntVecMx==0))
        #    #print(" xrange = ",_np.min(x),_np.max(x))
        #    print(" prange = ",_np.min(self.probs),_np.max(self.probs))
        #    print(" vrange = ",_np.min(v),_np.max(v))
        #    print(" |v|^2 = ",_np.sum(v))
        #    #print(" |v(normal)|^2 = ",_np.sum(v[x >= x0]))
        #    #print(" |v(taylor)|^2 = ",_np.sum(v[x < x0]))
        #    print(" |v(normal)|^2 = ",_np.sum(v[self.probs >= self.min_p]))
        #    print(" |v(taylor)|^2 = ",_np.sum(v[self.probs < self.min_p]))
        #    imax = _np.argmax(v)
        #    print(" MAX: v=",v[imax]," p=",self.probs[imax]," f=",self.freqs[imax])
        #    " x=",x[imax]," pos_x=",pos_x[imax],

        return terms

    def lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        # lsvec = sqrt(terms), but don't use base class fn b/c of special taylor patch...
        lsvec = _np.sqrt(self.terms(probs, counts, total_counts, freqs, intermediates))

        if self.regtype == "pfratio":  # post-sqrt(v) 1st order taylor patch for x near 1.0 - maybe unnecessary
            freqs_nozeros = _np.where(counts == 0, 1.0, freqs)
            x = probs / freqs_nozeros  # objective is -Nf*(log(x) + 1 - x)
            lsvec = _np.where(_np.abs(x - 1) < 1e-6, _np.sqrt(counts) * _np.abs(x - 1) / _np.sqrt(2), lsvec)

        return lsvec

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x, pos_x, c0, c1, freqs_nozeros = intermediates
            dterms = (total_counts * (-1 / pos_x + 1))
            dterms_taylor = (c0 + 2 * c1 * (x - x0)) / freqs_nozeros
            #dterms_taylor2 = (T + 2 * T2 * (x - x0)) / self.freqs_nozeros
            dterms = _np.where(x < x0, dterms_taylor, dterms)
            #terms = _np.where(x > 1 / x0, dprobs_taylor2, dterms)

        elif self.regtype == 'minp':
            _, pos_probs, c0, c1, freqs_nozeros = intermediates
            dterms = total_counts - counts / pos_probs
            dterms_taylor = c0 + 2 * c1 * (probs - self.min_p)
            dterms = _np.where(probs < self.min_p, dterms_taylor, dterms)

        dterms_zerofreq = self.zero_freq_dterms(total_counts, probs)
        dterms = _np.where(counts == 0, dterms_zerofreq, dterms)
        return dterms

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        # terms = Nf*(log(f)-log(p)) + N*(p-f)  OR const + S*(p - minp) + S2*(p - minp)^2
        # dterms/dp = -Nf/p + N  OR  c0 + 2*S2*(p - minp)
        # d2terms/dp2 = Nf/p^2   OR  2*S2
        assert(self.regtype == "minp")
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        _, pos_probs, c0, c1, freqs_nozeros = intermediates
        d2terms_dp2 = _np.where(probs < self.min_p, 2 * c1, counts / pos_probs**2)
        zfc = _np.where(probs >= self.radius, 0.0,
                        total_counts * ((-2.0 / self.radius**2) * probs + 2.0 / self.radius))
        d2terms_dp2 = _np.where(counts == 0, zfc, d2terms_dp2)
        return d2terms_dp2  # a 1D array of d2(logl)/dprobs2 values; shape = (nEls,)

    #Required zero-term methods for omitted probs support in model-based objective functions
    def _zero_freq_terms_harsh(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, probs,
                                        (-1.0 / (3 * a**2)) * probs**3 + probs**2 / a + a / 3.0)

    def _zero_freq_dterms_harsh(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, 1.0, (-1.0 / a**2) * probs**2 + 2 * probs / a)

    def _zero_freq_hterms_harsh(self, total_counts, probs):
        a = self.radius
        return total_counts * _np.where(probs >= a, 0.0, (-2.0 / a**2) * probs + 2 / a)

    def _zero_freq_terms_relaxed(self, total_counts, probs):
        # quadratic N*C0*p^2 that == N*p at p=1/C0.
        # Pick C0 so it is ~ magnitude of curvature at patch-pt p/f = x1
        # Note that at d2f/dx2 at x1 is 0.5 N*f / x1^2 so d2f/dp2 = 0.5 (N/f) / x1^2  (dx/dp = 1/f)
        # Thus, we want C0 ~ 0.5(N/f)/x1^2; the largest this value can be is when f=fmin
        c1 = (0.5 / self.fmin) * 1.0 / (self.x1**2)
        p0 = 1.0 / c1
        return total_counts * _np.where(probs > p0, probs, c1 * probs**2)

    def _zero_freq_dterms_relaxed(self, total_counts, probs):
        c1 = (0.5 / self.fmin) * 1.0 / (self.x1**2)
        p0 = 1.0 / c1
        return total_counts * _np.where(probs > p0, 1.0, 2 * c1 * probs)

    def _zero_freq_hterms_relaxed(self, total_counts, probs):
        raise NotImplementedError()  # This is straightforward, but do it later.


class RawDeltaLogLFunction(RawObjectiveFunction):
    def __init__(self, regularization=None,
                 resource_alloc=None, name='dlogl', description="2*Delta(log(L))", verbosity=0):
        super().__init__(regularization, resource_alloc, name, description, verbosity)

    def get_chi2k_distributed_qty(self, objective_function_value):
        return 2 * objective_function_value  # 2 * deltaLogL is what is chi2_k distributed

    def set_regularization(self, min_prob_clip=1e-4, pfratio_stitchpt=None, pfratio_derivpt=None):
        if min_prob_clip is not None:
            assert(pfratio_stitchpt is None and pfratio_derivpt is None), \
                "Cannot specify pfratio and min_prob_clip arguments as non-None!"
            self.min_p = min_prob_clip
            self.regtype = "minp"
        else:
            assert(min_prob_clip is None), "Cannot specify pfratio and min_prob_clip arguments as non-None!"
            self.x0 = pfratio_stitchpt
            self.x1 = pfratio_derivpt
            self.regtype = "pfratio"

    def _intermediates(self, probs, counts, total_counts, freqs):
        """ Intermediate values used by both terms(...) and dterms(...) """
        # Quantities depending on data only (not probs): could be computed once and
        # passed in as arguments to this (and other) functions?
        freqs_nozeros = _np.where(counts == 0, 1.0, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x1 = self.x1
            x = probs / freqs_nozeros  # objective is -Nf*log(x)
            pos_x = _np.where(x < x0, x0, x)
            c0 = -counts * (1 / x1)  # deriv wrt x at x == x1 (=min_p)
            c1 = 0.5 * counts / (x1**2)  # 0.5 * 2nd deriv at x1
            return x, pos_x, c0, c1, freqs_nozeros

        elif self.regtype == 'minp':
            freq_term = counts * _np.log(freqs_nozeros)  # objective is Nf*(log(f) - log(p))
            pos_probs = _np.where(probs < self.min_p, self.min_p, probs)
            c0 = -counts / self.min_p
            c1 = 0.5 * counts / (self.min_p**2)
            return freq_term, pos_probs, c0, c1, freqs_nozeros

        else:
            raise ValueError("Invalid regularization type: %s" % self.regtype)

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x, pos_x, c0, c1, freqs_nozeros = intermediates
            terms = -counts * _np.log(pos_x)
            terms = _np.where(x < x0, terms + c0 * (x - x0) + c1 * (x - x0)**2, terms)

        elif self.regtype == 'minp':
            freq_term, pos_probs, c0, c1, _ = intermediates
            terms = freq_term - counts * _np.log(pos_probs)
            terms = _np.where(probs < self.min_p,
                              terms + c0 * (probs - self.min_p) + c1 * (probs - self.min_p)**2, terms)
        else:
            raise ValueError("Invalid regularization type: %s" % self.regtype)

        terms = _np.where(counts == 0, 0.0, terms)
        #Note: no penalty for omitted probabilities (objective fn == 0 whenever counts == 0)

        terms.shape = [self.nelements]  # reshape ensuring no copy is needed
        return terms

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)

        if self.regtype == 'pfratio':
            x0 = self.x0
            x, pos_x, c0, c1, freqs_nozeros = intermediates
            dterms = total_counts * (-1 / pos_x)  # note Nf/p = N/x
            dterms_taylor = (c0 + 2 * c1 * (x - x0)) / freqs_nozeros  # (...) is df/dx and want df/dp = df/dx * (1/f)
            dterms = _np.where(x < x0, dterms_taylor, dterms)

        elif self.regtype == 'minp':
            _, pos_probs, c0, c1, freqs_nozeros = intermediates
            dterms = -counts / pos_probs
            dterms_taylor = c0 + 2 * c1 * (probs - self.min_p)
            dterms = _np.where(probs < self.min_p, dterms_taylor, dterms)

        dterms = _np.where(counts == 0, 0.0, dterms)
        return dterms

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        # terms = Nf*log(p) OR const + S*(p - minp) + S2*(p - minp)^2
        # dterms/dp = Nf/p  OR  c0 + 2*S2*(p - minp)
        # d2terms/dp2 = -Nf/p^2   OR  2*S2
        assert(self.regtype == "minp")
        if intermediates is None:
            intermediates = self._intermediates(probs, counts, total_counts, freqs)
        _, pos_probs, c0, c1, freqs_nozeros = intermediates
        d2terms_dp2 = _np.where(probs < self.min_p, 2 * c1, counts / pos_probs**2)
        d2terms_dp2 = _np.where(counts == 0, 0.0, d2terms_dp2)
        return d2terms_dp2  # a 1D array of d2(logl)/dprobs2 values; shape = (nEls,)

    def lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        # lsvec = sqrt(terms), but terms are not guaranteed to be positive!
        raise ValueError("LogL objective function cannot produce a LS-vector b/c terms are not necessarily positive!")

    def dlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        raise ValueError("LogL objective function cannot produce a LS-vector b/c terms are not necessarily positive!")

    def dlsvec_and_lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        raise ValueError("LogL objective function cannot produce a LS-vector b/c terms are not necessarily positive!")

    def hlsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        raise ValueError("LogL objective function cannot produce a LS-vector b/c terms are not necessarily positive!")

    #Required zero-term methods for omitted probs support in model-based objective functions
    def zero_freq_terms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')

    def zero_freq_dterms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')

    def zero_freq_hterms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')


class RawMaxLogLFunction(RawObjectiveFunction):
    def __init__(self, regularization=None,
                 resource_alloc=None, name='maxlogl', description="Max LogL", verbosity=0, poisson_picture=True):
        super().__init__(regularization, resource_alloc, name, description, verbosity)
        self.poisson_picture = poisson_picture

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        freqs_nozeros = _np.where(counts == 0, 1.0, freqs)
        if self.poisson_picture:
            terms = counts * (_np.log(freqs_nozeros) - 1.0)
        else:
            terms = counts * _np.log(freqs_nozeros)
        terms[counts == 0] = 0.0
        return terms

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        return _np.zeros(len(probs), 'd')

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        return _np.zeros(len(probs), 'd')

    def lsvec(self, probs, counts, total_counts, freqs, intermediates=None):
        raise ValueError("MaxLogL objective function cannot produce a LS-vector: terms are not necessarily positive!")

    def dlsvec(self, probs, counts, total_counts, freqs):
        raise ValueError("MaxLogL objective function cannot produce a LS-vector: terms are not necessarily positive!")

    def dlsvec_and_lsvec(self, probs, counts, total_counts, freqs):
        raise ValueError("MaxLogL objective function cannot produce a LS-vector: terms are not necessarily positive!")

    def hlsvec(self, probs, counts, total_counts, freqs):
        raise ValueError("LogL objective function cannot produce a LS-vector b/c terms are not necessarily positive!")

    #Required zero-term methods for omitted probs support in model-based objective functions
    def zero_freq_terms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')

    def zero_freq_dterms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')

    def zero_freq_hterms(self, total_counts, probs):
        return _np.zeros(len(probs), 'd')


class RawTVDFunction(RawObjectiveFunction):
    def __init__(self, regularization=None,
                 resource_alloc=None, name='tvd', description="Total Variational Distance (TVD)", verbosity=0):
        super().__init__(regularization, resource_alloc, name, description, verbosity)

    def terms(self, probs, counts, total_counts, freqs, intermediates=None):
        return 0.5 * _np.abs(probs - freqs)

    def dterms(self, probs, counts, total_counts, freqs, intermediates=None):
        raise NotImplementedError("Derivatives not implemented for TVD yet!")

    def hterms(self, probs, counts, total_counts, freqs, intermediates=None):
        raise NotImplementedError("Derivatives not implemented for TVD yet!")

    #Required zero-term methods for omitted probs support in model-based objective functions
    def zero_freq_terms(self, total_counts, probs):
        return 0.5 * _np.abs(probs)

    def zero_freq_dterms(self, total_counts, probs):
        raise NotImplementedError("Derivatives not implemented for TVD yet!")

    def zero_freq_hterms(self, total_counts, probs):
        raise NotImplementedError("Derivatives not implemented for TVD yet!")


class TimeIndependentMDSObjectiveFunction(MDSObjectiveFunction):

    @classmethod
    def builder(cls, name=None, description=None, regularization=None, penalties=None, **kwargs):
        return ObjectiveFunctionBuilder(cls, name, description, regularization, penalties, **kwargs)

    def __init__(self, raw_objfn_cls, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):

        raw_objfn = raw_objfn_cls(regularization, resource_alloc, name, description, verbosity)
        super().__init__(raw_objfn, mdl, dataset, circuit_list, cache, enable_hessian)

        if penalties is None: penalties = {}
        self.ex = self.set_penalties(**penalties)  # "extra" (i.e. beyond the (circuit,spamlabel)) rows of jacobian

        #  Allocate peristent memory
        #  (must be AFTER possible operation sequence permutation by
        #   tree and initialization of ds_circuits_to_use)
        self.probs = _np.empty(self.nelements, 'd')
        self.jac = _np.empty((self.nelements + self.ex, self.nparams), 'd')
        self.hprobs = _np.empty((self.nelements, self.nparams, self.nparams), 'd') if self.enable_hessian else None
        self.counts, self.N = self.compute_count_vectors()
        self.freqs = self.counts / self.N
        self.maxCircuitLength = max([len(x) for x in self.circuits_to_use])
        self.precompute_omitted_freqs()  # sets self.first

    #Model-based regularization and penalty support functions

    def set_penalties(self, regularize_factor=0, cptp_penalty_factor=0, spam_penalty_factor=0,
                      forcefn_grad=None, shift_fctr=100, prob_clip_interval=(-10000, 1000)):

        self.regularize_factor = regularize_factor
        self.cptp_penalty_factor = cptp_penalty_factor
        self.spam_penalty_factor = spam_penalty_factor
        self.forcefn_grad = forcefn_grad

        self.prob_clip_interval = prob_clip_interval  # not really a "penalty" per se, but including it as one
        # gives the user the ability to easily set it if they ever need to (unlikely)

        ex = 0  # Compute "extra" number of terms/lsvec-element/rows-of-jacobian beyond evaltree elements

        if self.regularize_factor != 0: ex += self.nparams
        if self.cptp_penalty_factor != 0: ex += _cptp_penalty_size(self.mdl)
        if self.spam_penalty_factor != 0: ex += _spam_penalty_size(self.mdl)

        if forcefn_grad is not None:
            ex += forcefn_grad.shape[0]
            ffg_norm = _np.linalg.norm(forcefn_grad)
            start_norm = _np.linalg.norm(self.mdl.to_vector())
            self.forceOffset = self.nelements + ex  # index to jacobian row of first forcing term
            self.forceShift = ffg_norm * (ffg_norm + start_norm) * shift_fctr
            #used to keep forceShift - _np.dot(forcefn_grad,paramvec) positive (Note: not analytic, just a heuristic!)

        return ex

    def lspenaltyvec(self, paramvec):

        if self.forcefn_grad is not None:
            force_vec = self.forceShift - _np.dot(self.forcefn_grad, self.mdl.to_vector())
            assert(_np.all(force_vec >= 0)), "Inadequate forcing shift!"
            forcefn_penalty = _np.sqrt(force_vec)
        else: forcefn_penalty = []

        if self.regularize_factor != 0:
            paramvec_norm = self.regularize_factor * _np.array([max(0, absx - 1.0) for absx in map(abs, paramvec)], 'd')
        else: paramvec_norm = []  # so concatenate ignores

        if self.cptp_penalty_factor > 0:
            cp_penalty_vec = _cptp_penalty(self.mdl, self.cptp_penalty_factor, self.opBasis)
        else: cp_penalty_vec = []  # so concatenate ignores

        if self.spam_penalty_factor > 0:
            spam_penalty_vec = _spam_penalty(self.mdl, self.spam_penalty_factor, self.opBasis)
        else: spam_penalty_vec = []  # so concatenate ignores

        return _np.concatenate((forcefn_penalty, paramvec_norm, cp_penalty_vec, spam_penalty_vec))

    def penaltyvec(self, paramvec):
        return self.lspenaltyvec(paramvec)**2

    def fill_lspenaltyvec_jac(self, paramvec, lspenaltyvec_jac):
        off = 0

        if self.regularize_factor > 0:
            n = len(paramvec)
            lspenaltyvec_jac[off:off + n, :] = _np.diag([(self.regularize_factor * _np.sign(x) if abs(x) > 1.0 else 0.0)
                                                         for x in paramvec])  # (N,N)
            off += n

        if self.cptp_penalty_factor > 0:
            off += _cptp_penalty_jac_fill(
                self.jac[off:, :], self.mdl, self.cptp_penalty_factor, self.opBasis)

        if self.spam_penalty_factor > 0:
            off += _spam_penalty_jac_fill(
                self.jac[off:, :], self.mdl, self.spam_penalty_factor, self.opBasis)

        assert(off == self.ex)

    def fill_dterms_penalty(self, paramvec, terms_jac):
        # terms_penalty = ls_penalty**2
        # terms_penalty_jac = 2 * ls_penalty * ls_penalty_jac
        self.fill_lspenaltyvec_jac(paramvec, terms_jac)
        terms_jac[:, :] *= 2 * self.lspenaltyvec(paramvec)[:, None]

    #Omitted-probability support functions

    def omitted_prob_first_terms(self, probs):
        omitted_probs = 1.0 - _np.array([_np.sum(probs[self.lookup[i]])
                                         for i in self.indicesOfCircuitsWithOmittedData])
        return self.raw_objfn.zero_freq_terms(self.N[self.firsts], omitted_probs)
        #DEBUG TODO REMOVE
        #if debug and (self.comm is None or self.comm.Get_rank() == 0):
        #    print(" omitted_probs range = ", _np.min(omitted_probs), _np.max(omitted_probs))
        #    p0 = 1.0 / (0.5 * (1. + self.alpha) / (self.x1**(2 + self.alpha) * self.fmin))
        #    print(" nSparse = ",len(self.firsts), " nOmitted >p0=", _np.count_nonzero(omitted_probs >= p0),
        #          " <0=", _np.count_nonzero(omitted_probs < 0))
        #    print(" |v(post-sparse)|^2 = ",_np.sum(v))

    def update_lsvec_for_omitted_probs(self, lsvec, probs):
        # lsvec = sqrt(terms) => sqrt(terms + zerofreqfn(omitted))
        lsvec[self.firsts] = _np.sqrt(lsvec[self.firsts]**2 + self.omitted_prob_first_terms(probs))

    def update_terms_for_omitted_probs(self, terms, probs):
        # terms => terms + zerofreqfn(omitted)
        terms[self.firsts] += self.omitted_prob_first_terms(probs)
        #DEBUG TODO REMOVE
        #if debug and (self.comm is None or self.comm.Get_rank() == 0):
        #    print(" vrange2 = ",_np.min(v),_np.max(v))
        #    print(" omitted_probs range = ", _np.min(omitted_probs), _np.max(omitted_probs))
        #    p0 = 1.0 / ((0.5 / self.fmin) * 1.0 / self.x1**2)
        #    print(" nSparse = ",len(self.firsts), " nOmitted >p0=", _np.count_nonzero(omitted_probs >= p0),
        #          " <0=", _np.count_nonzero(omitted_probs < 0))
        #    print(" |v(post-sparse)|^2 = ",_np.sum(v))

    def omitted_prob_first_dterms(self, probs):
        omitted_probs = 1.0 - _np.array([_np.sum(probs[self.lookup[i]])
                                         for i in self.indicesOfCircuitsWithOmittedData])
        return self.raw_objfn.zero_freq_dterms(self.N[self.firsts], omitted_probs)

    def update_dterms_for_omitted_probs(self, dterms, probs, dprobs_omitted_rowsum):
        # terms => terms + zerofreqfn(omitted)
        # dterms => dterms + dzerofreqfn(omitted) * domitted  (and domitted = (-omitted_rowsum))
        dterms[self.firsts] -= self.omitted_prob_first_dterms(probs)[:, None] * dprobs_omitted_rowsum

    def update_dlsvec_for_omitted_probs(self, dlsvec, lsvec, probs, dprobs_omitted_rowsum):
        # lsvec = sqrt(terms) => sqrt(terms + zerofreqfn(omitted))
        # dlsvec = 0.5 / sqrt(terms) * dterms = 0.5 / lsvec * dterms
        #          0.5 / sqrt(terms + zerofreqfn(omitted)) * (dterms + dzerofreqfn(omitted) * domitted)
        # so dterms = 2 * lsvec * dlsvec, and
        #    new_dlsvec = 0.5 / sqrt(...) * (2 * lsvec * dlsvec + dzerofreqfn(omitted) * domitted)
        lsvec_firsts = lsvec[self.firsts]
        updated_lsvec = _np.sqrt(lsvec_firsts**2 + self.omitted_prob_first_terms(probs))
        updated_lsvec = _np.where(updated_lsvec == 0, 1.0, updated_lsvec)  # avoid 0/0 where lsvec & deriv == 0

        # dlsvec => 0.5 / updated_lsvec * (2 * lsvec * dlsvec + dzerofreqfn(omitted) * domitted) memory efficient:
        dlsvec[self.firsts] *= (lsvec_firsts / updated_lsvec)[:, None]
        dlsvec[self.firsts] -= ((0.5 / updated_lsvec) * self.omitted_prob_first_dterms(probs))[:, None] \
            * dprobs_omitted_rowsum
        #TODO: REMOVE
        #if (self.comm is None or self.comm.Get_rank() == 0):
        #    print(" |dprobs_omitted_rowsum| = ",_np.linalg.norm(dprobs_omitted_rowsum))
        #    print(" |dprobs_factor_omitted| = ",_np.linalg.norm(((0.5 / lsvec_firsts)
        #                                    * self.omitted_prob_first_dterms(probs))))
        #    print(" |jac(post-sparse)| = ",_np.linalg.norm(dlsvec))

    #Objective Function

    def lsvec(self, paramvec=None, oob_check=False):
        tm = _time.time()
        if paramvec is not None: self.mdl.from_vector(paramvec)
        self.mdl.bulk_fill_probs(self.probs, self.eval_tree, self.prob_clip_interval,
                                 self.check, self.raw_objfn.comm)

        if oob_check:  # Only used for termgap cases
            if not self.mdl.bulk_probs_paths_are_sufficient(self.eval_tree,
                                                            self.probs,
                                                            self.raw_objfn.comm,
                                                            mem_limit=self.raw_objfn.mem_limit,
                                                            verbosity=1):
                raise ValueError("Out of bounds!")  # signals LM optimizer

        lsvec = self.raw_objfn.lsvec(self.probs, self.counts, self.N, self.freqs)
        lsvec = _np.concatenate((lsvec, self.lspenaltyvec(paramvec)))

        if self.firsts is not None:
            self.update_lsvec_for_omitted_probs(lsvec, self.probs)

        self.raw_objfn.profiler.add_time("LS OBJECTIVE", tm)
        assert(lsvec.shape == (self.nelements,))  # reshape ensuring no copy is needed
        return lsvec

    def terms(self, paramvec=None):
        tm = _time.time()
        if paramvec is not None: self.mdl.from_vector(paramvec)
        self.mdl.bulk_fill_probs(self.probs, self.eval_tree, self.prob_clip_interval,
                                 self.check, self.raw_objfn.comm)

        terms = self.raw_objfn.terms(self.probs, self.counts, self.N, self.freqs)
        terms = _np.concatenate((terms, self.penaltyvec(paramvec)))

        if self.firsts is not None:
            self.update_terms_for_omitted_probs(terms, self.probs)

        self.raw_objfn.profiler.add_time("TERMS OBJECTIVE", tm)
        assert(terms.shape == (self.nelements,))  # reshape ensuring no copy is needed
        return terms

    # Jacobian function
    def dlsvec(self, paramvec=None):
        tm = _time.time()
        dprobs = self.jac[0:self.nelements, :]  # avoid mem copying: use jac mem for dprobs
        dprobs.shape = (self.nelements, self.nparams)
        if paramvec is not None: self.mdl.from_vector(paramvec)
        self.mdl.bulk_fill_dprobs(dprobs, self.eval_tree,
                                  pr_mx_to_fill=self.probs, clip_to=self.prob_clip_interval,
                                  check=self.check, comm=self.raw_objfn.comm, wrt_block_size=self.wrt_blk_size,
                                  profiler=self.raw_objfn.profiler, gather_mem_limit=self.gthrMem)

        #DEBUG TODO REMOVE - test dprobs to make sure they look right.
        #eps = 1e-7
        #db_probs = _np.empty(self.probs.shape, 'd')
        #db_probs2 = _np.empty(self.probs.shape, 'd')
        #db_dprobs = _np.empty(dprobs.shape, 'd')
        #self.mdl.bulk_fill_probs(db_probs, self.eval_tree, self.prob_clip_interval, self.check, self.comm)
        #for i in range(self.nparams):
        #    paramvec_eps = paramvec.copy()
        #    paramvec_eps[i] += eps
        #    self.mdl.from_vector(paramvec_eps)
        #    self.mdl.bulk_fill_probs(db_probs2, self.eval_tree, self.prob_clip_interval, self.check, self.comm)
        #    db_dprobs[:,i] = (db_probs2 - db_probs) / eps
        #if _np.linalg.norm(dprobs - db_dprobs)/dprobs.size > 1e-6:
        #    #assert(False), "STOP: %g" % (_np.linalg.norm(dprobs - db_dprobs)/db_dprobs.size)
        #    print("DB: dprobs per el mismatch = ",_np.linalg.norm(dprobs - db_dprobs)/db_dprobs.size)
        #self.mdl.from_vector(paramvec)
        #dprobs[:,:] = db_dprobs[:,:]

        if self.firsts is not None:
            for ii, i in enumerate(self.indicesOfCircuitsWithOmittedData):
                self.dprobs_omitted_rowsum[ii, :] = _np.sum(dprobs[self.lookup[i], :], axis=0)

        dg_dprobs, lsvec = self.raw_objfn.dlsvec_and_lsvec(self.probs, self.counts, self.N, self.freqs)
        dprobs *= dg_dprobs[:, None]
        # (nelements,N) * (nelements,1)   (N = dim of vectorized model)
        # this multiply also computes jac, which is just dprobs
        # with a different shape (jac.shape == [nelements,nparams])

        if self.firsts is not None:
            #Note: lsvec is assumed to be *not* updated w/omitted probs contribution
            self.update_dlsvec_for_omitted_probs(dprobs, lsvec, self.probs, self.dprobs_omitted_rowsum)

        self.fill_lspenaltyvec_jac(paramvec, self.jac[self.nelements:, :])  # jac.shape == (nelements+N,N)

        if self.check_jacobian: _opt.check_jac(lambda v: self.lsvec(
            v), paramvec, self.jac, tol=1e-3, eps=1e-6, errType='abs')  # TO FIX

        # dpr has shape == (nCircuits, nDerivCols), weights has shape == (nCircuits,)
        # return shape == (nCircuits, nDerivCols) where ret[i,j] = dP[i,j]*(weights+dweights*(p-f))[i]
        self.raw_objfn.profiler.add_time("JACOBIAN", tm)
        return self.jac

    def dterms(self, paramvec=None):
        tm = _time.time()
        dprobs = self.jac[0:self.nelements, :]  # avoid mem copying: use jac mem for dprobs
        dprobs.shape = (self.nelements, self.nparams)
        if paramvec is not None: self.mdl.from_vector(paramvec)
        self.mdl.bulk_fill_dprobs(dprobs, self.eval_tree,
                                  pr_mx_to_fill=self.probs, clip_to=self.prob_clip_interval,
                                  check=self.check, comm=self.raw_objfn.comm, wrt_block_size=self.wrt_blk_size,
                                  profiler=self.raw_objfn.profiler, gather_mem_limit=self.gthrMem)

        if self.firsts is not None:
            for ii, i in enumerate(self.indicesOfCircuitsWithOmittedData):
                self.dprobs_omitted_rowsum[ii, :] = _np.sum(dprobs[self.lookup[i], :], axis=0)

        dprobs *= self.raw_objfn.dterms(self.probs, self.counts, self.N, self.freqs)[:, None]
        # (nelements,N) * (nelements,1)   (N = dim of vectorized model)
        # this multiply also computes jac, which is just dprobs
        # with a different shape (jac.shape == [nelements,nparams])

        if self.firsts is not None:
            self.update_dterms_for_omitted_probs(dprobs, self.probs, self.dprobs_omitted_rowsum)

        self.fill_dterms_penalty(paramvec, self.jac[self.nelements:, :])  # jac.shape == (nelements+N,N)

        if self.check_jacobian: _opt.check_jac(lambda v: self.lsvec(
            v), paramvec, self.jac, tol=1e-3, eps=1e-6, errType='abs')  # TO FIX

        # dpr has shape == (nCircuits, nDerivCols), weights has shape == (nCircuits,)
        # return shape == (nCircuits, nDerivCols) where ret[i,j] = dP[i,j]*(weights+dweights*(p-f))[i]
        self.raw_objfn.profiler.add_time("JACOBIAN", tm)
        return self.jac

    def hessian_brute(self, pv=None):
        if self.firsts is not None:
            raise NotImplementedError("Brute-force Hessian not implemented for sparse data (yet)")

        #General idea of what we're doing:
        # Let f(pv) = g(probs(pv)), and let there be nelements elements (i.e. probabilities) & len(pv) == N
        #  => df/dpv = dg/dprobs * dprobs/dpv = (nelements,) * (nelements,N)
        #  => d2f/dpv1dpv2 = d/dpv2( dg/dprobs * dprobs/dpv1 )
        #                  = (d2g/dprobs2 * dprobs/dpv2) * dprobs/dpv1 + dg/dprobs * d2probs/dpv1dpv2
        #                  =  (KM,)       * (KM,N2)       * (KM,N1)    + (KM,)     * (KM,N1,N2)
        # Note that we need to end up with an array with shape (KM,N1,N2), and so we need to swap axes of first term

        if pv is not None: self.mdl.from_vector(pv)
        dprobs = self.jac[0:self.nelements, :]  # avoid mem copying: use jac mem for dprobs
        self.mdl.bulk_fill_hprobs(self.hprobs, self.eval_tree, self.probs, dprobs,
                                  self.prob_clip_interval, self.check, self.comm)  # use cache?

        dg_dprobs = self.raw_objfn.dterms(self.probs, self.counts, self.N, self.freqs)[:, None, None]
        d2g_dprobs2 = self.raw_objfn.hterms(self.probs, self.counts, self.N, self.freqs)[:, None, None]
        dprobs_dp1 = dprobs[:, :, None]  # (nelements,N,1)
        dprobs_dp2 = dprobs[:, None, :]  # (nelements,1,N)

        #hessian = d2g_dprobs2 * dprobs_dp2 * dprobs_dp1 + dg_dprobs * self.hprobs
        # do the above line in a more memory efficient way:
        hessian = self.hprobs
        hessian *= dg_dprobs
        hessian += d2g_dprobs2 * dprobs_dp2 * dprobs_dp1

        return _np.sum(hessian, axis=0)  # sum over operation sequences and spam labels => (N)

    def approximate_hessian(self, pv=None):
        #Almost the same as function above but drops hprobs term
        if self.firsts is not None:
            raise NotImplementedError("Chi2 hessian not implemented for sparse data (yet)")

        if pv is not None: self.mdl.from_vector(pv)
        dprobs = self.jac[0:self.nelements, :]  # avoid mem copying: use jac mem for dprobs
        self.mld.bulk_fill_dprobs(dprobs, self.eval_tree, self.probs, self.prob_clip_interval,
                                  self.check, self.comm)  # use cache?

        d2g_dprobs2 = self.raw_objfn.hterms(self.probs, self.counts, self.N, self.freqs)[:, None, None]
        dprobs_dp1 = dprobs[:, :, None]  # (nelements,N,1)
        dprobs_dp2 = dprobs[:, None, :]  # (nelements,1,N)

        hessian = d2g_dprobs2 * dprobs_dp2 * dprobs_dp1
        return _np.sum(hessian, axis=0)  # sum over operation sequences and spam labels => (N)

    def hessian(self, pv=None):
        if pv is not None: self.mdl.from_vector(pv)
        return self._construct_hessian(self.counts, self.N, self.prob_clip_interval)

    def _hessian_from_block(self, hprobs, dprobs12, probs, counts, total_counts, freqs):
        """ Factored-out computation of hessian from raw components """

        #General idea of what we're doing:
        # Let f(pv) = g(probs(pv)), and let there be KM elements (i.e. probabilities) & len(pv) == N
        #  => df/dpv = dg/dprobs * dprobs/dpv = (KM,) * (KM,N)
        #  => d2f/dpv1dpv2 = d/dpv2( dg/dprobs * dprobs/dpv1 )
        #                  = (d2g/dprobs2 * dprobs/dpv2) * dprobs/dpv1 + dg/dprobs * d2probs/dpv1dpv2
        #                  =  (KM,)       * (KM,N2)       * (KM,N1)    + (KM,)     * (KM,N1,N2)
        # so: hessian = d2(raw_objfn)/dprobs2 * dprobs12 + d(raw_objfn)/dprobs * hprobs

        dprobs12_coeffs = self.raw_objfn.hterms(probs, counts, total_counts, freqs)
        hprobs_coeffs = self.raw_objfn.dterms(probs, counts, total_counts, freqs)

        if self.firsts is not None:
            #Allocate these above?  Need to know block sizes of dprobs12 & hprobs...
            dprobs12_omitted_rowsum = _np.empty((len(self.firsts),) + dprobs12.shape[1:], 'd')
            hprobs_omitted_rowsum = _np.empty((len(self.firsts),) + hprobs.shape[1:], 'd')

            omitted_probs = 1.0 - _np.array([_np.sum(probs[self.lookup[i]])
                                             for i in self.indicesOfCircuitsWithOmittedData])
            for ii, i in enumerate(self.indicesOfCircuitsWithOmittedData):
                dprobs12_omitted_rowsum[ii, :, :] = _np.sum(dprobs12[self.lookup[i], :, :], axis=0)
                hprobs_omitted_rowsum[ii, :, :] = _np.sum(hprobs[self.lookup[i], :, :], axis=0)

            dprobs12_omitted_coeffs = -self.raw_objfn.zero_freq_hterms(total_counts[self.firsts], omitted_probs)
            hprobs_omitted_coeffs = -self.raw_objfn.zero_freq_dterms(total_counts[self.firsts], omitted_probs)

        # hessian = hprobs_coeffs * hprobs + dprobs12_coeff * dprobs12
        #  but re-using dprobs12 and hprobs memory (which is overwritten!)
        hprobs *= hprobs_coeffs[:, None, None]
        dprobs12 *= dprobs12_coeffs[:, None, None]
        if self.firsts is not None:
            hprobs[self.firsts, :, :] += hprobs_omitted_coeffs[:, None, None] * hprobs_omitted_rowsum
            dprobs12[self.firsts, :, :] += dprobs12_omitted_coeffs[:, None, None] * dprobs12_omitted_rowsum
        hessian = dprobs12; hessian += hprobs

        # hessian[iElement,iModelParam1,iModelParams2] contains all d2(logl)/d(modelParam1)d(modelParam2) contributions
        # suming over element dimension (operation sequences in eval_subtree) gets current subtree contribution
        # for (N,N')-sized block of Hessian
        return _np.sum(hessian, axis=0)


class Chi2Function(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawChi2Function, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class ChiAlphaFunction(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawChiAlphaFunction, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class FreqWeightedChi2Function(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawFreqWeightedChi2Function, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class PoissonPicDeltaLogLFunction(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawPoissonPicDeltaLogLFunction, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class DeltaLogLFunction(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawDeltaLogLFunction, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class MaxLogLFunction(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawMaxLogLFunction, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class TVDFunction(TimeIndependentMDSObjectiveFunction):
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, description=None, verbosity=0, enable_hessian=False):
        super().__init__(RawTVDFunction, mdl, dataset, circuit_list, regularization, penalties,
                         cache, resource_alloc, name, description, verbosity, enable_hessian)


class TimeDependentMDSObjectiveFunction(MDSObjectiveFunction):

    #This objective function can handle time-dependent circuits - that is, circuits_to_use are treated as
    # potentially time-dependent and mdl as well.  For now, we don't allow any regularization or penalization
    # in this case.
    def __init__(self, mdl, dataset, circuit_list, regularization=None, penalties=None,
                 cache=None, resource_alloc=None, name=None, verbosity=0):

        dummy = RawObjectiveFunction({}, resource_alloc, name, None, verbosity)
        super().__init__(dummy, mdl, dataset, circuit_list, cache, enable_hessian=False)

        self.time_dependent = True

        if regularization is None: regularization = {}
        self.set_regularization(**regularization)

        if penalties is None: penalties = {}
        self.ex = self.set_penalties(**penalties)  # "extra" (i.e. beyond the (circuit,spamlabel)) rows of jacobian

        #  Allocate peristent memory
        #  (must be AFTER possible operation sequence permutation by
        #   tree and initialization of ds_circuits_to_use)
        self.v = _np.empty(self.nelements, 'd')
        self.jac = _np.empty((self.nelements + self.ex, self.nparams), 'd')
        self.maxCircuitLength = max([len(x) for x in self.circuits_to_use])
        self.num_total_outcomes = [mdl.get_num_outcomes(c) for c in self.circuits_to_use]  # for sparse data detection

    def set_regularization(self):
        pass  # no regularization

    def set_penalties(self):
        pass  # no penalties

    def lsvec(self, paramvec):
        raise NotImplementedError()

    def dlsvec(self, paramvec):
        raise NotImplementedError()


class TimeDependentChi2Function(TimeDependentMDSObjectiveFunction):

    #This objective function can handle time-dependent circuits - that is, circuits_to_use are treated as
    # potentially time-dependent and mdl as well.  For now, we don't allow any regularization or penalization
    # in this case.

    def set_regularization(self, min_prob_clip_for_weighting=1e-4, radius=1e-4):
        self.min_p = min_prob_clip_for_weighting
        self.a = radius  # parameterizes "roundness" of f == 0 terms

    def set_penalties(self, regularize_factor=0, cptp_penalty_factor=0, spam_penalty_factor=0,
                      prob_clip_interval=(-10000, 10000)):
        assert(regularize_factor == 0 and cptp_penalty_factor == 0 and spam_penalty_factor == 0), \
            "Cannot apply regularization or penalization in time-dependent chi2 case (yet)"
        self.prob_clip_interval = prob_clip_interval

    def lsvec(self, paramvec):
        tm = _time.time()
        self.mdl.from_vector(paramvec)
        fsim = self.mdl._fwdsim()
        v = self.v
        fsim.bulk_fill_timedep_chi2(v, self.eval_tree, self.ds_circuits_to_use, self.num_total_outcomes,
                                    self.dataset, self.min_prob_clip_for_weighting, self.prob_clip_interval, self.comm)
        self.raw_objfn.profiler.add_time("Time-dep chi2: OBJECTIVE", tm)
        assert(v.shape == (self.nelements,))  # reshape ensuring no copy is needed
        return v.copy()  # copy() needed for FD deriv, and we don't need to be stingy w/memory at objective fn level

    def dlsvec(self, paramvec):
        tm = _time.time()
        dprobs = self.jac.view()  # avoid mem copying: use jac mem for dprobs
        dprobs.shape = (self.nelements, self.nparams)
        self.mdl.from_vector(paramvec)

        fsim = self.mdl._fwdsim()
        fsim.bulk_fill_timedep_dchi2(dprobs, self.eval_tree, self.ds_circuits_to_use, self.num_total_outcomes,
                                     self.dataset, self.min_prob_clip_for_weighting, self.prob_clip_interval, None,
                                     self.comm, wrt_block_size=self.wrt_blk_size, profiler=self.raw_objfn.profiler,
                                     gather_mem_limit=self.gthrMem)

        self.raw_objfn.profiler.add_time("Time-dep chi2: JACOBIAN", tm)
        return self.jac


class TimeDependentPoissonPicLogLFunction(ObjectiveFunction):

    def set_regularization(self, min_prob_clip=1e-4, radius=1e-4):
        self.min_p = min_prob_clip
        self.a = radius  # parameterizes "roundness" of f == 0 terms

    def set_penalties(self, cptp_penalty_factor=0, spam_penalty_factor=0, forcefn_grad=None, shift_fctr=100,
                      prob_clip_interval=(-10000, 10000)):
        assert(cptp_penalty_factor == 0 and spam_penalty_factor == 0), \
            "Cannot apply CPTP or SPAM penalization in time-dependent logl case (yet)"
        assert(forcefn_grad is None), "forcing functions not supported with time-dependent logl function yet"
        self.prob_clip_interval = prob_clip_interval

    def get_chi2k_distributed_qty(self, objective_function_value):
        return 2 * objective_function_value  # 2 * deltaLogL is what is chi2_k distributed

    def lsvec(self, paramvec):
        tm = _time.time()
        self.mdl.from_vector(paramvec)
        fsim = self.mdl._fwdsim()
        v = self.v
        fsim.bulk_fill_timedep_loglpp(v, self.eval_tree, self.ds_circuits_to_use, self.num_total_outcomes,
                                      self.dataset, self.min_p, self.a, self.prob_clip_interval, self.comm)
        v = _np.sqrt(v)
        v.shape = [self.nelements]  # reshape ensuring no copy is needed

        self.raw_objfn.profiler.add_time("Time-dep dlogl: OBJECTIVE", tm)
        return v  # Note: no test for whether probs is in [0,1] so no guarantee that
        #      sqrt is well defined unless prob_clip_interval is set within [0,1].

    #  derivative of  sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} ) terms:
    #   == 0.5 / sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} ) * ( -N_{i,sl} / p_{i,sl} + N[i] ) * dp
    #  with ommitted correction: sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} + N[i] * Y(1-other_ps)) terms (Y is a fn of other ps == omitted_probs)  # noqa
    #   == 0.5 / sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} + N[i]*(1-other_ps) ) * ( -N_{i,sl} / p_{i,sl} + N[i] ) * dp_{i,sl} +                   # noqa
    #      0.5 / sqrt( N_{i,sl} * -log(p_{i,sl}) + N[i] * p_{i,sl} + N[i]*(1-other_ps) ) * ( N[i]*dY/dp_j(1-other_ps) ) * -dp_j (for p_j in other_ps)      # noqa

    #  if p <  p_min then term == sqrt( N_{i,sl} * -log(p_min) + N[i] * p_min + S*(p-p_min) )
    #   and deriv == 0.5 / sqrt(...) * c0 * dp
    def dlsvec(self, paramvec):
        tm = _time.time()
        dlogl = self.jac[0:self.nelements, :]  # avoid mem copying: use jac mem for dlogl
        dlogl.shape = (self.nelements, self.nparams)
        self.mdl.from_vector(paramvec)

        fsim = self.mdl._fwdsim()
        fsim.bulk_fill_timedep_dloglpp(dlogl, self.eval_tree, self.ds_circuits_to_use, self.num_total_outcomes,
                                       self.dataset, self.min_p, self.a, self.prob_clip_interval, self.v,
                                       self.comm, wrt_block_size=self.wrt_blk_size, profiler=self.raw_objfn.profiler,
                                       gather_mem_limit=self.gthrMem)

        # want deriv( sqrt(logl) ) = 0.5/sqrt(logl) * deriv(logl)
        v = _np.sqrt(self.v)
        # derivative diverges as v->0, but v always >= 0 so clip v to a small positive value to avoid divide by zero
        # below
        v = _np.maximum(v, 1e-100)
        dlogl_factor = (0.5 / v)
        dlogl *= dlogl_factor[:, None]  # (nelements,N) * (nelements,1)   (N = dim of vectorized model)

        self.raw_objfn.profiler.add_time("do_mlgst: JACOBIAN", tm)
        return self.jac


def _cptp_penalty_size(mdl):
    return len(mdl.operations)


def _spam_penalty_size(mdl):
    return len(mdl.preps) + sum([len(povm) for povm in mdl.povms.values()])


def _cptp_penalty(mdl, prefactor, op_basis):
    """
    Helper function - CPTP penalty: (sum of tracenorms of gates),
    which in least squares optimization means returning an array
    of the sqrt(tracenorm) of each gate.

    Returns
    -------
    numpy array
        a (real) 1D array of length len(mdl.operations).
    """
    from .. import tools as _tools
    return prefactor * _np.sqrt(_np.array([_tools.tracenorm(
        _tools.fast_jamiolkowski_iso_std(gate, op_basis)
    ) for gate in mdl.operations.values()], 'd'))


def _spam_penalty(mdl, prefactor, op_basis):
    """
    Helper function - CPTP penalty: (sum of tracenorms of gates),
    which in least squares optimization means returning an array
    of the sqrt(tracenorm) of each gate.

    Returns
    -------
    numpy array
        a (real) 1D array of length len(mdl.operations).
    """
    from .. import tools as _tools
    return prefactor * (_np.sqrt(
        _np.array([
            _tools.tracenorm(
                _tools.vec_to_stdmx(prepvec.todense(), op_basis)
            ) for prepvec in mdl.preps.values()
        ] + [
            _tools.tracenorm(
                _tools.vec_to_stdmx(mdl.povms[plbl][elbl].todense(), op_basis)
            ) for plbl in mdl.povms for elbl in mdl.povms[plbl]], 'd')
    ))


def _cptp_penalty_jac_fill(cp_penalty_vec_grad_to_fill, mdl, prefactor, op_basis):
    """
    Helper function - jacobian of CPTP penalty (sum of tracenorms of gates)
    Returns a (real) array of shape (len(mdl.operations), n_params).
    """
    from .. import tools as _tools

    # d( sqrt(|chi|_Tr) ) = (0.5 / sqrt(|chi|_Tr)) * d( |chi|_Tr )
    for i, gate in enumerate(mdl.operations.values()):
        nparams = gate.num_params()

        #get sgn(chi-matrix) == d(|chi|_Tr)/dchi in std basis
        # so sgnchi == d(|chi_std|_Tr)/dchi_std
        chi = _tools.fast_jamiolkowski_iso_std(gate, op_basis)
        assert(_np.linalg.norm(chi - chi.T.conjugate()) < 1e-4), \
            "chi should be Hermitian!"

        # Alt#1 way to compute sgnchi (evals) - works equally well to svd below
        #evals,U = _np.linalg.eig(chi)
        #sgnevals = [ ev/abs(ev) if (abs(ev) > 1e-7) else 0.0 for ev in evals]
        #sgnchi = _np.dot(U,_np.dot(_np.diag(sgnevals),_np.linalg.inv(U)))

        # Alt#2 way to compute sgnchi (sqrtm) - DOESN'T work well; sgnchi NOT very hermitian!
        #sgnchi = _np.dot(chi, _np.linalg.inv(
        #        _spl.sqrtm(_np.matrix(_np.dot(chi.T.conjugate(),chi)))))

        sgnchi = _tools.matrix_sign(chi)
        assert(_np.linalg.norm(sgnchi - sgnchi.T.conjugate()) < 1e-4), \
            "sgnchi should be Hermitian!"

        # get d(gate)/dp in op_basis [shape == (nP,dim,dim)]
        #OLD: dGdp = mdl.dproduct((gl,)) but wasteful
        dgate_dp = gate.deriv_wrt_params()  # shape (dim**2, nP)
        dgate_dp = _np.swapaxes(dgate_dp, 0, 1)  # shape (nP, dim**2, )
        dgate_dp.shape = (nparams, mdl.dim, mdl.dim)

        # Let M be the "shuffle" operation performed by fast_jamiolkowski_iso_std
        # which maps a gate onto the choi-jamiolkowsky "basis" (i.e. performs that C-J
        # transform).  This shuffle op commutes with the derivative, so that
        # dchi_std/dp := d(M(G))/dp = M(dG/dp), which we call "MdGdp_std" (the choi
        # mapping of dGdp in the std basis)
        m_dgate_dp_std = _np.empty((nparams, mdl.dim, mdl.dim), 'complex')
        for p in range(nparams):  # p indexes param
            m_dgate_dp_std[p] = _tools.fast_jamiolkowski_iso_std(dgate_dp[p], op_basis)  # now "M(dGdp_std)"
            assert(_np.linalg.norm(m_dgate_dp_std[p] - m_dgate_dp_std[p].T.conjugate()) < 1e-8)  # check hermitian

        m_dgate_dp_std = _np.conjugate(m_dgate_dp_std)  # so element-wise multiply
        # of complex number (einsum below) results in separately adding
        # Re and Im parts (also see NOTE in spam_penalty_jac_fill below)

        #contract to get (note contract along both mx indices b/c treat like a
        # mx basis): d(|chi_std|_Tr)/dp = d(|chi_std|_Tr)/dchi_std * dchi_std/dp
        #v =  _np.einsum("ij,aij->a",sgnchi,MdGdp_std)
        v = _np.tensordot(sgnchi, m_dgate_dp_std, ((0, 1), (1, 2)))
        v *= prefactor * (0.5 / _np.sqrt(_tools.tracenorm(chi)))  # add 0.5/|chi|_Tr factor
        assert(_np.linalg.norm(v.imag) < 1e-4)
        cp_penalty_vec_grad_to_fill[i, :] = 0.0
        cp_penalty_vec_grad_to_fill[i, gate.gpindices] = v.real  # indexing w/array OR
        #slice works as expected in this case
        chi = sgnchi = dgate_dp = m_dgate_dp_std = v = None  # free mem

    return len(mdl.operations)  # the number of leading-dim indicies we filled in


def _spam_penalty_jac_fill(spam_penalty_vec_grad_to_fill, mdl, prefactor, op_basis):
    """
    Helper function - jacobian of CPTP penalty (sum of tracenorms of gates)
    Returns a (real) array of shape ( _spam_penalty_size(mdl), n_params).
    """
    from .. import tools as _tools
    basis_mxs = op_basis.elements  # shape [mdl.dim, dmDim, dmDim]
    ddenmx_dv = demx_dv = basis_mxs.conjugate()  # b/c denMx = sum( spamvec[i] * Bmx[i] ) and "V" == spamvec
    #NOTE: conjugate() above is because ddenMxdV and dEMxdV will get *elementwise*
    # multiplied (einsum below) by another complex matrix (sgndm or sgnE) and summed
    # in order to gather the different components of the total derivative of the trace-norm
    # wrt some spam-vector change dV.  If left un-conjugated, we'd get A*B + A.C*B.C (just
    # taking the (i,j) and (j,i) elements of the sum, say) which would give us
    # 2*Re(A*B) = A.r*B.r - B.i*A.i when we *want* (b/c Re and Im parts are thought of as
    # separate, independent degrees of freedom) A.r*B.r + A.i*B.i = 2*Re(A*B.C) -- so
    # we need to conjugate the "B" matrix, which is ddenMxdV or dEMxdV below.

    # d( sqrt(|denMx|_Tr) ) = (0.5 / sqrt(|denMx|_Tr)) * d( |denMx|_Tr )
    for i, prepvec in enumerate(mdl.preps.values()):
        nparams = prepvec.num_params()

        #get sgn(denMx) == d(|denMx|_Tr)/d(denMx) in std basis
        # dmDim = denMx.shape[0]
        denmx = _tools.vec_to_stdmx(prepvec, op_basis)
        assert(_np.linalg.norm(denmx - denmx.T.conjugate()) < 1e-4), \
            "denMx should be Hermitian!"

        sgndm = _tools.matrix_sign(denmx)
        assert(_np.linalg.norm(sgndm - sgndm.T.conjugate()) < 1e-4), \
            "sgndm should be Hermitian!"

        # get d(prepvec)/dp in op_basis [shape == (nP,dim)]
        dv_dp = prepvec.deriv_wrt_params()  # shape (dim, nP)
        assert(dv_dp.shape == (mdl.dim, nparams))

        # denMx = sum( spamvec[i] * Bmx[i] )

        #contract to get (note contrnact along both mx indices b/c treat like a mx basis):
        # d(|denMx|_Tr)/dp = d(|denMx|_Tr)/d(denMx) * d(denMx)/d(spamvec) * d(spamvec)/dp
        # [dmDim,dmDim] * [mdl.dim, dmDim,dmDim] * [mdl.dim, nP]
        #v =  _np.einsum("ij,aij,ab->b",sgndm,ddenMxdV,dVdp)
        v = _np.tensordot(_np.tensordot(sgndm, ddenmx_dv, ((0, 1), (1, 2))), dv_dp, (0, 0))
        v *= prefactor * (0.5 / _np.sqrt(_tools.tracenorm(denmx)))  # add 0.5/|denMx|_Tr factor
        assert(_np.linalg.norm(v.imag) < 1e-4)
        spam_penalty_vec_grad_to_fill[i, :] = 0.0
        spam_penalty_vec_grad_to_fill[i, prepvec.gpindices] = v.real  # slice or array index works!
        denmx = sgndm = dv_dp = v = None  # free mem

    #Compute derivatives for effect terms
    i = len(mdl.preps)
    for povmlbl, povm in mdl.povms.items():
        #Simplify effects of povm so we can take their derivatives
        # directly wrt parent Model parameters
        for _, effectvec in povm.simplify_effects(povmlbl).items():
            nparams = effectvec.num_params()

            #get sgn(EMx) == d(|EMx|_Tr)/d(EMx) in std basis
            emx = _tools.vec_to_stdmx(effectvec, op_basis)
            # dmDim = EMx.shape[0]
            assert(_np.linalg.norm(emx - emx.T.conjugate()) < 1e-4), \
                "EMx should be Hermitian!"

            sgn_e = _tools.matrix_sign(emx)
            assert(_np.linalg.norm(sgn_e - sgn_e.T.conjugate()) < 1e-4), \
                "sgnE should be Hermitian!"

            # get d(prepvec)/dp in op_basis [shape == (nP,dim)]
            dv_dp = effectvec.deriv_wrt_params()  # shape (dim, nP)
            assert(dv_dp.shape == (mdl.dim, nparams))

            # emx = sum( spamvec[i] * basis_mx[i] )

            #contract to get (note contract along both mx indices b/c treat like a mx basis):
            # d(|EMx|_Tr)/dp = d(|EMx|_Tr)/d(EMx) * d(EMx)/d(spamvec) * d(spamvec)/dp
            # [dmDim,dmDim] * [mdl.dim, dmDim,dmDim] * [mdl.dim, nP]
            #v =  _np.einsum("ij,aij,ab->b",sgnE,dEMxdV,dVdp)
            v = _np.tensordot(_np.tensordot(sgn_e, demx_dv, ((0, 1), (1, 2))), dv_dp, (0, 0))
            v *= prefactor * (0.5 / _np.sqrt(_tools.tracenorm(emx)))  # add 0.5/|EMx|_Tr factor
            assert(_np.linalg.norm(v.imag) < 1e-4)

            spam_penalty_vec_grad_to_fill[i, :] = 0.0
            spam_penalty_vec_grad_to_fill[i, effectvec.gpindices] = v.real
            i += 1

            sgn_e = dv_dp = v = None  # free mem

    #return the number of leading-dim indicies we filled in
    return len(mdl.preps) + sum([len(povm) for povm in mdl.povms.values()])


class LogLWildcardFunction(ObjectiveFunction):

    def __init__(self, logl_objective_fn, base_pt, wildcard):
        from .. import tools as _tools

        self.logl_objfn = logl_objective_fn
        self.basept = base_pt
        self.wildcard_budget = wildcard
        self.wildcard_budget_precomp = wildcard.get_precomp_for_circuits(self.logl_objfn.circuits_to_use)

        #assumes self.logl_objfn.fn(...) was called to initialize the members of self.logl_objfn
        self.probs = self.logl_objfn.probs.copy()

    #def _default_evalpt(self):
    #    """The default point to evaluate functions at """
    #    return self.wildcard_budget.to_vector()

    def fn(self, wvec=None):
        return sum(self.terms(wvec))

    def terms(self, wvec=None):
        return self.lsvec(wvec)**2

    def lsvec(self, w_vec=None):
        tm = _time.time()
        if w_vec is not None: self.wildcard_budget.from_vector(w_vec)
        self.wildcard_budget.update_probs(self.probs,
                                          self.logl_objfn.probs,
                                          self.logl_objfn.freqs,
                                          self.logl_objfn.circuits_to_use,
                                          self.logl_objfn.lookup,
                                          self.wildcard_budget_precomp)

        return self.logl_objfn.lsvec_from_probs(tm)

    def dlsvec(self, w_vec):
        raise NotImplementedError("No jacobian yet")
