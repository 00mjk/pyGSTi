""" Chi-squared and related functions """
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import numpy as _np
from . import listtools as _lt
from . import slicetools as _slct
from ..objects import objectivefns as _objfns


def chi2(model, dataset, circuit_list=None,
         minProbClipForWeighting=1e-4, clipTo=(-10000, 10000),
         memLimit=None, opLabelAliases=None,
         cache=None, comm=None):
    """
    Computes the total (aggregate) chi^2 for a set of circuits.

    The chi^2 test statistic obtained by summing up the
    contributions of a given set of operation sequences or all
    the circuits available in a dataset.  For the gradient or
    Hessian, see the :function:`chi2_jacobian` and
    :function:`chi2_hessian` functions.

    Parameters
    ----------
    model : Model
        The model used to specify the probabilities and SPAM labels

    dataset : DataSet
        The data used to specify frequencies and counts

    circuit_list : list of Circuits or tuples, optional
        List of operation sequences whose terms will be included in chi^2 sum.
        Default value (None) means "all strings in dataset".

    minProbClipForWeighting : float, optional
        defines the clipping interval for the statistical weight (see chi2fn).

    clipTo : 2-tuple, optional
        (min,max) to clip probabilities to within Model probability
        computation routines (see Model.bulk_fill_probs)

    memLimit : int, optional
        A rough memory limit in bytes which restricts the amount of intermediate
        values that are computed and stored.

    opLabelAliases : dictionary, optional
        Dictionary whose keys are operation label "aliases" and whose values are tuples
        corresponding to what that operation label should be expanded into before querying
        the dataset. Defaults to the empty dictionary (no aliases defined)
        e.g. opLabelAliases['Gx^3'] = ('Gx','Gx','Gx')

    cache : ComputationCache, optional
        A cache object used to hold results for the same `model` and `dataset` and `circuit_list`.

    comm : mpi4py.MPI.Comm, optional
        When not None, an MPI communicator for distributing the computation
        across multiple processors.

    Returns
    -------
    chi2 : float
        chi^2 value, equal to the sum of chi^2 terms from all specified operation sequences
    """
    return _objfns.objfn(_objfns.Chi2Function, model, dataset, circuit_list, None,
                         {'minProbClipForWeighting': minProbClipForWeighting,
                          'probClipInterval': clipTo},
                         memLimit, opLabelAliases, cache, comm).fn()


def chi2_per_circuit(model, dataset, circuit_list=None,
                     minProbClipForWeighting=1e-4, clipTo=(-10000, 10000),
                     memLimit=None, opLabelAliases=None,
                     cache=None, comm=None):
    """
    Computes the per-circuit chi^2 contributions for a set of cirucits.

    This function returns the same value as :func:`chi2` except the
    contributions from different circuits are not summed but
    returned as an array (the contributions of all the outcomes of a
    given cirucit *are* summed together).

    Parameters
    ----------
    This function takes the same arguments as :func:`chi2`.

    Returns
    -------
    chi2 : numpy.ndarray
        Array of length either `len(circuit_list)` or `len(dataset.keys())`.
        Values are the chi2 contributions of the corresponding gate
        string aggregated over outcomes.
    """
    return _objfns.objfn(_objfns.Chi2Function, model, dataset, circuit_list, None,
                         {'minProbClipForWeighting': minProbClipForWeighting,
                          'probClipInterval': clipTo},
                         memLimit, opLabelAliases, cache, comm).percircuit_fn()


def chi2_jacobian(model, dataset, circuit_list=None,
                  minProbClipForWeighting=1e-4, clipTo=(-10000, 10000),
                  memLimit=None, opLabelAliases=None,
                  cache=None, comm=None):
    """
    Compute the gradient of the chi^2 function computed by :function:`chi2`.

    The returned value holds the derivatives of the chi^2 function with
    respect to `model`'s parameters.

    Parameters
    ----------
    This function takes the same arguments as :func:`chi2`.

    Returns
    -------
    numpy array
        The gradient vector of length `model.num_params()`, the number of model parameters.
    """
    return _objfns.objfn(_objfns.Chi2Function, model, dataset, circuit_list, None,
                         {'minProbClipForWeighting': minProbClipForWeighting,
                          'probClipInterval': clipTo},
                         memLimit, opLabelAliases, cache, comm).jfn()


def chi2_hessian(model, dataset, circuit_list=None,
                 minProbClipForWeighting=1e-4, clipTo=(-10000, 10000),
                 memLimit=None, opLabelAliases=None,
                 cache=None, comm=None, approximate=False):
    """
    Compute the Hessian matrix of the :func:`chi2` function.

    Parameters
    ----------
    This function takes the same arguments as :func:`chi2`, with the addition of:

    approximateHessian : bool, optional
        Whether, an *approximate* version of the Hessian should be returned.
        This approximation neglects terms proportional to the Hessian of the
        probabilities w.r.t. the model parameters (which can take a long time
        to compute).  See `logl_hessian` for details on the analogous approximation
        for the log-likelihood Hessian.

    Returns
    -------
    numpy array
        The Hessian matrix of shape (nModelParams, nModelParams), where
        nModelParams = `model.num_params()`.
    """
    obj = _objfns.objfn(_objfns.Chi2Function, model, dataset, circuit_list, None,
                        {'minProbClipForWeighting': minProbClipForWeighting,
                         'probClipInterval': clipTo},
                        memLimit, opLabelAliases, cache, comm, enable_hessian=not approximate)
    return obj.approx_hfn() if approximate else obj.hfn()


