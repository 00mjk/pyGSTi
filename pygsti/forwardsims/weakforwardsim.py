"""
Defines the WeakForwardSimulator calculator class
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************
import numpy as _np

from .forwardsim import ForwardSimulator as _ForwardSimulator
from ..models import labeldicts as _ld


class WeakForwardSimulator(_ForwardSimulator):
    """
    A calculator of circuit outcome probabilities from a "weak" forward simulator
    (i.e. probabilites taken as average frequencies over a number of "shots").

    Due to their ability to only sample outcome probabilities, WeakForwardSimulators
    rely heavily on implementing the _compute_sparse_circuit_outcome_probabilities
    function of ForwardSimulators.
    """

    def __init__(self, shots, model=None):
        """
        Construct a new WeakForwardSimulator object.

        Parameters
        ----------
        shots: int
            Number of times to run each circuit to obtain an approximate probability
        model : Model
            Optional parent Model to be stored with the Simulator
        """
        self.shots = shots
        super().__init__(model)

    def _compute_circuit_outcome_for_shot(self, spc_circuit, resource_alloc, time=None):
        """Compute outcome for a single shot of a circuit.

        Parameters
        ----------
        spc_circuit : SeparatePOVMCircuit
            A tuple-like object of *simplified* gates (e.g. may include
            instrument elements like 'Imyinst_0') generated by
            Circuit.expand_instruments_and_separate_povm()

        resource_alloc: ResourceAlloc
            Currently not used

        time : float, optional
            The *start* time at which `circuit` is evaluated.
        
        Returns
        -------
        outcome_label: tuple
            An outcome label for the single shot sampled
        """
        raise NotImplementedError("WeakForwardSimulator-derived classes should implement this!")
    
    def _compute_sparse_circuit_outcome_probabilities(self, circuit, resource_alloc, time=None):
        probs = _ld.OutcomeLabelDict()

        # TODO: For parallelization, block over this for loop
        for _ in range(self.shots):
            outcome = self._compute_circuit_outcome_for_shot(circuit, resource_alloc, time)
            if outcome in probs:
                probs[outcome] += 1.0 / self.shots
            else:
                probs[outcome] = 1.0 / self.shots
        
        return probs

    # For WeakForwardSimulator, provide "bulk" interface based on the sparse interface
    # This will be highly inefficient for large numbers of qubits due to the dense storage of outcome probabilities
    # Anything expanding out all effects or creating a COPALayout will be expensive
    def _compute_circuit_outcome_probabilities(self, array_to_fill, circuit, outcomes, resource_alloc, time=None):
        # TODO: Other forward sims have expand_outcomes here, check how to fit that in
        sparse_probs = self._compute_sparse_circuit_outcome_probabilities(circuit, resource_alloc, time)

        for i, outcome in enumerate(outcomes):
            array_to_fill[i] = sparse_probs[outcome]



