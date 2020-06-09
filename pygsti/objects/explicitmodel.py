"""
Defines the ExplicitOpModel class and supporting functionality.
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
import scipy as _scipy
import itertools as _itertools
import collections as _collections
import warnings as _warnings
import time as _time
import uuid as _uuid
import bisect as _bisect
import copy as _copy

from ..tools import matrixtools as _mt
from ..tools import optools as _gt
from ..tools import slicetools as _slct
from ..tools import likelihoodfns as _lf
from ..tools import jamiolkowski as _jt
from ..tools import basistools as _bt
from ..tools import listtools as _lt
from ..tools import symplectic as _symp

from . import model as _mdl
from . import modelmember as _gm
from . import circuit as _cir
from . import operation as _op
from . import spamvec as _sv
from . import povm as _povm
from . import instrument as _instrument
from . import labeldicts as _ld
from . import gaugegroup as _gg
from . import matrixforwardsim as _matrixfwdsim
from . import mapforwardsim as _mapfwdsim
from . import termforwardsim as _termfwdsim
from . import explicitcalc as _explicitcalc

from .verbosityprinter import VerbosityPrinter as _VerbosityPrinter
from .basis import BuiltinBasis as _BuiltinBasis, DirectSumBasis as _DirectSumBasis
from .label import Label as _Label, CircuitLabel as _CircuitLabel
from .layerrules import LayerRules as _LayerRules


class ExplicitOpModel(_mdl.OpModel):
    """
    Encapsulates a set of gate, state preparation, and POVM effect operations.

    An ExplictOpModel stores a set of labeled LinearOperator objects and
    provides dictionary-like access to their matrices.  State preparation
    and POVM effect operations are represented as column vectors.

    Parameters
    ----------
    state_space_labels : StateSpaceLabels or list or tuple
        The decomposition (with labels) of (pure) state-space this model
        acts upon.  Regardless of whether the model contains operators or
        superoperators, this argument describes the Hilbert space dimension
        and imposed structure.  If a list or tuple is given, it must be
        of a from that can be passed to `StateSpaceLabels.__init__`.

    basis : {"auto","pp","gm","qt","std","sv"} or Basis
        The basis used for the state space by dense operator representations.

    default_param : {"full", "TP", "CPTP", etc.}, optional
        Specifies the default gate and SPAM vector parameterization type.
        Can be any value allowed by :method:`set_all_parameterizations`,
        which also gives a description of each parameterization type.

    prep_prefix: string, optional
        Key prefixe for state preparations, allowing the model to determing what
        type of object a key corresponds to.

    effect_prefix : string, optional
        Key prefix for POVM effects, allowing the model to determing what
        type of object a key corresponds to.

    gate_prefix : string, optional
        Key prefix for gates, allowing the model to determing what
        type of object a key corresponds to.

    povm_prefix : string, optional
        Key prefix for POVMs, allowing the model to determing what
        type of object a key corresponds to.

    instrument_prefix : string, optional
        Key prefix for instruments, allowing the model to determing what
        type of object a key corresponds to.

    simulator : ForwardSimulator or {"auto", "matrix", "map"}
        The circuit simulator used to compute any
        requested probabilities, e.g. from :method:`probs` or
        :method:`bulk_probs`.  The default value of `"auto"` automatically
        selects the simulation type, and is usually what you want. Other
        special allowed values are:

        - "matrix" : op_matrix-op_matrix products are computed and
          cached to get composite gates which can then quickly simulate
          a circuit for any preparation and outcome.  High memory demand;
          best for a small number of (1 or 2) qubits.
        - "map" : op_matrix-state_vector products are repeatedly computed
          to simulate circuits.  Slower for a small number of qubits, but
          faster and more memory efficient for higher numbers of qubits (3+).

    evotype : {"densitymx", "statevec", "stabilizer", "svterm", "cterm"}
        The evolution type of this model, describing how states are
        represented, allowing compatibility checks with (super)operator
        objects.
    """

    #Whether access to gates & spam vecs via Model indexing is allowed
    _strict = False

    def __init__(self, state_space_labels, basis="auto", default_param="full",
                 prep_prefix="rho", effect_prefix="E", gate_prefix="G",
                 povm_prefix="M", instrument_prefix="I", simulator="auto",
                 evotype="densitymx"):
        """
        Initialize an ExplictOpModel.

        Parameters
        ----------
        state_space_labels : StateSpaceLabels or list or tuple
            The decomposition (with labels) of (pure) state-space this model
            acts upon.  Regardless of whether the model contains operators or
            superoperators, this argument describes the Hilbert space dimension
            and imposed structure.  If a list or tuple is given, it must be
            of a from that can be passed to `StateSpaceLabels.__init__`.

        basis : {"auto","pp","gm","qt","std","sv"} or Basis
            The basis used for the state space by dense operator representations.

        default_param : {"full", "TP", "CPTP", etc.}, optional
            Specifies the default gate and SPAM vector parameterization type.
            Can be any value allowed by :method:`set_all_parameterizations`,
            which also gives a description of each parameterization type.

        prep_prefix, effect_prefix, gate_prefix,
        povm_prefix, instrument_prefix : string, optional
            Key prefixes designating state preparations, POVM effects,
            gates, POVM, and instruments respectively.  These prefixes allow
            the Model to determine what type of object a key corresponds to.

        simulator : ForwardSimulator or {"auto", "matrix", "map"}
            The circuit simulator used to compute any
            requested probabilities, e.g. from :method:`probs` or
            :method:`bulk_probs`.

        evotype : {"densitymx", "statevec", "stabilizer", "svterm", "cterm"}
            The evolution type of this model, describing how states are
            represented, allowing compatibility checks with (super)operator
            objects.
        """
        #More options now (TODO enumerate?)
        #assert(default_param in ('full','TP','CPTP','H+S','S','static',
        #                         'H+S terms','clifford','H+S clifford terms'))
        def flagfn(typ): return {'auto_embed': True, 'match_parent_dim': True,
                                 'match_parent_evotype': True, 'cast_to_type': typ}

        self.preps = _ld.OrderedMemberDict(self, default_param, prep_prefix, flagfn("spamvec"))
        self.povms = _ld.OrderedMemberDict(self, default_param, povm_prefix, flagfn("povm"))
        self.operations = _ld.OrderedMemberDict(self, default_param, gate_prefix, flagfn("operation"))
        self.instruments = _ld.OrderedMemberDict(self, default_param, instrument_prefix, flagfn("instrument"))
        self.effects_prefix = effect_prefix

        self._default_gauge_group = None

        if basis == "auto":
            basis = "pp" if evotype in ("densitymx", "svterm", "cterm") \
                else "sv"  # ( if evotype in ("statevec","stabilizer") )

        super(ExplicitOpModel, self).__init__(state_space_labels, basis, evotype, ExplicitLayerRules(), simulator)

    @property
    def _primitive_prep_label_dict(self):
        return self.preps

    @property
    def _primitive_povm_label_dict(self):
        return self.povms

    @property
    def _primitive_op_label_dict(self):
        return self.operations

    @property
    def _primitive_instrument_label_dict(self):
        return self.instruments

    #Functions required for base class functionality

    def _iter_parameterized_objs(self):
        for lbl, obj in _itertools.chain(self.preps.items(),
                                         self.povms.items(),
                                         self.operations.items(),
                                         self.instruments.items()):
            yield (lbl, obj)

    def _excalc(self):
        """ Create & return a special explicit-model calculator for this model """

        self._clean_paramvec()  # ensures paramvec is rebuild if needed
        simplified_effects = _collections.OrderedDict()
        for povm_lbl, povm in self.povms.items():
            for k, e in povm.simplify_effects(povm_lbl).items():
                simplified_effects[k] = e

        simplified_ops = _collections.OrderedDict()
        for k, g in self.operations.items(): simplified_ops[k] = g
        for inst_lbl, inst in self.instruments.items():
            for k, g in inst.simplify_operations(inst_lbl).items():
                simplified_ops[k] = g
        simplified_preps = self.preps

        return _explicitcalc.ExplicitOpModelCalc(self.dim, simplified_preps, simplified_ops,
                                                 simplified_effects, self.num_params())

    #Unneeded - just use string processing & rely on effect labels *not* having underscores in them
    #def simplify_spamtuple_to_outcome_label(self, simplified_spamTuple):
    #    #TODO: make this more efficient (prep lbl isn't even used!)
    #    for prep_lbl in self.preps:
    #        for povm_lbl in self.povms:
    #            for elbl in self.povms[povm_lbl]:
    #                if simplified_spamTuple == (prep_lbl, povm_lbl + "_" + elbl):
    #                    return (elbl,) # outcome "label" (a tuple)
    #    raise ValueError("No outcome label found for simplified spam_tuple: ", simplified_spamTuple)

    def _embed_operation(self, op_target_labels, op_val, force=False):
        """
        Called by OrderedMemberDict._auto_embed to create an embedded-gate
        object that embeds `op_val` into the sub-space of
        `self.state_space_labels` given by `op_target_labels`.

        Parameters
        ----------
        op_target_labels : list
            A list of `op_val`'s target state space labels.

        op_val : LinearOperator
            The gate object to embed.  Note this should be a legitimate
            LinearOperator-derived object and not just a numpy array.

        force : bool, optional
            Always wrap with an embedded LinearOperator, even if the
            dimension of `op_val` is the full model dimension.

        Returns
        -------
        LinearOperator
            A gate of the full model dimension.
        """
        if self.dim is None:
            raise ValueError("Must set model dimension before adding auto-embedded gates.")
        if self.state_space_labels is None:
            raise ValueError("Must set model.state_space_labels before adding auto-embedded gates.")

        if op_val.dim == self.dim and not force:
            return op_val  # if gate operates on full dimension, no need to embed.

        if isinstance(self._sim, _matrixfwdsim.MatrixForwardSimulator):
            return _op.EmbeddedDenseOp(self.state_space_labels, op_target_labels, op_val)
        else:  # all other types, e.g. "map" and "termorder"
            return _op.EmbeddedOp(self.state_space_labels, op_target_labels, op_val)

    @property
    def default_gauge_group(self):
        """
        Gets the default gauge group for performing gauge transformations on this Model.

        Returns
        -------
        GaugeGroup
        """
        return self._default_gauge_group

    @default_gauge_group.setter
    def default_gauge_group(self, value):
        """
        The default gauge group.
        """
        self._default_gauge_group = value

    @property
    def prep(self):
        """
        The unique state preparation in this model, if one exists.

        If not, a ValueError is raised.

        Returns
        -------
        SPAMVec
        """
        if len(self.preps) != 1:
            raise ValueError("'.prep' can only be used on models"
                             " with a *single* state prep.  This Model has"
                             " %d state preps!" % len(self.preps))
        return list(self.preps.values())[0]

    @property
    def effects(self):
        """
        The unique POVM in this model, if one exists.

        If not, a ValueError is raised.

        Returns
        -------
        POVM
        """
        if len(self.povms) != 1:
            raise ValueError("'.effects' can only be used on models"
                             " with a *single* POVM.  This Model has"
                             " %d POVMS!" % len(self.povms))
        return list(self.povms.values())[0]

    def __setitem__(self, label, value):
        """
        Set an operator or SPAM vector associated with a given label.

        Parameters
        ----------
        label : string
            the gate or SPAM vector label.

        value : numpy array or LinearOperator or SPAMVec
            a operation matrix, SPAM vector, or object, which must have the
            appropriate dimension for the Model and appropriate type
            given the prefix of the label.
        """
        if ExplicitOpModel._strict:
            raise KeyError("Strict-mode: invalid key %s" % repr(label))

        if not isinstance(label, _Label): label = _Label(label)

        if label == _Label(()):  # special case
            self.operations[label] = value
        elif label.has_prefix(self.preps._prefix):
            self.preps[label] = value
        elif label.has_prefix(self.povms._prefix):
            self.povms[label] = value
        elif label.has_prefix(self.operations._prefix):
            self.operations[label] = value
        elif label.has_prefix(self.instruments._prefix, typ="any"):
            self.instruments[label] = value
        else:
            raise KeyError("Key %s has an invalid prefix" % label)

    def __getitem__(self, label):
        """
        Get an operation or SPAM vector associated with a given label.

        Parameters
        ----------
        label : string
            the gate or SPAM vector label.
        """
        if ExplicitOpModel._strict:
            raise KeyError("Strict-mode: invalid key %s" % label)

        if not isinstance(label, _Label): label = _Label(label)

        if label == _Label(()):  # special case
            return self.operations[label]
        elif label.has_prefix(self.preps._prefix):
            return self.preps[label]
        elif label.has_prefix(self.povms._prefix):
            return self.povms[label]
        elif label.has_prefix(self.operations._prefix):
            return self.operations[label]
        elif label.has_prefix(self.instruments._prefix, typ="any"):
            return self.instruments[label]
        else:
            raise KeyError("Key %s has an invalid prefix" % label)

    def set_all_parameterizations(self, parameterization_type, extra=None):
        """
        Convert all gates and SPAM vectors to a specific parameterization type.

        Parameters
        ----------
        parameterization_type : string
            The gate and SPAM vector parameterization type.  Allowed
            values are (where '*' means " terms" and " clifford terms"
            evolution-type suffixes are allowed):

            - "full" : each gate / SPAM element is an independent parameter
            - "TP" : Trace-Preserving gates and state preps
            - "static" : no parameters
            - "static unitary" : no parameters; convert superops to unitaries
            - "clifford" : no parameters; convert unitaries to Clifford symplecitics.
            - "GLND*" : General unconstrained Lindbladian
            - "CPTP*" : Completely-Positive-Trace-Preserving
            - "H+S+A*" : Hamiltoian, Pauli-Stochastic, and Affine errors
            - "H+S*" : Hamiltonian and Pauli-Stochastic errors
            - "S+A*" : Pauli-Stochastic and Affine errors
            - "S*" : Pauli-Stochastic errors
            - "H+D+A*" : Hamiltoian, Depolarization, and Affine errors
            - "H+D*" : Hamiltonian and Depolarization errors
            - "D+A*" : Depolarization and Affine errors
            - "D*" : Depolarization errors
            - Any of the above with "S" replaced with "s" or "D" replaced with
              "d". This removes the CPTP constraint on the Gates and SPAM (and
              as such is seldom used).

        extra : dict, optional
            For `"H+S terms"` type, this may specify a dictionary
            of unitary gates and pure state vectors to be used
            as the *ideal* operation of each gate/SPAM vector.

        Returns
        -------
        None
        """
        typ = parameterization_type

        #More options now (TODO enumerate?)
        #assert(parameterization_type in ('full','TP','CPTP','H+S','S','static',
        #                                 'H+S terms','clifford','H+S clifford terms',
        #                                 'static unitary'))

        #Update dim and evolution type so that setting converted elements works correctly
        baseType = typ  # the default - only updated if a lindblad param type

        if typ == 'static unitary':
            assert(self._evotype == "densitymx"), \
                "Can only convert to 'static unitary' from a density-matrix evolution type."
            self._evotype = "statevec"
            self._dim = int(round(_np.sqrt(self.dim)))  # reduce dimension d -> sqrt(d)
            if not isinstance(self._sim, (_matrixfwdsim.MatrixForwardSimulator, _mapfwdsim.MapForwardSimulator)):
                self._sim = _matrixfwdsim.MatrixForwardSimulator(self) if self.dim <= 4 else \
                    _mapfwdsim.MapForwardSimulator(self, max_cache_size=0)

        elif typ == 'clifford':
            self._evotype = "stabilizer"
            self._sim = _mapfwdsim.MapForwardSimulator(self, max_cache_size=0)

        elif _gt.is_valid_lindblad_paramtype(typ):
            baseType, evotype = _gt.split_lindblad_paramtype(typ)
            self._evotype = evotype
            if evotype == "densitymx":
                if not isinstance(self._sim, (_matrixfwdsim.MatrixForwardSimulator, _mapfwdsim.MapForwardSimulator)):
                    self._sim = _matrixfwdsim.MatrixForwardSimulator(self) if self.dim <= 16 else \
                        _mapfwdsim.MapForwardSimulator(self, max_cache_size=0)
            elif evotype in ("svterm", "cterm"):
                if not isinstance(self._sim, _termfwdsim.TermForwardSimulator):
                    self._sim = _termfwdsim.TermForwardSimulator(self)

        else:  # assume all other parameterizations are densitymx type
            self._evotype = "densitymx"
            if not isinstance(self._sim, (_matrixfwdsim.MatrixForwardSimulator, _mapfwdsim.MapForwardSimulator)):
                self._sim = _matrixfwdsim.MatrixForwardSimulator(self) if self.dim <= 16 else \
                    _mapfwdsim.MapForwardSimulator(self, max_cache_size=0)

        basis = self.basis
        if extra is None: extra = {}

        povmtyp = rtyp = typ  # assume spam types are available to all objects
        ityp = "TP" if _gt.is_valid_lindblad_paramtype(typ) else typ

        for lbl, gate in self.operations.items():
            self.operations[lbl] = _op.convert(gate, typ, basis,
                                               extra.get(lbl, None))

        for lbl, inst in self.instruments.items():
            self.instruments[lbl] = _instrument.convert(inst, ityp, basis,
                                                        extra.get(lbl, None))

        for lbl, vec in self.preps.items():
            self.preps[lbl] = _sv.convert(vec, rtyp, basis,
                                          extra.get(lbl, None))

        for lbl, povm in self.povms.items():
            self.povms[lbl] = _povm.convert(povm, povmtyp, basis,
                                            extra.get(lbl, None))

        if typ == 'full':
            self.default_gauge_group = _gg.FullGaugeGroup(self.dim)
        elif typ == 'TP':
            self.default_gauge_group = _gg.TPGaugeGroup(self.dim)
        elif typ == 'CPTP':
            self.default_gauge_group = _gg.UnitaryGaugeGroup(self.dim, basis)
        else:  # typ in ('static','H+S','S', 'H+S terms', ...)
            self.default_gauge_group = _gg.TrivialGaugeGroup(self.dim)

    #def __getstate__(self):
    #    #Returns self.__dict__ by default, which is fine

    def __setstate__(self, state_dict):

        if "gates" in state_dict:
            #Unpickling an OLD-version Model (or GateSet)
            _warnings.warn("Unpickling deprecated-format ExplicitOpModel (GateSet).  Please re-save/pickle asap.")
            self.operations = state_dict['gates']
            self._state_space_labels = state_dict['stateSpaceLabels']
            self._paramlbls = None
            del state_dict['gates']
            del state_dict['_autogator']
            del state_dict['auto_idle_gatename']
            del state_dict['stateSpaceLabels']

        if "effects" in state_dict:
            raise ValueError(("This model (GateSet) object is too old to unpickle - "
                              "try using pyGSTi v0.9.6 to upgrade it to a version "
                              "that this version can upgrade to the current version."))

        #Backward compatibility:
        if 'basis' in state_dict:
            state_dict['_basis'] = state_dict['basis']; del state_dict['basis']
        if 'state_space_labels' in state_dict:
            state_dict['_state_space_labels'] = state_dict['state_space_labels']; del state_dict['_state_space_labels']

        #TODO REMOVE
        #if "effects" in state_dict: #
        #    #unpickling an OLD-version Model - like a re-__init__
        #    #print("DB: UNPICKLING AN OLD GATESET"); print("Keys = ",state_dict.keys())
        #    default_param = "full"
        #    self.preps = _ld.OrderedMemberDict(self, default_param, "rho", "spamvec")
        #    self.povms = _ld.OrderedMemberDict(self, default_param, "M", "povm")
        #    self.effects_prefix = 'E'
        #    self.operations = _ld.OrderedMemberDict(self, default_param, "G", "gate")
        #    self.instruments = _ld.OrderedMemberDict(self, default_param, "I", "instrument")
        #    self._paramvec = _np.zeros(0, 'd')
        #    self._rebuild_paramvec()
        #
        #    self._dim = state_dict['_dim']
        #    self._calcClass = state_dict.get('_calcClass',_matrixfwdsim.MatrixForwardSimulator)
        #    self._evotype = "densitymx"
        #    self.basis = state_dict.get('basis', _Basis('unknown', None))
        #    if self.basis.name == "unknown" and '_basisNameAndDim' in state_dict:
        #        self.basis = _Basis(state_dict['_basisNameAndDim'][0],
        #                            state_dict['_basisNameAndDim'][1])
        #
        #    self._default_gauge_group = state_dict['_default_gauge_group']
        #
        #    assert(len(state_dict['preps']) <= 1), "Cannot convert Models with multiple preps!"
        #    for lbl,gate in state_dict['gates'].items(): self.operations[lbl] = gate
        #    for lbl,vec in state_dict['preps'].items(): self.preps[lbl] = vec
        #
        #    effect_vecs = []; remL = state_dict['_remainderlabel']
        #    comp_lbl = None
        #    for sl,(prepLbl,ELbl) in state_dict['spamdefs'].items():
        #        assert((prepLbl,ELbl) != (remL,remL)), "Cannot convert sum-to-one spamlabel!"
        #        if ELbl == remL:  comp_lbl = str(sl)
        #        else: effect_vecs.append( (str(sl), state_dict['effects'][ELbl]) )
        #    if comp_lbl is not None:
        #        comp_vec = state_dict['_povm_identity'] - sum([v for sl,v in effect_vecs])
        #        effect_vecs.append( (comp_lbl, comp_vec) )
        #        self.povms['Mdefault'] = _povm.TPPOVM(effect_vecs)
        #    else:
        #        self.povms['Mdefault'] = _povm.UnconstrainedPOVM(effect_vecs)
        #
        #else:
        self.__dict__.update(state_dict)

        if 'uuid' not in state_dict:
            self.uuid = _uuid.uuid4()  # create a new uuid

        #Additionally, must re-connect this model as the parent
        # of relevant OrderedDict-derived classes, which *don't*
        # preserve this information upon pickling so as to avoid
        # circular pickling...
        self.preps.parent = self
        self.povms.parent = self
        #self.effects.parent = self
        self.operations.parent = self
        self.instruments.parent = self
        for o in self.preps.values(): o.relink_parent(self)
        for o in self.povms.values(): o.relink_parent(self)
        #for o in self.effects.values(): o.relink_parent(self)
        for o in self.operations.values(): o.relink_parent(self)
        for o in self.instruments.values(): o.relink_parent(self)

    def num_elements(self):
        """
        Return the number of total operation matrix and spam vector elements in this model.

        This is in general different from the number of *parameters* in the
        model, which are the number of free variables used to generate all of
        the matrix and vector *elements*.

        Returns
        -------
        int
            the number of model elements.
        """
        rhoSize = [rho.size for rho in self.preps.values()]
        povmSize = [povm.num_elements() for povm in self.povms.values()]
        opSize = [gate.size for gate in self.operations.values()]
        instSize = [i.num_elements() for i in self.instruments.values()]
        return sum(rhoSize) + sum(povmSize) + sum(opSize) + sum(instSize)

    def num_nongauge_params(self):
        """
        Return the number of non-gauge parameters in this model.

        Returns
        -------
        int
            the number of non-gauge model parameters.
        """
        return self.num_params() - self.num_gauge_params()

    def num_gauge_params(self):
        """
        Return the number of gauge parameters in this model.

        Returns
        -------
        int
            the number of gauge model parameters.
        """
        if self._evotype not in ("densitymx", "statevec"):
            return 0  # punt on computing number of gauge parameters for other evotypes
        dPG = self._excalc()._buildup_dpg()
        gaugeDirs = _mt.nullspace_qr(dPG)  # cols are gauge directions
        if gaugeDirs.size == 0:  # if there are *no* gauge directions
            return 0  # calling matrix_rank on a length-0 array => error
        return _np.linalg.matrix_rank(gaugeDirs[0:self.num_params(), :])

    def deriv_wrt_params(self):
        """
        The element-wise derivative of all this models' operations.

        Constructs a matrix whose columns are the vectorized derivatives of all
        the model's raw matrix and vector *elements* (placed in a vector)
        with respect to each single model parameter.

        Thus, each column has length equal to the number of elements in the
        model, and there are num_params() columns.  In the case of a "fully
        parameterized model" (i.e. all operation matrices and SPAM vectors are
        fully parameterized) then the resulting matrix will be the (square)
        identity matrix.

        Returns
        -------
        numpy array
            2D array of derivatives.
        """
        return self._excalc().deriv_wrt_params()

    def compute_nongauge_projector(self, item_weights=None, non_gauge_mix_mx=None):
        """
        Construct a projector onto the non-gauge parameter space.

        Useful for isolating the gauge degrees of freedom from the non-gauge
        degrees of freedom.

        Parameters
        ----------
        item_weights : dict, optional
            Dictionary of weighting factors for individual gates and spam operators.
            Keys can be gate, state preparation, POVM effect, spam labels, or the
            special strings "gates" or "spam" whic represent the entire set of gate
            or SPAM operators, respectively.  Values are floating point numbers.
            These weights define the metric used to compute the non-gauge space,
            *orthogonal* the gauge space, that is projected onto.

        non_gauge_mix_mx : numpy array, optional
            An array of shape (n_non_gauge_params,n_gauge_params) specifying how to
            mix the non-gauge degrees of freedom into the gauge degrees of
            freedom that are projected out by the returned object.  This argument
            essentially sets the off-diagonal block of the metric used for
            orthogonality in the "gauge + non-gauge" space.  It is for advanced
            usage and typically left as None (the default).

        Returns
        -------
        numpy array
           The projection operator as a N x N matrix, where N is the number
           of parameters (obtained via num_params()).  This projector acts on
           parameter-space, and has rank equal to the number of non-gauge
           degrees of freedom.
        """
        return self._excalc().nongauge_projector(item_weights, non_gauge_mix_mx)

    def transform_inplace(self, s):
        """
        Gauge transform this model.

        Update each of the operation matrices G in this model with inv(s) * G * s,
        each rhoVec with inv(s) * rhoVec, and each EVec with EVec * s

        Parameters
        ----------
        s : GaugeGroupElement
            A gauge group element which specifies the "s" matrix
            (and it's inverse) used in the above similarity transform.

        Returns
        -------
        None
        """
        for rhoVec in self.preps.values():
            rhoVec.transform_inplace(s, 'prep')

        for povm in self.povms.values():
            povm.transform_inplace(s)

        for opObj in self.operations.values():
            opObj.transform_inplace(s)

        for instrument in self.instruments.values():
            instrument.transform_inplace(s)

        self._clean_paramvec()  # transform may leave dirty members

#REMOVE
#    def product(self, circuit, scale=False):
#        """
#        Compute the product of a specified sequence of operation labels.
#
#        Note: Operator matrices are multiplied in the reversed order of the tuple. That is,
#        the first element of circuit can be thought of as the first gate operation
#        performed, which is on the far right of the product of matrices.
#
#        Parameters
#        ----------
#        circuit : Circuit or tuple of operation labels
#            The sequence of operation labels.
#
#        scale : bool, optional
#            When True, return a scaling factor (see below).
#
#        Returns
#        -------
#        product : numpy array
#            The product or scaled product of the operation matrices.
#
#        scale : float
#            Only returned when scale == True, in which case the
#            actual product == product * scale.  The purpose of this
#            is to allow a trace or other linear operation to be done
#            prior to the scaling.
#        """
#        circuit = _cir.Circuit(circuit)  # cast to Circuit
#        return self._fwdsim().product(circuit, scale)
#
#    def dproduct(self, circuit, flat=False):
#        """
#        Compute the derivative of a specified sequence of operation labels.
#
#        Parameters
#        ----------
#        circuit : Circuit or tuple of operation labels
#            The sequence of operation labels.
#
#        flat : bool, optional
#            Affects the shape of the returned derivative array (see below).
#
#        Returns
#        -------
#        deriv : numpy array
#            * if flat == False, a M x G x G array, where:
#
#              - M == length of the vectorized model (number of model parameters)
#              - G == the linear dimension of a operation matrix (G x G operation matrices).
#
#              and deriv[i,j,k] holds the derivative of the (j,k)-th entry of the product
#              with respect to the i-th model parameter.
#
#            * if flat == True, a N x M array, where:
#
#              - N == the number of entries in a single flattened gate (ordering as numpy.flatten)
#              - M == length of the vectorized model (number of model parameters)
#
#              and deriv[i,j] holds the derivative of the i-th entry of the flattened
#              product with respect to the j-th model parameter.
#        """
#        circuit = _cir.Circuit(circuit)  # cast to Circuit
#        return self._fwdsim().dproduct(circuit, flat)
#
#    def hproduct(self, circuit, flat=False):
#        """
#        Compute the hessian of a specified sequence of operation labels.
#
#        Parameters
#        ----------
#        circuit : Circuit or tuple of operation labels
#            The sequence of operation labels.
#
#        flat : bool, optional
#            Affects the shape of the returned derivative array (see below).
#
#        Returns
#        -------
#        hessian : numpy array
#            * if flat == False, a  M x M x G x G numpy array, where:
#
#              - M == length of the vectorized model (number of model parameters)
#              - G == the linear dimension of a operation matrix (G x G operation matrices).
#
#              and hessian[i,j,k,l] holds the derivative of the (k,l)-th entry of the product
#              with respect to the j-th then i-th model parameters.
#
#            * if flat == True, a  N x M x M numpy array, where:
#
#              - N == the number of entries in a single flattened gate (ordered as numpy.flatten)
#              - M == length of the vectorized model (number of model parameters)
#
#              and hessian[i,j,k] holds the derivative of the i-th entry of the flattened
#              product with respect to the k-th then k-th model parameters.
#        """
#        circuit = _cir.Circuit(circuit)  # cast to Circuit
#        return self._fwdsim().hproduct(circuit, flat)
#
#    def bulk_product(self, eval_tree, scale=False, comm=None):
#        """
#        Compute the products of many operation sequences at once.
#
#        Parameters
#        ----------
#        eval_tree : EvalTree
#            given by a prior call to bulk_evaltree.  Specifies the operation sequences
#            to compute the bulk operation on.
#
#        scale : bool, optional
#            When True, return a scaling factor (see below).
#
#        comm : mpi4py.MPI.Comm, optional
#            When not None, an MPI communicator for distributing the computation
#            across multiple processors.  This is done over operation sequences when a
#            *split* eval_tree is given, otherwise no parallelization is performed.
#
#        Returns
#        -------
#        prods : numpy array
#            Array of shape S x G x G, where:
#
#            - S == the number of operation sequences
#            - G == the linear dimension of a operation matrix (G x G operation matrices).
#        scaleValues : numpy array
#            Only returned when scale == True. A length-S array specifying
#            the scaling that needs to be applied to the resulting products
#            (final_product[i] = scaleValues[i] * prods[i]).
#        """
#        return self._fwdsim().bulk_product(eval_tree, scale, comm)
#
#    def bulk_dproduct(self, eval_tree, flat=False, return_prods=False,
#                      scale=False, comm=None):
#        """
#        Compute the derivative of many operation sequences at once.
#
#        Parameters
#        ----------
#        eval_tree : EvalTree
#            given by a prior call to bulk_evaltree.  Specifies the operation sequences
#            to compute the bulk operation on.
#
#        flat : bool, optional
#            Affects the shape of the returned derivative array (see below).
#
#        return_prods : bool, optional
#            when set to True, additionally return the products.
#
#        scale : bool, optional
#            When True, return a scaling factor (see below).
#
#        comm : mpi4py.MPI.Comm, optional
#            When not None, an MPI communicator for distributing the computation
#            across multiple processors.  Distribution is first done over the set
#            of parameters being differentiated with respect to.  If there are
#            more processors than model parameters, distribution over a split
#            eval_tree (if given) is possible.
#
#        Returns
#        -------
#        derivs : numpy array
#            * if `flat` is ``False``, an array of shape S x M x G x G, where:
#
#              - S = len(circuit_list)
#              - M = the length of the vectorized model
#              - G = the linear dimension of a operation matrix (G x G operation matrices)
#
#              and ``derivs[i,j,k,l]`` holds the derivative of the (k,l)-th entry
#              of the i-th operation sequence product with respect to the j-th model
#              parameter.
#
#            * if `flat` is ``True``, an array of shape S*N x M where:
#
#              - N = the number of entries in a single flattened gate (ordering
#                same as numpy.flatten),
#              - S,M = as above,
#
#              and ``deriv[i,j]`` holds the derivative of the ``(i % G^2)``-th
#              entry of the ``(i / G^2)``-th flattened operation sequence product  with
#              respect to the j-th model parameter.
#        products : numpy array
#            Only returned when `return_prods` is ``True``.  An array of shape
#            S x G x G; ``products[i]`` is the i-th operation sequence product.
#        scale_vals : numpy array
#            Only returned when `scale` is ``True``.  An array of shape S such
#            that ``scale_vals[i]`` contains the multiplicative scaling needed for
#            the derivatives and/or products for the i-th operation sequence.
#        """
#        return self._fwdsim().bulk_dproduct(eval_tree, flat, return_prods,
#                                            scale, comm)
#
#    def bulk_hproduct(self, eval_tree, flat=False, return_dprods_and_prods=False,
#                      scale=False, comm=None):
#        """
#        Return the Hessian of many operation sequence products at once.
#
#        Parameters
#        ----------
#        eval_tree : EvalTree
#            given by a prior call to bulk_evaltree.  Specifies the operation sequences
#            to compute the bulk operation on.
#
#        flat : bool, optional
#            Affects the shape of the returned derivative array (see below).
#
#        return_dprods_and_prods : bool, optional
#            when set to True, additionally return the probabilities and
#            their derivatives.
#
#        scale : bool, optional
#            When True, return a scaling factor (see below).
#
#        comm : mpi4py.MPI.Comm, optional
#            When not None, an MPI communicator for distributing the computation
#            across multiple processors.  Distribution is first done over the
#            set of parameters being differentiated with respect to when the
#            *second* derivative is taken.  If there are more processors than
#            model parameters, distribution over a split eval_tree (if given)
#            is possible.
#
#        Returns
#        -------
#        hessians : numpy array
#            * if flat == False, an  array of shape S x M x M x G x G, where
#
#              - S == len(circuit_list)
#              - M == the length of the vectorized model
#              - G == the linear dimension of a operation matrix (G x G operation matrices)
#
#              and hessians[i,j,k,l,m] holds the derivative of the (l,m)-th entry
#              of the i-th operation sequence product with respect to the k-th then j-th
#              model parameters.
#
#            * if flat == True, an array of shape S*N x M x M where
#
#              - N == the number of entries in a single flattened gate (ordering as numpy.flatten),
#              - S,M == as above,
#
#              and hessians[i,j,k] holds the derivative of the (i % G^2)-th entry
#              of the (i / G^2)-th flattened operation sequence product with respect to
#              the k-th then j-th model parameters.
#        derivs : numpy array
#            Only returned if return_dprods_and_prods == True.
#
#            * if flat == False, an array of shape S x M x G x G, where
#
#              - S == len(circuit_list)
#              - M == the length of the vectorized model
#              - G == the linear dimension of a operation matrix (G x G operation matrices)
#
#              and derivs[i,j,k,l] holds the derivative of the (k,l)-th entry
#              of the i-th operation sequence product with respect to the j-th model
#              parameter.
#
#            * if flat == True, an array of shape S*N x M where
#
#              - N == the number of entries in a single flattened gate (ordering is
#                     the same as that used by numpy.flatten),
#              - S,M == as above,
#
#              and deriv[i,j] holds the derivative of the (i % G^2)-th entry of
#              the (i / G^2)-th flattened operation sequence product  with respect to
#              the j-th model parameter.
#        products : numpy array
#            Only returned when return_dprods_and_prods == True.  An array of shape
#            S x G x G; products[i] is the i-th operation sequence product.
#        scale_vals : numpy array
#            Only returned when scale == True.  An array of shape S such that
#            scale_vals[i] contains the multiplicative scaling needed for
#            the hessians, derivatives, and/or products for the i-th operation sequence.
#        """
#        ret = self._fwdsim().bulk_hproduct(
#            eval_tree, flat, return_dprods_and_prods, scale, comm)
#        if return_dprods_and_prods:
#            return ret[0:2] + ret[3:]  # remove ret[2] == deriv wrt filter2,
#            # which isn't an input param for Model version
#        else: return ret

    def frobeniusdist(self, other_model, transform_mx=None,
                      item_weights=None, normalize=True):
        """
        Compute the weighted frobenius norm of the difference between this model and other_model.

        Differences in each corresponding gate matrix and spam vector element
        are squared, weighted (using `item_weights` as applicable), then summed.
        The value returned is the square root of this sum, or the square root of
        this sum divided by the number of summands if normalize == True.

        Parameters
        ----------
        other_model : Model
            the other model to difference against.

        transform_mx : numpy array, optional
            if not None, transform this model by
            G => inv(transform_mx) * G * transform_mx, for each operation matrix G
            (and similar for rho and E vectors) before taking the difference.
            This transformation is applied only for the difference and does
            not alter the values stored in this model.

        item_weights : dict, optional
            Dictionary of weighting factors for individual gates and spam
            operators. Weights are applied multiplicatively to the squared
            differences, i.e., (*before* the final square root is taken).  Keys
            can be gate, state preparation, POVM effect, or spam labels, as well
            as the two special labels `"gates"` and `"spam"` which apply to all
            of the gate or SPAM elements, respectively (but are overridden by
            specific element values).  Values are floating point numbers.
            By default, all weights are 1.0.

        normalize : bool, optional
            if True (the default), the sum of weighted squared-differences
            is divided by the weighted number of differences before the
            final square root is taken.  If False, the division is not performed.

        Returns
        -------
        float
        """
        return self._excalc().frobeniusdist(other_model._excalc(), transform_mx,
                                            item_weights, normalize)

    def residuals(self, other_model, transform_mx=None, item_weights=None):
        """
        Compute the weighted residuals between two models.

        Residuals are the differences in corresponding operation matrix and spam
        vector elements.

        Parameters
        ----------
        other_model : Model
            the other model to difference against.

        transform_mx : numpy array, optional
            if not None, transform this model by
            G => inv(transform_mx) * G * transform_mx, for each operation matrix G
            (and similar for rho and E vectors) before taking the difference.
            This transformation is applied only for the difference and does
            not alter the values stored in this model.

        item_weights : dict, optional
            Dictionary of weighting factors for individual gates and spam
            operators. Weights applied such that they act multiplicatively on
            the *squared* differences, so that the residuals themselves are
            scaled by the square roots of these weights.  Keys can be gate, state
            preparation, POVM effect, or spam labels, as well as the two special
            labels `"gates"` and `"spam"` which apply to all of the gate or SPAM
            elements, respectively (but are overridden by specific element
            values).  Values are floating point numbers.  By default, all weights
            are 1.0.

        Returns
        -------
        residuals : numpy.ndarray
            A 1D array of residuals (differences w.r.t. other)
        nSummands : int
            The (weighted) number of elements accounted for by the residuals.
        """
        return self._excalc().residuals(other_model._excalc(), transform_mx, item_weights)

    def jtracedist(self, other_model, transform_mx=None, include_spam=True):
        """
        Compute the Jamiolkowski trace distance between this model and `other_model`.

        This is defined as the maximum of the trace distances between each
        corresponding gate, including spam gates.

        Parameters
        ----------
        other_model : Model
            the other model to difference against.

        transform_mx : numpy array, optional
            if not None, transform this model by
            G => inv(transform_mx) * G * transform_mx, for each operation matrix G
            (and similar for rho and E vectors) before taking the difference.
            This transformation is applied only for the difference and does
            not alter the values stored in this model.

        include_spam : bool, optional
            Whether to add to the max-trace-distance the frobenius distances
            between corresponding SPAM vectors.

        Returns
        -------
        float
        """
        return self._excalc().jtracedist(other_model._excalc(), transform_mx, include_spam)

    def diamonddist(self, other_model, transform_mx=None, include_spam=True):
        """
        Compute the diamond-norm distance between this model and `other_model`.

        This is defined as the maximum of the diamond-norm distances between each
        corresponding gate, including spam gates.

        Parameters
        ----------
        other_model : Model
            the other model to difference against.

        transform_mx : numpy array, optional
            if not None, transform this model by
            G => inv(transform_mx) * G * transform_mx, for each operation matrix G
            (and similar for rho and E vectors) before taking the difference.
            This transformation is applied only for the difference and does
            not alter the values stored in this model.

        include_spam : bool, optional
            Whether to add to the max-diamond-distance the frobenius distances
            between corresponding SPAM vectors.

        Returns
        -------
        float
        """
        return self._excalc().diamonddist(other_model._excalc(), transform_mx, include_spam)

    def _tpdist(self):
        """
        Compute the "distance" between this model and the space of trace-preserving (TP) maps.

        This is defined as the square root of the sum-of-squared deviations
        among the first row of all operation matrices and the first element of
        all state preparations.

        Returns
        -------
        float
        """
        penalty = 0.0
        for operationMx in list(self.operations.values()):
            penalty += abs(operationMx[0, 0] - 1.0)**2
            for k in range(1, operationMx.shape[1]):
                penalty += abs(operationMx[0, k])**2

        op_dim = self.get_dimension()
        firstEl = 1.0 / op_dim**0.25
        for rhoVec in list(self.preps.values()):
            penalty += abs(rhoVec[0, 0] - firstEl)**2

        return _np.sqrt(penalty)

    def strdiff(self, other_model, metric='frobenius'):
        """
        Return a string describing the distances between this model and `other_model`.

        The returned string displays differences between each corresponding gate,
        state prep, and POVM effect.

        Parameters
        ----------
        other_model : Model
            the other model to difference against.

        metric : {'frobenius', 'infidelity', 'diamond'}
            Which distance metric to use.

        Returns
        -------
        str
        """

        if metric == 'frobenius':
            def dist(a, b): return _np.linalg.norm(a - b)
            def vecdist(a, b): return _np.linalg.norm(a - b)
        elif metric == 'infidelity':
            def dist(a, b): return _gt.entanglement_infidelity(a, b, self.basis)
            def vecdist(a, b): return _np.linalg.norm(a - b)
        elif metric == 'diamond':
            def dist(a, b): return 0.5 * _gt.diamondist(a, b, self.basis)
            def vecdist(a, b): return _np.linalg.norm(a - b)
        else:
            raise ValueError("Invalid `metric` argument: %s" % metric)

        s = "Model Difference:\n"
        s += " Preps:\n"
        for lbl in self.preps:
            s += "  %s = %g\n" % \
                (str(lbl), vecdist(self.preps[lbl].to_dense(), other_model.preps[lbl].to_dense()))

        s += " POVMs:\n"
        for povm_lbl, povm in self.povms.items():
            s += "  %s: " % str(povm_lbl)
            for lbl in povm:
                s += "    %s = %g\n" % \
                     (lbl, vecdist(povm[lbl].to_dense(), other_model.povms[povm_lbl][lbl].to_dense()))

        s += " Gates:\n"
        for lbl in self.operations:
            s += "  %s = %g\n" % \
                (str(lbl), dist(self.operations[lbl].to_dense(), other_model.operations[lbl].to_dense()))

        if len(self.instruments) > 0:
            s += " Instruments:\n"
            for inst_lbl, inst in self.instruments.items():
                s += "  %s: " % str(inst_lbl)
                for lbl in inst:
                    s += "    %s = %g\n" % (str(lbl), dist(
                        inst[lbl].to_dense(), other_model.instruments[inst_lbl][lbl].to_dense()))

        return s

    def _init_copy(self, copy_into):
        """
        Copies any "tricky" member of this model into `copy_into`, before
        deep copying everything else within a .copy() operation.
        """

        # Copy special base class members first
        super(ExplicitOpModel, self)._init_copy(copy_into)

        # Copy our "tricky" members
        copy_into.preps = self.preps.copy(copy_into)
        copy_into.povms = self.povms.copy(copy_into)
        copy_into.operations = self.operations.copy(copy_into)
        copy_into.instruments = self.instruments.copy(copy_into)
        copy_into._default_gauge_group = self._default_gauge_group  # Note: SHALLOW copy

    def __str__(self):
        s = ""
        for lbl, vec in self.preps.items():
            s += "%s = " % str(lbl) + str(vec) + "\n"
        s += "\n"
        for lbl, povm in self.povms.items():
            s += "%s = " % str(lbl) + str(povm) + "\n"
        s += "\n"
        for lbl, gate in self.operations.items():
            s += "%s = \n" % str(lbl) + str(gate) + "\n\n"
        for lbl, inst in self.instruments.items():
            s += "%s = " % str(lbl) + str(inst) + "\n"
        s += "\n"

        return s

    def all_objects(self):
        """
        Iterate over all of the (label, operator object) entities in this model.

        This iterator runs over all state preparations, POVMS, operations,
        and instruments.
        """
        for lbl, obj in _itertools.chain(self.preps.items(),
                                         self.povms.items(),
                                         self.operations.items(),
                                         self.instruments.items()):
            yield (lbl, obj)

#TODO: how to handle these given possibility of different parameterizations...
#  -- maybe only allow these methods to be called when using a "full" parameterization?
#  -- or perhaps better to *move* them to the parameterization class
    def depolarize(self, op_noise=None, spam_noise=None, max_op_noise=None,
                   max_spam_noise=None, seed=None):
        """
        Apply depolarization uniformly or randomly to this model's gate and/or SPAM elements.

        The result is returned without modifying the original (this) model.  You
        must specify either `op_noise` or `max_op_noise` (for the amount of gate
        depolarization), and either `spam_noise` or `max_spam_noise` (for spam
        depolarization).

        Parameters
        ----------
        op_noise : float, optional
            apply depolarizing noise of strength ``1-op_noise`` to all gates in
             the model. (Multiplies each assumed-Pauli-basis operation matrix by the
             diagonal matrix with ``(1.0-op_noise)`` along all the diagonal
             elements except the first (the identity).

        spam_noise : float, optional
            apply depolarizing noise of strength ``1-spam_noise`` to all SPAM
            vectors in the model. (Multiplies the non-identity part of each
            assumed-Pauli-basis state preparation vector and measurement vector
            by ``(1.0-spam_noise)``).

        max_op_noise : float, optional
            specified instead of `op_noise`; apply a random depolarization
            with maximum strength ``1-max_op_noise`` to each gate in the
            model.

        max_spam_noise : float, optional
            specified instead of `spam_noise`; apply a random depolarization
            with maximum strength ``1-max_spam_noise`` to SPAM vector in the
            model.

        seed : int, optional
            if not ``None``, seed numpy's random number generator with this value
            before generating random depolarizations.

        Returns
        -------
        Model
            the depolarized Model
        """
        newModel = self.copy()  # start by just copying the current model
        rndm = _np.random.RandomState(seed)

        if max_op_noise is not None:
            if op_noise is not None:
                raise ValueError("Must specify at most one of 'op_noise' and 'max_op_noise' NOT both")

            #Apply random depolarization to each gate
            r = max_op_noise * rndm.random_sample(len(self.operations))
            for i, label in enumerate(self.operations):
                newModel.operations[label].depolarize(r[i])
            r = max_op_noise * rndm.random_sample(len(self.instruments))
            for i, label in enumerate(self.instruments):
                newModel.instruments[label].depolarize(r[i])

        elif op_noise is not None:
            #Apply the same depolarization to each gate
            for label in self.operations:
                newModel.operations[label].depolarize(op_noise)
            for label in self.instruments:
                newModel.instruments[label].depolarize(op_noise)

        if max_spam_noise is not None:
            if spam_noise is not None:
                raise ValueError("Must specify at most  one of 'noise' and 'max_noise' NOT both")

            #Apply random depolarization to each rho and E vector
            r = max_spam_noise * rndm.random_sample(len(self.preps))
            for (i, lbl) in enumerate(self.preps):
                newModel.preps[lbl].depolarize(r[i])
            r = max_spam_noise * rndm.random_sample(len(self.povms))
            for label in self.povms:
                newModel.povms[label].depolarize(r[i])

        elif spam_noise is not None:
            #Apply the same depolarization to each gate
            for lbl in self.preps:
                newModel.preps[lbl].depolarize(spam_noise)

            # Just depolarize the preps - leave POVMs alone
            #for label in self.povms:
            #    newModel.povms[label].depolarize(spam_noise)

        newModel._clean_paramvec()  # depolarize may leave dirty members
        return newModel

    def rotate(self, rotate=None, max_rotate=None, seed=None):
        """
        Apply a rotation uniformly or randomly to this model.

        Uniformly means the same rotation applied to each gate and
        randomly means different random rotations are applied to each gate of
        this model.  The result is returned without modifying the original (this) model.

        You must specify either `rotate` or `max_rotate`. This method currently
        only works on n-qubit models.

        Parameters
        ----------
        rotate : tuple of floats, optional
            If you specify the `rotate` argument, then the same rotation
            operation is applied to each gate.  That is, each gate's matrix `G`
            is composed with a rotation operation `R`  (so `G` -> `dot(R, G)` )
            where `R` is the unitary superoperator corresponding to the unitary
            operator `U = exp( sum_k( i * rotate[k] / 2.0 * Pauli_k ) )`.  Here
            `Pauli_k` ranges over all of the non-identity un-normalized Pauli
            operators (e.g. {X,Y,Z} for 1 qubit, {IX, IY, IZ, XI, XX, XY, XZ,
            YI, YX, YY, YZ, ZI, ZX, ZY, ZZ} for 2 qubits).

        max_rotate : float, optional
            If `max_rotate` is specified (*instead* of `rotate`), then pyGSTi
            randomly generates a different `rotate` tuple, and applies the
            corresponding rotation, to each gate in this `Model`.  Each
            component of each tuple is drawn uniformly from [0, `max_rotate`).

        seed : int, optional
            if  not None, seed numpy's random number generator with this value
            before generating random depolarizations.

        Returns
        -------
        Model
            the rotated Model
        """
        newModel = self.copy()  # start by just copying model
        dim = self.get_dimension()
        myBasis = self.basis

        if max_rotate is not None:
            if rotate is not None:
                raise ValueError("Must specify exactly one of 'rotate' and 'max_rotate' NOT both")

            #Apply random rotation to each gate
            rndm = _np.random.RandomState(seed)
            r = max_rotate * rndm.random_sample(len(self.operations) * (dim - 1))
            for i, label in enumerate(self.operations):
                rot = _np.array(r[(dim - 1) * i:(dim - 1) * (i + 1)])
                newModel.operations[label].rotate(rot, myBasis)
            r = max_rotate * rndm.random_sample(len(self.instruments) * (dim - 1))
            for i, label in enumerate(self.instruments):
                rot = _np.array(r[(dim - 1) * i:(dim - 1) * (i + 1)])
                newModel.instruments[label].rotate(rot, myBasis)

        elif rotate is not None:
            assert(len(rotate) == dim - 1), \
                "Invalid 'rotate' argument. You must supply a tuple of length %d" % (dim - 1)
            for label in self.operations:
                newModel.operations[label].rotate(rotate, myBasis)
            for label in self.instruments:
                newModel.instruments[label].rotate(rotate, myBasis)

        else: raise ValueError("Must specify either 'rotate' or 'max_rotate' "
                               + "-- neither was non-None")

        newModel._clean_paramvec()  # rotate may leave dirty members
        return newModel

    def randomize_with_unitary(self, scale, seed=None, rand_state=None):
        """
        Create a new model with random unitary perturbations.

        Apply a random unitary to each element of a model, and return the
        result, without modifying the original (this) model. This method
        works on Model as long as the dimension is a perfect square.

        Parameters
        ----------
        scale : float
            maximum element magnitude in the generator of each random unitary
            transform.

        seed : int, optional
            if not None, seed numpy's random number generator with this value
            before generating random depolarizations.

        rand_state : numpy.random.RandomState
            A RandomState object to generate samples from. Can be useful to set
            instead of `seed` if you want reproducible distribution samples
            across multiple random function calls but you don't want to bother
            with manually incrementing seeds between those calls.

        Returns
        -------
        Model
            the randomized Model
        """
        if rand_state is None:
            rndm = _np.random.RandomState(seed)
        else:
            rndm = rand_state

        op_dim = self.get_dimension()
        unitary_dim = int(round(_np.sqrt(op_dim)))
        assert(unitary_dim**2 == op_dim), \
            "Model dimension must be a perfect square, %d is not" % op_dim

        mdl_randomized = self.copy()

        for opLabel, gate in self.operations.items():
            randMat = scale * (rndm.randn(unitary_dim, unitary_dim)
                               + 1j * rndm.randn(unitary_dim, unitary_dim))
            randMat = _np.transpose(_np.conjugate(randMat)) + randMat
            # make randMat Hermetian: (A_dag + A)^dag = (A_dag + A)
            randUnitary = _scipy.linalg.expm(-1j * randMat)

            randOp = _gt.unitary_to_process_mx(randUnitary)  # in std basis
            randOp = _bt.change_basis(randOp, "std", self.basis)

            mdl_randomized.operations[opLabel] = _op.FullDenseOp(
                _np.dot(randOp, gate))

        #Note: this function does NOT randomize instruments

        return mdl_randomized

    def increase_dimension(self, new_dimension):
        """
        Enlarge the dimension of this model.

        Enlarge the spam vectors and operation matrices of model to a specified
        dimension, and return the resulting inflated model.  Spam vectors
        are zero-padded and operation matrices are padded with 1's on the diagonal
        and zeros on the off-diagonal (effectively padded by identity operation).

        Parameters
        ----------
        new_dimension : int
            the dimension of the returned model.  That is,
            the returned model will have rho and E vectors that
            have shape (new_dimension,1) and operation matrices with shape
            (new_dimension,new_dimension)

        Returns
        -------
        Model
            the increased-dimension Model
        """

        curDim = self.get_dimension()
        assert(new_dimension > curDim)

        #For now, just create a dumb default state space labels and basis for the new model:
        sslbls = [('L%d' % i,) for i in range(new_dimension)]  # interpret as independent classical levels
        dumb_basis = _DirectSumBasis([_BuiltinBasis('gm', 1)] * new_dimension,
                                     name="Unknown")  # - just act on diagonal density mx
        new_model = ExplicitOpModel(sslbls, dumb_basis, "full", self.preps._prefix, self.effects_prefix,
                                    self.operations._prefix, self.povms._prefix,
                                    self.instruments._prefix, self._sim.copy())
        #new_model._dim = new_dimension # dim will be set when elements are added
        #new_model.reset_basis() #FUTURE: maybe user can specify how increase is being done?

        addedDim = new_dimension - curDim
        vec_zeroPad = _np.zeros((addedDim, 1), 'd')

        #Increase dimension of rhoVecs and EVecs by zero-padding
        for lbl, rhoVec in self.preps.items():
            assert(len(rhoVec) == curDim)
            new_model.preps[lbl] = \
                _sv.FullSPAMVec(_np.concatenate((rhoVec, vec_zeroPad)))

        for lbl, povm in self.povms.items():
            assert(povm.dim == curDim)
            effects = [(elbl, _np.concatenate((EVec, vec_zeroPad)))
                       for elbl, EVec in povm.items()]

            if isinstance(povm, _povm.TPPOVM):
                new_model.povms[lbl] = _povm.TPPOVM(effects)
            else:
                new_model.povms[lbl] = _povm.UnconstrainedPOVM(effects)  # everything else

        #Increase dimension of gates by assuming they act as identity on additional (unknown) space
        for opLabel, gate in self.operations.items():
            assert(gate.shape == (curDim, curDim))
            newOp = _np.zeros((new_dimension, new_dimension))
            newOp[0:curDim, 0:curDim] = gate[:, :]
            for i in range(curDim, new_dimension): newOp[i, i] = 1.0
            new_model.operations[opLabel] = _op.FullDenseOp(newOp)

        for instLabel, inst in self.instruments.items():
            inst_ops = []
            for outcomeLbl, gate in inst.items():
                newOp = _np.zeros((new_dimension, new_dimension))
                newOp[0:curDim, 0:curDim] = gate[:, :]
                for i in range(curDim, new_dimension): newOp[i, i] = 1.0
                inst_ops.append((outcomeLbl, _op.FullDenseOp(newOp)))
            new_model.instruments[instLabel] = _instrument.Instrument(inst_ops)

        return new_model

    def _decrease_dimension(self, new_dimension):
        """
        Decrease the dimension of this model.

        Shrink the spam vectors and operation matrices of model to a specified
        dimension, and return the resulting model.

        Parameters
        ----------
        new_dimension : int
            the dimension of the returned model.  That is,
            the returned model will have rho and E vectors that
            have shape (new_dimension,1) and operation matrices with shape
            (new_dimension,new_dimension)

        Returns
        -------
        Model
            the decreased-dimension Model
        """
        curDim = self.get_dimension()
        assert(new_dimension < curDim)

        #For now, just create a dumb default state space labels and basis for the new model:
        sslbls = [('L%d' % i,) for i in range(new_dimension)]  # interpret as independent classical levels
        dumb_basis = _DirectSumBasis([_BuiltinBasis('gm', 1)] * new_dimension,
                                     name="Unknown")  # - just act on diagonal density mx
        new_model = ExplicitOpModel(sslbls, dumb_basis, "full", self.preps._prefix, self.effects_prefix,
                                    self.operations._prefix, self.povms._prefix,
                                    self.instruments._prefix, self._sim.copy())
        #new_model._dim = new_dimension # dim will be set when elements are added
        #new_model.reset_basis() #FUTURE: maybe user can specify how decrease is being done?

        #Decrease dimension of rhoVecs and EVecs by truncation
        for lbl, rhoVec in self.preps.items():
            assert(len(rhoVec) == curDim)
            new_model.preps[lbl] = \
                _sv.FullSPAMVec(rhoVec[0:new_dimension, :])

        for lbl, povm in self.povms.items():
            assert(povm.dim == curDim)
            effects = [(elbl, EVec[0:new_dimension, :]) for elbl, EVec in povm.items()]

            if isinstance(povm, _povm.TPPOVM):
                new_model.povms[lbl] = _povm.TPPOVM(effects)
            else:
                new_model.povms[lbl] = _povm.UnconstrainedPOVM(effects)  # everything else

        #Decrease dimension of gates by truncation
        for opLabel, gate in self.operations.items():
            assert(gate.shape == (curDim, curDim))
            newOp = _np.zeros((new_dimension, new_dimension))
            newOp[:, :] = gate[0:new_dimension, 0:new_dimension]
            new_model.operations[opLabel] = _op.FullDenseOp(newOp)

        for instLabel, inst in self.instruments.items():
            inst_ops = []
            for outcomeLbl, gate in inst.items():
                newOp = _np.zeros((new_dimension, new_dimension))
                newOp[:, :] = gate[0:new_dimension, 0:new_dimension]
                inst_ops.append((outcomeLbl, _op.FullDenseOp(newOp)))
            new_model.instruments[instLabel] = _instrument.Instrument(inst_ops)

        return new_model

    def kick(self, absmag=1.0, bias=0, seed=None):
        """
        "Kick" this model by adding to each gate a random matrix.

        The random matrices have values uniformly distributed in the interval
        [bias-absmag,bias+absmag].

        Parameters
        ----------
        absmag : float, optional
            The maximum magnitude of the entries in the "kick" matrix
            relative to bias.

        bias : float, optional
            The bias of the entries in the "kick" matrix.

        seed : int, optional
            if not None, seed numpy's random number generator with this value
            before generating random depolarizations.

        Returns
        -------
        Model
            the kicked model.
        """
        kicked_gs = self.copy()
        rndm = _np.random.RandomState(seed)
        for opLabel, gate in self.operations.items():
            delta = absmag * 2.0 * (rndm.random_sample(gate.shape) - 0.5) + bias
            kicked_gs.operations[opLabel] = _op.FullDenseOp(
                kicked_gs.operations[opLabel] + delta)

        #Note: does not alter intruments!
        return kicked_gs

    def compute_clifford_symplectic_reps(self, oplabel_filter=None):
        """
        Constructs a dictionary of the symplectic representations for all the Clifford gates in this model.

        Non-:class:`CliffordOp` gates will be ignored and their entries omitted
        from the returned dictionary.

        Parameters
        ----------
        oplabel_filter : iterable, optional
            A list, tuple, or set of operation labels whose symplectic
            representations should be returned (if they exist).

        Returns
        -------
        dict
            keys are operation labels and/or just the root names of gates
            (without any state space indices/labels).  Values are
            `(symplectic_matrix, phase_vector)` tuples.
        """
        gfilter = set(oplabel_filter) if oplabel_filter is not None \
            else None

        srep_dict = {}

        for gl, gate in self.operations.items():
            if (gfilter is not None) and (gl not in gfilter): continue

            if isinstance(gate, _op.EmbeddedOp):
                assert(isinstance(gate.embedded_op, _op.CliffordOp)), \
                    "EmbeddedClifforGate contains a non-CliffordOp!"
                lbl = gl.name  # strip state space labels off since this is a
                # symplectic rep for the *embedded* gate
                srep = (gate.embedded_op.smatrix, gate.embedded_op.svector)
            elif isinstance(gate, _op.CliffordOp):
                lbl = gl.name
                srep = (gate.smatrix, gate.svector)
            else:
                lbl = srep = None

            if srep:
                if lbl in srep_dict:
                    assert(srep == srep_dict[lbl]), \
                        "Inconsistent symplectic reps for %s label!" % lbl
                else:
                    srep_dict[lbl] = srep

        return srep_dict

    def print_info(self):
        """
        Print to stdout relevant information about this model.

        This information includes the Choi matrices and their eigenvalues.

        Returns
        -------
        None
        """
        print(self)
        print("\n")
        print("Basis = ", self.basis.name)
        print("Choi Matrices:")
        for (label, gate) in self.operations.items():
            print(("Choi(%s) in pauli basis = \n" % label,
                   _mt.mx_to_string_complex(_jt.jamiolkowski_iso(gate))))
            print(("  --eigenvals = ", sorted(
                [ev.real for ev in _np.linalg.eigvals(
                    _jt.jamiolkowski_iso(gate))]), "\n"))
        print(("Sum of negative Choi eigenvalues = ", _jt.sum_of_negative_choi_eigenvalues(self)))

    def _effect_labels_for_povm(self, povm_lbl):
        """
        Gets the effect labels corresponding to the possible outcomes of POVM label `povm_lbl`.

        Parameters
        ----------
        povm_lbl : Label
            POVM label.

        Returns
        -------
        list
            A list of strings which label the POVM outcomes.
        """
        return tuple(self.povms[povm_lbl].keys())

    def _member_labels_for_instrument(self, inst_lbl):
        """
        Gets the member labels corresponding to the possible outcomes of the instrument labeled by `inst_lbl`.

        Parameters
        ----------
        inst_lbl : Label
            Instrument label.

        Returns
        -------
        list
            A list of strings which label the instrument members.
        """
        return tuple(self.instruments[inst_lbl].keys())

    def _reinit_layerop_cache(self):
        self._layerop_cache.clear()

        # Add expanded instrument and POVM operations to cache so these are accessible to circuit calcs
        simplified_effects = _collections.OrderedDict()
        for povm_lbl, povm in self.povms.items():
            for k, e in povm.simplify_effects(povm_lbl).items():
                simplified_effects[k] = e

        simplified_ops = _collections.OrderedDict()
        for k, g in self.operations.items(): simplified_ops[k] = g
        for inst_lbl, inst in self.instruments.items():
            for k, g in inst.simplify_operations(inst_lbl).items():
                simplified_ops[k] = g

        self._layerop_cache.update(simplified_effects)
        self._layerop_cache.update(simplified_ops)


class ExplicitLayerRules(_LayerRules):
    """ Rule: layer must appear explicitly as a "primitive op" """
    def prep_layer_operator(self, model, layerlbl, cache):
        """
        Create the operator corresponding to `layerlbl`.

        Parameters
        ----------
        layerlbl : Label
            A circuit layer label.

        Returns
        -------
        POVM or SPAMVec
        """
        if layerlbl in cache: return cache[layerlbl]
        return model.preps[layerlbl]  # don't cache this - it's not a new operator

    def povm_layer_operator(self, model, layerlbl, cache):
        """
        Create the operator corresponding to `layerlbl`.

        Parameters
        ----------
        layerlbl : Label
            A circuit layer label.

        Returns
        -------
        POVM or SPAMVec
        """
        if layerlbl in cache: return cache[layerlbl]
        return model.povms[layerlbl]  # don't cache this - it's not a new operator

    def operation_layer_operator(self, model, layerlbl, cache):
        """
        Create the operator corresponding to `layerlbl`.

        Parameters
        ----------
        layerlbl : Label
            A circuit layer label.

        Returns
        -------
        LinearOperator
        """
        if layerlbl in cache: return cache[layerlbl]
        if isinstance(layerlbl, _CircuitLabel):
            dense = isinstance(model._sim, _matrixfwdsim.MatrixForwardSimulator)  # True => create dense-matrix gates
            op = self._create_op_for_circuitlabel(model, layerlbl, dense)
            cache[layerlbl] = op
            return op
        else:
            return model.operations[layerlbl]
