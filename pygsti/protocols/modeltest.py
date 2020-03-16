""" ModelTest Protocol objects """
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import time as _time
import os as _os
import numpy as _np
import pickle as _pickle
import collections as _collections
import warnings as _warnings
import scipy.optimize as _spo
from scipy.stats import chi2 as _chi2

from . import protocol as _proto
from .. import objects as _objs
from .. import algorithms as _alg
from .. import construction as _construction
from .. import io as _io
from .. import tools as _tools

from ..objects.estimate import Estimate as _Estimate
from ..objects import wildcardbudget as _wild
from ..objects.profiler import DummyProfiler as _DummyProfiler
from ..objects import objectivefns as _objfns


class ModelTest(_proto.Protocol):
    """A protocol that tests how well a model agrees with a given set of data."""

    @classmethod
    def create_builder(cls, obj):
        builder_cls = _objfns.ObjectiveFunctionBuilder
        if isinstance(obj, builder_cls): return obj
        elif obj is None: return builder_cls.simple()
        elif isinstance(obj, dict): return builder_cls.simple(**obj)
        elif isinstance(obj, (list, tuple)): return builder_cls(*obj)
        else: raise ValueError("Cannot build a objective-fn builder from '%s'" % str(type(obj)))

    def __init__(self, model_to_test, target_model=None, gaugeopt_suite=None,
                 gaugeopt_target=None, objfn_builder=None, badfit_options=None,
                 set_trivial_gauge_group=True, verbosity=2, name=None):

        if set_trivial_gauge_group:
            model_to_test = model_to_test.copy()
            model_to_test.default_gauge_group = _objs.TrivialGaugeGroup(model_to_test.dim)  # so no gauge opt is done

        super().__init__(name)
        self.model_to_test = model_to_test
        self.target_model = target_model
        self.gaugeopt_suite = gaugeopt_suite
        self.gaugeopt_target = gaugeopt_target
        self.badfit_options = badfit_options
        self.verbosity = verbosity

        self.objfn_builders = [self.create_builder(objfn_builder)]

        self.auxfile_types['model_to_test'] = 'pickle'
        self.auxfile_types['target_model'] = 'pickle'
        self.auxfile_types['gaugeopt_suite'] = 'pickle'  # TODO - better later? - json?
        self.auxfile_types['gaugeopt_target'] = 'pickle'  # TODO - better later? - json?
        self.auxfile_types['objfn_builders'] = 'pickle'

        #Advanced options that could be changed by users who know what they're doing
        self.profile = 1
        self.oplabel_aliases = None
        self.circuit_weights = None
        self.unreliable_ops = ('Gcnot', 'Gcphase', 'Gms', 'Gcn', 'Gcx', 'Gcz')

    #def run_using_germs_and_fiducials(self, model, dataset, target_model, prep_fiducials,
    #                                  meas_fiducials, germs, maxLengths):
    #    from .gst import StandardGSTDesign as _StandardGSTDesign
    #    design = _StandardGSTDesign(target_model, prep_fiducials, meas_fiducials, germs, maxLengths)
    #    return self.run(_proto.ProtocolData(design, dataset))

    def run(self, data, memlimit=None, comm=None):
        the_model = self.model_to_test

        if self.target_model is not None:
            target_model = self.target_model
        elif hasattr(data.edesign, 'target_model'):
            target_model = data.edesign.target_model
        else:
            target_model = None  # target model isn't necessary

        #Create profiler
        profile = self.profile
        if profile == 0: profiler = _DummyProfiler()
        elif profile == 1: profiler = _objs.Profiler(comm, False)
        elif profile == 2: profiler = _objs.Profiler(comm, True)
        else: raise ValueError("Invalid value for 'profile' argument (%s)" % profile)

        printer = _objs.VerbosityPrinter.build_printer(self.verbosity, comm)
        resource_alloc = _objfns.ResourceAllocation(comm, memlimit, profiler, distributeMethod='default')

        try:  # take structs if available
            circuit_lists_or_structs = data.edesign.circuit_structs
            aliases = circuit_lists_or_structs[-1].aliases
        except:
            aliases = None
            try:  # take multiple lists if available
                circuit_lists_or_structs = data.edesign.circuit_lists
            except:  # otherwise just use base list of all circuits
                circuit_lists_or_structs = [data.edesign.all_circuits_needing_data]

        ds = data.dataset

        if self.oplabel_aliases:  # override any other aliases with ones specifically given
            aliases = self.oplabel_aliases

        bulk_circuit_lists = [_objfns.BulkCircuitList(lst, aliases, self.circuit_weights)
                              for lst in circuit_lists_or_structs]
        objfn_vals = []
        chi2d_vals = []
        assert(len(self.objfn_builders) == 1), "Only support for a single objective function so far."
        for circuit_list in bulk_circuit_lists:
            cache = _objfns.ComputationCache()  # store objects for this particular model, dataset, and circuit list
            objective = self.objfn_builders[0].build(the_model, ds, circuit_list, resource_alloc, cache, printer)
            f = objective.fn(the_model.to_vector())
            objfn_vals.append(f)
            chi2d_vals.append(objective.get_chi2k_distributed_qty(f))

        parameters = _collections.OrderedDict()
        parameters['raw_objective_values'] = objfn_vals
        parameters['model_test_values'] = chi2d_vals

        from .gst import _add_gaugeopt_and_badfit
        from .gst import ModelEstimateResults as _ModelEstimateResults

        ret = _ModelEstimateResults(data, self)
        models = {'final iteration estimate': the_model, 'iteration estimates': [the_model] * len(bulk_circuit_lists)}
        # TODO: come up with better key names? and must we have iteration_estimates?
        if target_model is not None:
            models['target'] = target_model
        ret.add_estimate(_Estimate(ret, models, parameters), estimate_key=self.name)
        return _add_gaugeopt_and_badfit(ret, self.name, the_model, target_model, self.gaugeopt_suite,
                                        self.gaugeopt_target, self.unreliable_ops, self.badfit_options,
                                        self.objfn_builders[-1], None, resource_alloc, printer)