def chialpha(alpha, model, dataset, circuit_list=None,
             pfratio_stitchpt=1e-2, pfratio_derivpt=1e-2, clipTo=(-10000, 10000),
             radius=None, memLimit=None, opLabelAliases=None,
             cache=None, comm=None):
    """
    TODO: docstring
    """
    return _objfns.objfn(_objfns.ChiAlphaFunction, model, dataset, circuit_list, None,
                         {'pfratio_stitchpt': pfratio_stitchpt,
                          'pfratio_derivpt': pfratio_derivpt,
                          'probClipInterval': clipTo,
                          'radius': radius},
                         memLimit, opLabelAliases, cache, comm, alpha=alpha).fn()


def chialpha_percircuit(alpha, model, dataset, circuit_list=None,
                        pfratio_stitchpt=1e-2, pfratio_derivpt=1e-2, clipTo=(-10000, 10000),
                        radius=None, memLimit=None, opLabelAliases=None,
                        cache=None, comm=None):
    """
    TODO: docstring
    """
    return _objfns.objfn(_objfns.ChiAlphaFunction, model, dataset, circuit_list, None,
                         {'pfratio_stitchpt': pfratio_stitchpt,
                          'pfratio_derivpt': pfratio_derivpt,
                          'probClipInterval': clipTo,
                          'radius': radius},
                         memLimit, opLabelAliases, cache, comm, alpha=alpha).percircuit_fn()


def chi2fn_2outcome(N, p, f, minProbClipForWeighting=1e-4):
    """
    Computes chi^2 for a 2-outcome measurement.

    The chi-squared function for a 2-outcome measurement using
    a clipped probability for the statistical weighting.

    Parameters
    ----------
    N : float or numpy array
        Number of samples.

    p : float or numpy array
        Probability of 1st outcome (typically computed).

    f : float or numpy array
        Frequency of 1st outcome (typically observed).

    minProbClipForWeighting : float, optional
        Defines clipping interval (see return value).

    Returns
    -------
    float or numpy array
        N(p-f)^2 / (cp(1-cp)),
        where cp is the value of p clipped to the interval
        (minProbClipForWeighting, 1-minProbClipForWeighting)
    """
    cp = _np.clip(p, minProbClipForWeighting, 1 - minProbClipForWeighting)
    return N * (p - f)**2 / (cp * (1 - cp))


def chi2fn_2outcome_wfreqs(N, p, f):
    """
    Computes chi^2 for a 2-outcome measurement using frequency-weighting.

    The chi-squared function for a 2-outcome measurement using
    the observed frequency in the statistical weight.

    Parameters
    ----------
    N : float or numpy array
        Number of samples.

    p : float or numpy array
        Probability of 1st outcome (typically computed).

    f : float or numpy array
        Frequency of 1st outcome (typically observed).

    Returns
    -------
    float or numpy array
        N(p-f)^2 / (f*(1-f*)),
        where f* = (f*N+1)/N+2 is the frequency value used in the
        statistical weighting (prevents divide by zero errors)
    """
    f1 = (f * N + 1) / (N + 2)
    return N * (p - f)**2 / (f1 * (1 - f1))


def chi2fn(N, p, f, minProbClipForWeighting=1e-4):
    """
    Computes the chi^2 term corresponding to a single outcome.

    The chi-squared term for a single outcome of a multi-outcome
    measurement using a clipped probability for the statistical
    weighting.

    Parameters
    ----------
    N : float or numpy array
        Number of samples.

    p : float or numpy array
        Probability of 1st outcome (typically computed).

    f : float or numpy array
        Frequency of 1st outcome (typically observed).

    minProbClipForWeighting : float, optional
        Defines clipping interval (see return value).

    Returns
    -------
    float or numpy array
        N(p-f)^2 / cp ,
        where cp is the value of p clipped to the interval
        (minProbClipForWeighting, 1-minProbClipForWeighting)
    """
    cp = _np.clip(p, minProbClipForWeighting, None)
    return N * (p - f)**2 / cp


def chi2fn_wfreqs(N, p, f, minProbClipForWeighting=1e-4):
    """
    Computes the frequency-weighed chi^2 term corresponding to a single outcome.

    The chi-squared term for a single outcome of a multi-outcome
    measurement using the observed frequency in the statistical weight.

    Parameters
    ----------
    N : float or numpy array
        Number of samples.

    p : float or numpy array
        Probability of 1st outcome (typically computed).

    f : float or numpy array
        Frequency of 1st outcome (typically observed).

    minProbClipForWeighting : float, optional
        unused but present to keep the same function
        signature as chi2fn.

    Returns
    -------
    float or numpy array
        N(p-f)^2 / f*,
        where f* = (f*N+1)/N+2 is the frequency value used in the
        statistical weighting (prevents divide by zero errors)
    """
    f1 = (f * N + 1) / (N + 2)
    return N * (p - f)**2 / f1
