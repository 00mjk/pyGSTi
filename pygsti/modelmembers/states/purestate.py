import numpy as _np
import itertools as _itertools
import functools as _functools

from .state import State as _State
from .staticstate import StaticState as _StaticState
from .. import modelmember as _modelmember
from ...evotype import Evotype as _Evotype
from ...objects import term as _term
from ...tools import optools as _ot
from ...tools import basistools as _bt
from ...objects.polynomial import Polynomial as _Polynomial


#TODO: figure out what to do with this class when we wire up term calcs??
# may need this to be an effect class too?
class EmbeddedPureState(_State):
    """
    TODO: update docstring
    A SPAM vector that is a rank-1 density matrix.

    This is essentially a pure state that evolves according to one of the
    density matrix evolution types ("denstiymx", "svterm", and "cterm").  It is
    parameterized by a contained pure-state SPAMVec which evolves according to a
    state vector evolution type ("statevec" or "stabilizer").

    Parameters
    ----------
    pure_state_vec : array_like or SPAMVec
        a 1D numpy array or object representing the pure state.  This object
        sets the parameterization and dimension of this SPAM vector (if
        `pure_state_vec`'s dimension is `d`, then this SPAM vector's
        dimension is `d^2`).  Assumed to be a complex vector in the
        standard computational basis.

    evotype : {'densitymx', 'svterm', 'cterm'}
        The evolution type of this SPAMVec.  Note that the evotype of
        `pure_state_vec` must be compatible with this value.  In particular,
        `pure_state_vec` must have an evotype of `"statevec"` (then allowed
        values are `"densitymx"` and `"svterm"`) or `"stabilizer"` (then
        the only allowed value is `"cterm"`).

    dm_basis : {'std', 'gm', 'pp', 'qt'} or Basis object
        The basis for this SPAM vector - that is, for the *density matrix*
        corresponding to `pure_state_vec`.  Allowed values are Matrix-unit
        (std),  Gell-Mann (gm), Pauli-product (pp), and Qutrit (qt)
        (or a custom basis object).
    """

    def __init__(self, pure_state, evotype='densitymx', dm_basis='pp'):
        if not isinstance(pure_state, _State):
            pure_state = _StaticState(_State._to_vector(pure_state), 'statevec')
        self.pure_state = pure_state
        self.basis = dm_basis  # only used for dense conversion

        evotype = _Evotype.cast(evotype)
        rep = evotype.create_state_rep()
        rep.init_from_dense_purevec(pure_state)

        #TODO: remove
        #pure_evo = pure_state._evotype
        #if pure_evo == "statevec":
        #    if evotype not in ("densitymx", "svterm"):
        #        raise ValueError(("`evotype` arg must be 'densitymx' or 'svterm'"
        #                          " when `pure_state_vec` evotype is 'statevec'"))
        #elif pure_evo == "stabilizer":
        #    if evotype not in ("cterm",):
        #        raise ValueError(("`evotype` arg must be 'densitymx' or 'svterm'"
        #                          " when `pure_state_vec` evotype is 'statevec'"))
        #else:
        #    raise ValueError("`pure_state_vec` evotype must be 'statevec' or 'stabilizer' (not '%s')" % pure_evo)

        #Create representation
        _State.__init__(self, rep, evotype)

    def to_dense(self, scratch=None):
        """
        Return this SPAM vector as a (dense) numpy array.

        The memory in `scratch` maybe used when it is not-None.

        Parameters
        ----------
        scratch : numpy.ndarray, optional
            scratch space available for use.

        Returns
        -------
        numpy.ndarray
        """
        dmVec_std = _ot.state_to_dmvec(self.pure_state.to_dense())
        return _bt.change_basis(dmVec_std, 'std', self.basis)

    def taylor_order_terms(self, order, max_polynomial_vars=100, return_coeff_polys=False):
        """
        Get the `order`-th order Taylor-expansion terms of this SPAM vector.

        This function either constructs or returns a cached list of the terms at
        the given order.  Each term is "rank-1", meaning that it is a state
        preparation followed by or POVM effect preceded by actions on a
        density matrix `rho` of the form:

        `rho -> A rho B`

        The coefficients of these terms are typically polynomials of the
        SPAMVec's parameters, where the polynomial's variable indices index the
        *global* parameters of the SPAMVec's parent (usually a :class:`Model`)
        , not the SPAMVec's local parameter array (i.e. that returned from
        `to_vector`).

        Parameters
        ----------
        order : int
            The order of terms to get.

        max_polynomial_vars : int, optional
            maximum number of variables the created polynomials can have.

        return_coeff_polys : bool
            Whether a parallel list of locally-indexed (using variable indices
            corresponding to *this* object's parameters rather than its parent's)
            polynomial coefficients should be returned as well.

        Returns
        -------
        terms : list
            A list of :class:`RankOneTerm` objects.
        coefficients : list
            Only present when `return_coeff_polys == True`.
            A list of *compact* polynomial objects, meaning that each element
            is a `(vtape,ctape)` 2-tuple formed by concatenating together the
            output of :method:`Polynomial.compact`.
        """
        if self.num_params > 0:
            raise ValueError(("PureStateSPAMVec.taylor_order_terms(...) is only "
                              "implemented for the case when its underlying "
                              "pure state vector has 0 parameters (is static)"))

        if order == 0:  # only 0-th order term exists (assumes static pure_state_vec)
            purevec = self.pure_state
            coeff = _Polynomial({(): 1.0}, max_polynomial_vars)
            if self._prep_or_effect == "prep":
                terms = [_term.RankOnePolynomialPrepTerm.create_from(coeff, purevec, purevec, self._evotype)]
            else:
                terms = [_term.RankOnePolynomialEffectTerm.create_from(coeff, purevec, purevec, self._evotype)]

            if return_coeff_polys:
                coeffs_as_compact_polys = coeff.compact(complex_coeff_tape=True)
                return terms, coeffs_as_compact_polys
            else:
                return terms
        else:
            if return_coeff_polys:
                vtape = _np.empty(0, _np.int64)
                ctape = _np.empty(0, complex)
                return [], (vtape, ctape)
            else:
                return []

    #TODO REMOVE
    #def get_direct_order_terms(self, order, base_order):
    #    """
    #    Parameters
    #    ----------
    #    order : int
    #        The order of terms to get.
    #
    #    Returns
    #    -------
    #    list
    #        A list of :class:`RankOneTerm` objects.
    #    """
    #    if self.num_params > 0:
    #        raise ValueError(("PureStateSPAMVec.taylor_order_terms(...) is only "
    #                          "implemented for the case when its underlying "
    #                          "pure state vector has 0 parameters (is static)"))
    #
    #    if order == 0: # only 0-th order term exists (assumes static pure_state_vec)
    #        if self._evotype == "svterm":  tt = "dense"
    #        elif self._evotype == "cterm": tt = "clifford"
    #        else: raise ValueError("Invalid evolution type %s for calling `taylor_order_terms`" % self._evotype)
    #
    #        purevec = self.pure_state_vec
    #        terms = [ _term.RankOneTerm(1.0, purevec, purevec, tt) ]
    #    else:
    #        terms = []
    #    return terms

    @property
    def parameter_labels(self):
        """
        An array of labels (usually strings) describing this model member's parameters.
        """
        return self.pure_state.parameter_labels

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this SPAM vector.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return self.pure_state.num_params

    def to_vector(self):
        """
        Get the SPAM vector parameters as an array of values.

        Returns
        -------
        numpy array
            The parameters as a 1D array with length num_params().
        """
        return self.pure_state.to_vector()

    def from_vector(self, v, close=False, dirty_value=True):
        """
        Initialize the SPAM vector using a 1D array of parameters.

        Parameters
        ----------
        v : numpy array
            The 1D vector of SPAM vector parameters.  Length
            must == num_params()

        close : bool, optional
            Whether `v` is close to this SPAM vector's current
            set of parameters.  Under some circumstances, when this
            is true this call can be completed more quickly.

        dirty_value : bool, optional
            The value to set this object's "dirty flag" to before exiting this
            call.  This is passed as an argument so it can be updated *recursively*.
            Leave this set to `True` unless you know what you're doing.

        Returns
        -------
        None
        """
        self.pure_state.from_vector(v, close, dirty_value)
        #Update dense rep if one is created (TODO)

    def deriv_wrt_params(self, wrt_filter=None):
        """
        The element-wise derivative this SPAM vector.

        Construct a matrix whose columns are the derivatives of the SPAM vector
        with respect to a single param.  Thus, each column is of length
        dimension and there is one column per SPAM vector parameter.
        An empty 2D array in the StaticSPAMVec case (num_params == 0).

        Parameters
        ----------
        wrt_filter : list or numpy.ndarray
            List of parameter indices to take derivative with respect to.
            (None means to use all the this operation's parameters.)

        Returns
        -------
        numpy array
            Array of derivatives, shape == (dimension, num_params)
        """
        raise NotImplementedError("Still need to work out derivative calculation of PureStateSPAMVec")

    def has_nonzero_hessian(self):
        """
        Whether this SPAM vector has a non-zero Hessian with respect to its parameters.

        Returns
        -------
        bool
        """
        return self.pure_state.has_nonzero_hessian()

    def submembers(self):
        """
        Get the ModelMember-derived objects contained in this one.

        Returns
        -------
        list
        """
        return [self.pure_state]

    def __str__(self):
        s = "Pure-state spam vector with length %d holding:\n" % self.dim
        s += "  " + str(self.pure_state)
        return s
