#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************
"""
Variables for working with the a model containing X(pi/2) and Z(pi/2) gates.
"""

import sys as _sys

from ...circuits import circuitconstruction as _strc
from ...models import modelconstruction as _setc
from .. import stdtarget as _stdtarget

description = "X(pi/2) and Z(pi/2) gates"

gates = ['Gx', 'Gz']
prepStrs = _strc.to_circuits([(),
                               ('Gx',),
                               ('Gx', 'Gz'),
                               ('Gx', 'Gx'),
                               ('Gx', 'Gx', 'Gx'),
                               ('Gx', 'Gz', 'Gx', 'Gx')], line_labels=('*',))  # for 1Q MUB

effectStrs = _strc.to_circuits([(),
                                 ('Gx',),
                                 ('Gz', 'Gx'),
                                 ('Gx', 'Gx'),
                                 ('Gx', 'Gx', 'Gx'),
                                 ('Gx', 'Gx', 'Gz', 'Gx')], line_labels=('*',))

germs = _strc.to_circuits(
    [('Gx',),
     ('Gz',),
     ('Gx', 'Gz',),
     ('Gx', 'Gx', 'Gz'),
     ('Gx', 'Gz', 'Gz'),
     ('Gx', 'Gx', 'Gz', 'Gx', 'Gz', 'Gz',)], line_labels=('*',))
germs_lite = germs[0:4]


germs = _strc.to_circuits([('Gx',), ('Gz',), ('Gz', 'Gx', 'Gx'), ('Gz', 'Gz', 'Gx')], line_labels=('*',))

#Construct a target model:  X(pi/2), Z(pi/2)
_target_model = _setc.create_explicit_model_from_expressions([('Q0',)], ['Gx', 'Gz'],
                                                             ["X(pi/2,Q0)", "Z(pi/2,Q0)"])

_gscache = {("full", "auto"): _target_model}


def processor_spec():
    from pygsti.processors import QubitProcessorSpec as _QubitProcessorSpec
    static_target_model = target_model('static')
    return _QubitProcessorSpec.from_explicit_model(static_target_model, None)


def target_model(parameterization_type="full", sim_type="auto"):
    """
    Returns a copy of the target model in the given parameterization.

    Parameters
    ----------
    parameterization_type : {"TP", "CPTP", "H+S", "S", ... }
        The gate and SPAM vector parameterization type. See
        :function:`Model.set_all_parameterizations` for all allowed values.

    sim_type : {"auto", "matrix", "map", "termorder:X" }
        The simulator type to be used for model calculations (leave as
        "auto" if you're not sure what this is).

    Returns
    -------
    Model
    """
    return _stdtarget._copy_target(_sys.modules[__name__], parameterization_type,
                                   sim_type, _gscache)


global_fidPairs = [
    (0, 1), (1, 2), (4, 3), (4, 4)]

pergerm_fidPairsDict = {
    ('Gx',): [
        (1, 1), (3, 4), (4, 2), (5, 5)],
    ('Gz',): [
        (0, 0), (2, 3), (5, 2), (5, 4)],
    ('Gz', 'Gz', 'Gx'): [
        (0, 3), (1, 2), (2, 5), (3, 1), (3, 3), (5, 3)],
    ('Gz', 'Gx', 'Gx'): [
        (0, 3), (0, 4), (1, 0), (1, 4), (2, 1), (4, 5)],
}


global_fidPairs_lite = [
    (0, 1), (1, 2), (4, 3), (4, 4)]

pergerm_fidPairsDict_lite = {
    ('Gx',): [
        (1, 1), (3, 4), (4, 2), (5, 5)],
    ('Gz',): [
        (0, 0), (2, 3), (5, 2), (5, 4)],
    ('Gx', 'Gz'): [
        (0, 3), (3, 2), (4, 0), (5, 3)],
    ('Gx', 'Gx', 'Gz'): [
        (0, 0), (0, 2), (1, 1), (4, 0), (4, 2), (5, 5)],
}
