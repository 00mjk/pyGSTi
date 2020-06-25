"""
Circuit list for bulk computation
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************
import uuid as _uuid

from .circuit import Circuit as _Circuit
from ..tools import listtools as _lt


class BulkCircuitList(list):
    """
    A list of :class:`Circuit` objects and associated metadata.

    Parameters
    ----------
    circuits : list
        The list of circuits that constitutes the primary data held by this object.

    op_label_aliases : dict, optional
        Dictionary of circuit meta-data whose keys are operation label "aliases"
        and whose values are circuits corresponding to what that operation label
        should be expanded into before querying the dataset.  Defaults to the
        empty dictionary (no aliases defined).  e.g. op_label_aliases['Gx^3'] =
        pygsti.obj.Circuit(['Gx','Gx','Gx'])

    circuit_weights : numpy.ndarray, optional
        If not None, an array of per-circuit weights (of length equal to the number of
        circuits) that are typically used to multiply the counts extracted for each circuit.

    name : str, optional
        An optional name for this list, used for status messages.
    """

    @classmethod
    def cast(self, circuits):
        """
        Convert (if needed) an object into a :class:`BulkCircuitList`.

        Parameters
        ----------
        circuits : list or BulkCircuitList
            The object to convert.

        Returns
        -------
        BulkCircuitList
        """
        if isinstance(circuits, BulkCircuitList):
            return circuits
        return BulkCircuitList(circuits)

    def __init__(self, circuits, op_label_aliases=None, circuit_weights=None, name=None):
        """
        Create a BulkCircuitList.

        Parameters
        ----------
        circuits : list
            The list of circuits that constitutes the primary data held by this object.

        op_label_aliases : dict, optional
            Dictionary of circuit meta-data whose keys are operation label "aliases"
            and whose values are circuits corresponding to what that operation label
            should be expanded into before querying the dataset.  Defaults to the
            empty dictionary (no aliases defined).  e.g. op_label_aliases['Gx^3'] =
            pygsti.obj.Circuit(['Gx','Gx','Gx'])

        circuit_weights : numpy.ndarray, optional
            If not None, an array of per-circuit weights (of length equal to the number of
            circuits) that are typically used to multiply the counts extracted for each circuit.

        name : str, optional
            An optional name for this list, used for status messages.
        """
        super().__init__(map(_Circuit.cast, circuits))
        self.op_label_aliases = op_label_aliases
        self.circuit_weights = circuit_weights
        self.name = name  # an optional name for this circuit list
        self.uuid = _uuid.uuid4()  # like a persistent id(), useful for peristent (file) caches

    def apply_aliases(self):
        """
        Applies any operation-label aliases to this circuit list.

        Returns
        -------
        list
            A list of :class:`Circuit`s.
        """
        return _lt.apply_aliases_to_circuits(self[:], self.op_label_aliases)

    def __hash__(self):
        if self.uuid is not None:
            return hash(self.uuid)
        else:
            raise TypeError('Use digest hash')

    def __setstate__(self, state_dict):
        self.__dict__.update(state_dict)
        if 'uuid' not in state_dict:  # backward compatibility
            self.uuid = _uuid.uuid4()  # create a new uuid
