"""
The DenseOperator class and supporting functionality.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from collections import OrderedDict
import copy as _copy

import numpy as _np
import scipy.sparse as _sps

from pygsti.modelmembers.operations.linearop import LinearOperator as _LinearOperator
from pygsti.evotypes import Evotype as _Evotype
from pygsti.baseobjs import statespace as _statespace
from pygsti.baseobjs.basis import Basis as _Basis
from pygsti.tools import basistools as _bt
from pygsti.tools import matrixtools as _mt
from pygsti.tools import optools as _ot


def finite_difference_deriv_wrt_params(operation, wrt_filter, eps=1e-7):
    """
    Computes a finite-difference Jacobian for a LinearOperator object.

    The returned value is a matrix whose columns are the vectorized
    derivatives of the flattened operation matrix with respect to a single
    operation parameter, matching the format expected from the operation's
    `deriv_wrt_params` method.

    Parameters
    ----------
    operation : LinearOperator
        The operation object to compute a Jacobian for.

    wrt_filter : list or numpy.ndarray
        List of parameter indices to filter the result by (as though
        derivative is only taken with respect to these parameters).

    eps : float, optional
        The finite difference step to use.

    Returns
    -------
    numpy.ndarray
        An M by N matrix where M is the number of operation elements and
        N is the number of operation parameters.
    """
    dim = operation.dim
    #operation.from_vector(operation.to_vector()) #ensure we call from_vector w/close=False first
    op2 = operation.copy()
    p = operation.to_vector()
    fd_deriv = _np.empty((dim, dim, operation.num_params), operation.dtype)

    for i in range(operation.num_params):
        p_plus_dp = p.copy()
        p_plus_dp[i] += eps
        op2.from_vector(p_plus_dp)
        fd_deriv[:, :, i] = (op2 - operation) / eps

    fd_deriv.shape = [dim**2, operation.num_params]
    if wrt_filter is None:
        return fd_deriv
    else:
        return _np.take(fd_deriv, wrt_filter, axis=1)


def check_deriv_wrt_params(operation, deriv_to_check=None, wrt_filter=None, eps=1e-7):
    """
    Checks the `deriv_wrt_params` method of a LinearOperator object.

    This routine is meant to be used as an aid in testing and debugging
    operation classes by comparing the finite-difference Jacobian that
    *should* be returned by `operation.deriv_wrt_params` with the one that
    actually is.  A ValueError is raised if the two do not match.

    Parameters
    ----------
    operation : LinearOperator
        The operation object to test.

    deriv_to_check : numpy.ndarray or None, optional
        If not None, the Jacobian to compare against the finite difference
        result.  If None, `operation.deriv_wrt_parms()` is used.  Setting this
        argument can be useful when the function is called *within* a LinearOperator
        class's `deriv_wrt_params()` method itself as a part of testing.

    wrt_filter : list or numpy.ndarray
        List of parameter indices to filter the result by (as though
        derivative is only taken with respect to these parameters).

    eps : float, optional
        The finite difference step to use.

    Returns
    -------
    None
    """
    fd_deriv = finite_difference_deriv_wrt_params(operation, wrt_filter, eps)
    if deriv_to_check is None:
        deriv_to_check = operation.deriv_wrt_params()

    #print("Deriv shapes = %s and %s" % (str(fd_deriv.shape),
    #                                    str(deriv_to_check.shape)))
    #print("finite difference deriv = \n",fd_deriv)
    #print("deriv_wrt_params deriv = \n",deriv_to_check)
    #print("deriv_wrt_params - finite diff deriv = \n",
    #      deriv_to_check - fd_deriv)
    for i in range(deriv_to_check.shape[0]):
        for j in range(deriv_to_check.shape[1]):
            diff = abs(deriv_to_check[i, j] - fd_deriv[i, j])
            if diff > 10 * eps:
                print("deriv_chk_mismatch: (%d,%d): %g (comp) - %g (fd) = %g" %
                      (i, j, deriv_to_check[i, j], fd_deriv[i, j], diff))  # pragma: no cover

    if _np.linalg.norm(fd_deriv - deriv_to_check) / fd_deriv.size > 10 * eps:
        raise ValueError("Failed check of deriv_wrt_params:\n"
                         " norm diff = %g" %
                         _np.linalg.norm(fd_deriv - deriv_to_check))  # pragma: no cover


class DenseOperatorInterface(object):
    """
    Adds a numpy-array-mimicing interface onto an operation object.
    """

    def __init__(self):
        pass

    @property
    def _ptr(self):
        raise NotImplementedError("Derived classes must implement the _ptr property!")

    def _ptr_has_changed(self):
        """ Derived classes should override this function to handle rep updates
            when the `_ptr` property is changed. """
        pass

    def to_array(self):
        """
        Return the array used to identify this operation within its range of possible values.

        For instance, if the operation is a unitary operation, this returns a
        unitary matrix regardless of the evolution type.  The related :method:`to_dense`
        method, in contrast, returns the dense representation of the operation, which
        varies by evolution type.

        Note: for efficiency, this doesn't copy the underlying data, so
        the caller should copy this data before modifying it.

        Returns
        -------
        numpy.ndarray
        """
        return _np.asarray(self._ptr)
        # *must* be a numpy array for Cython arg conversion

    def to_sparse(self, on_space='minimal'):
        """
        Return the operation as a sparse matrix.

        Parameters
        ----------
        on_space : {'minimal', 'Hilbert', 'HilbertSchmidt'}
            The space that the returned dense operation acts upon.  For unitary matrices and bra/ket vectors,
            use `'Hilbert'`.  For superoperator matrices and super-bra/super-ket vectors use `'HilbertSchmidt'`.
            `'minimal'` means that `'Hilbert'` is used if possible given this operator's evolution type, and
            otherwise `'HilbertSchmidt'` is used.

        Returns
        -------
        scipy.sparse.csr_matrix
        """
        return _sps.csr_matrix(self.to_dense(on_space))

    def __copy__(self):
        # We need to implement __copy__ because we defer all non-existing
        # attributes to self.base (a numpy array) which *has* a __copy__
        # implementation that we don't want to use, as it results in just a
        # copy of the numpy array.
        cls = self.__class__
        cpy = cls.__new__(cls)
        cpy.__dict__.update(self.__dict__)
        return cpy

    def __deepcopy__(self, memo):
        # We need to implement __deepcopy__ because we defer all non-existing
        # attributes to self.base (a numpy array) which *has* a __deepcopy__
        # implementation that we don't want to use, as it results in just a
        # copy of the numpy array.
        cls = self.__class__
        cpy = cls.__new__(cls)
        memo[id(self)] = cpy
        for k, v in self.__dict__.items():
            setattr(cpy, k, _copy.deepcopy(v, memo))
        return cpy

    #Access to underlying ndarray
    def __getitem__(self, key):
        self.dirty = True
        return self._ptr.__getitem__(key)

    def __getslice__(self, i, j):
        self.dirty = True
        return self.__getitem__(slice(i, j))  # Called for A[:]

    def __setitem__(self, key, val):
        self.dirty = True
        ret = self._ptr.__setitem__(key, val)
        self._ptr_has_changed()
        return ret

    def __getattr__(self, attr):
        #use __dict__ so no chance for recursive __getattr__
        #ret = getattr(self.__dict__['_rep'].base, attr)
        ret = getattr(self._ptr, attr)
        self.dirty = True
        return ret

    def __str__(self):
        s = "%s with shape %s\n" % (self.__class__.__name__, str(self._ptr.shape))
        s += _mt.mx_to_string(self._ptr, width=4, prec=2)
        return s

    #Mimic array behavior
    def __pos__(self): return self._ptr
    def __neg__(self): return -self._ptr
    def __abs__(self): return abs(self._ptr)
    def __add__(self, x): return self._ptr + x
    def __radd__(self, x): return x + self._ptr
    def __sub__(self, x): return self._ptr - x
    def __rsub__(self, x): return x - self._ptr
    def __mul__(self, x): return self._ptr * x
    def __rmul__(self, x): return x * self._ptr
    def __truediv__(self, x): return self._ptr / x
    def __rtruediv__(self, x): return x / self._ptr
    def __floordiv__(self, x): return self._ptr // x
    def __rfloordiv__(self, x): return x // self._ptr
    def __pow__(self, x): return self._ptr ** x
    def __eq__(self, x): return self._ptr == x
    def __len__(self): return len(self._ptr)
    def __int__(self): return int(self._ptr)
    def __long__(self): return int(self._ptr)
    def __float__(self): return float(self._ptr)
    def __complex__(self): return complex(self._ptr)


class DenseOperator(DenseOperatorInterface, _LinearOperator):
    """
    TODO: update docstring
    An operator that behaves like a dense super-operator matrix.

    This class is the common base class for more specific dense operators.

    Parameters
    ----------
    mx : numpy.ndarray
        The operation as a dense process matrix.

    evotype : Evotype or str
        The evolution type.  The special value `"default"` is equivalent
        to specifying the value of `pygsti.evotypes.Evotype.default_evotype`.

    state_space : StateSpace, optional
        The state space for this operation.  If `None` a default state space
        with the appropriate number of qubits is used.

    Attributes
    ----------
    base : numpy.ndarray
        Direct access to the underlying process matrix data.
    """

    def __init__(self, mx, evotype, state_space=None):
        """ Initialize a new LinearOperator """
        mx = _LinearOperator.convert_to_matrix(mx)
        state_space = _statespace.default_space_for_dim(mx.shape[0]) if (state_space is None) \
            else _statespace.StateSpace.cast(state_space)
        evotype = _Evotype.cast(evotype)
        rep = evotype.create_dense_superop_rep(mx, state_space)
        _LinearOperator.__init__(self, rep, evotype)
        DenseOperatorInterface.__init__(self)

    @property
    def _ptr(self):
        return self._rep.base

    def _ptr_has_changed(self):
        """ Derived classes should override this function to handle rep updates
            when the `_ptr` property is changed. """
        self._rep.base_has_changed()

    def to_dense(self, on_space='minimal'):
        """
        Return the dense array used to represent this operation within its evolution type.

        Note: for efficiency, this doesn't copy the underlying data, so
        the caller should copy this data before modifying it.

        Parameters
        ----------
        on_space : {'minimal', 'Hilbert', 'HilbertSchmidt'}
            The space that the returned dense operation acts upon.  For unitary matrices and bra/ket vectors,
            use `'Hilbert'`.  For superoperator matrices and super-bra/super-ket vectors use `'HilbertSchmidt'`.
            `'minimal'` means that `'Hilbert'` is used if possible given this operator's evolution type, and
            otherwise `'HilbertSchmidt'` is used.

        Returns
        -------
        numpy.ndarray
        """
        return self._rep.to_dense(on_space)  # both types of possible reps implement 'to_dense'

    def to_memoized_dict(self, mmg_memo):
        """Create a serializable dict with references to other objects in the memo.

        Parameters
        ----------
        mmg_memo: dict
            Memo dict from a ModelMemberGraph, i.e. keys are object ids and values
            are ModelMemberGraphNodes (which contain the serialize_id). This is NOT
            the same as other memos in ModelMember (e.g. copy, allocate_gpindices, etc.).

        Returns
        -------
        mm_dict: dict
            A dict representation of this ModelMember ready for serialization
            This must have at least the following fields:
                module, class, submembers, params, state_space, evotype
            Additional fields may be added by derived classes.
        """
        mm_dict = super().to_memoized_dict(mmg_memo)
        mm_dict['dense_matrix'] = self._encodemx(self.to_dense())

        return mm_dict

    @classmethod
    def _from_memoized_dict(cls, mm_dict, serial_memo):
        m = cls._decodemx(mm_dict['dense_matrix'])
        state_space = _statespace.StateSpace.from_nice_serialization(mm_dict['state_space'])
        return cls(m, mm_dict['evotype'], state_space)

    def _oneline_contents(self):
        """ Summarizes the contents of this object in a single line.  Does not summarize submembers. """
        dims = tuple(self.to_dense().shape)
        return "dense %d x %d superop matrix" % dims

    def _is_similar(self, other, rtol, atol):
        """ Returns True if `other` model member (which it guaranteed to be the same type as self) has
            the same local structure, i.e., not considering parameter values or submembers """
        return self._ptr.shape == other._ptr.shape  # similar (up to params) if have same data shape


class DenseUnitaryOperator(DenseOperatorInterface, _LinearOperator):
    """
    TODO: update docstring
    An operator that behaves like a dense (unitary) operator matrix.

    This class is the common base class for more specific dense operators.

    Parameters
    ----------
    mx : numpy.ndarray
        The operation as a dense process matrix.

    basis : Basis or {'pp','gm','std'}, optional
        The basis used to construct the Hilbert-Schmidt space representation
        of this state as a super-operator.

    evotype : Evotype or str
        The evolution type.  The special value `"default"` is equivalent
        to specifying the value of `pygsti.evotypes.Evotype.default_evotype`.

    state_space : StateSpace, optional
        The state space for this operation.  If `None` a default state space
        with the appropriate number of qubits is used.

    Attributes
    ----------
    base : numpy.ndarray
        Direct access to the underlying process matrix data.
    """

    def __init__(self, mx, basis, evotype, state_space):
        """ Initialize a new LinearOperator """
        mx = _LinearOperator.convert_to_matrix(mx)
        state_space = _statespace.default_space_for_udim(mx.shape[0]) if (state_space is None) \
            else _statespace.StateSpace.cast(state_space)
        basis = _Basis.cast(basis, state_space.dim)  # basis for Hilbert-Schmidt (superop) space
        evotype = _Evotype.cast(evotype)

        #Try to create a dense unitary rep.  If this fails, see if a dense superop rep
        # can be created, as this type of rep can also hold arbitrary unitary ops.
        try:
            rep = evotype.create_dense_unitary_rep(mx, basis, state_space)
            self._reptype = 'unitary'
            self._unitary = None
        except Exception:
            if mx.shape[0] == basis.dim and _np.linalg.norm(mx.imag) < 1e-10:
                # Special case when a *superop* was provided instead of a unitary mx
                superop_mx = mx.real  # used as a convenience case that really shouldn't be used
            else:
                superop_mx = _bt.change_basis(_ot.unitary_to_process_mx(mx), 'std', basis)
            rep = evotype.create_dense_superop_rep(superop_mx, state_space)
            self._reptype = 'superop'
            self._unitary = mx
        self._basis = basis

        _LinearOperator.__init__(self, rep, evotype)
        DenseOperatorInterface.__init__(self)

    @property
    def _ptr(self):
        """Gives a handle/pointer to the base numpy array that this object can be accessed as"""
        return self._rep.base if self._reptype == 'unitary' else self._unitary

    def _ptr_has_changed(self):
        """ Derived classes should override this function to handle rep updates
            when the `_ptr` property is changed. """
        if self._reptype == 'superop':
            self._rep.base[:, :] = _bt.change_basis(_ot.unitary_to_process_mx(self._unitary), 'std', self._basis)
        self._rep.base_has_changed()

    def to_dense(self, on_space='minimal'):
        """
        Return the dense array used to represent this operation within its evolution type.

        Note: for efficiency, this doesn't copy the underlying data, so
        the caller should copy this data before modifying it.

        Parameters
        ----------
        on_space : {'minimal', 'Hilbert', 'HilbertSchmidt'}
            The space that the returned dense operation acts upon.  For unitary matrices and bra/ket vectors,
            use `'Hilbert'`.  For superoperator matrices and super-bra/super-ket vectors use `'HilbertSchmidt'`.
            `'minimal'` means that `'Hilbert'` is used if possible given this operator's evolution type, and
            otherwise `'HilbertSchmidt'` is used.

        Returns
        -------
        numpy.ndarray
        """
        return self._rep.to_dense(on_space)  # both types of possible reps implement 'to_dense'

    def transform_inplace(self, s):
        """
        Update operation matrix `O` with `inv(s) * O * s`.

        Generally, the transform function updates the *parameters* of
        the operation such that the resulting operation matrix is altered as
        described above.  If such an update cannot be done (because
        the operation parameters do not allow for it), ValueError is raised.

        Parameters
        ----------
        s : GaugeGroupElement
            A gauge group element which specifies the "s" matrix
            (and it's inverse) used in the above similarity transform.

        Returns
        -------
        None
        """
        from pygsti.models import gaugegroup as _gaugegroup
        if isinstance(s, _gaugegroup.UnitaryGaugeGroupElement) or \
           isinstance(s, _gaugegroup.TPSpamGaugeGroupElement):

            #Just to this the brute force way for now - there should be a more elegant & faster way!
            U = s.transform_matrix
            Uinv = s.transform_matrix_inverse

            my_superop_mx = _bt.change_basis(_ot.unitary_to_process_mx(self._ptr), 'std', self._basis)  # to_dense()?
            my_superop_mx = _mt.safe_dot(Uinv, _mt.safe_dot(my_superop_mx, U))

            self._ptr[:, :] = _ot.process_mx_to_unitary(_bt.change_basis(my_superop_mx, self._basis, 'std'))
            self._ptr_has_changed()
            self.dirty = True
        else:
            raise ValueError("Invalid transform for this DenseUnitaryOperation: type %s" % str(type(s)))

    def spam_transform_inplace(self, s, typ):
        """
        Update operation matrix `O` with `inv(s) * O` OR `O * s`, depending on the value of `typ`.

        This functions as `transform_inplace(...)` but is used when this
        Lindblad-parameterized operation is used as a part of a SPAM
        vector.  When `typ == "prep"`, the spam vector is assumed
        to be `rho = dot(self, <spamvec>)`, which transforms as
        `rho -> inv(s) * rho`, so `self -> inv(s) * self`. When
        `typ == "effect"`, `e.dag = dot(e.dag, self)` (not that
        `self` is NOT `self.dag` here), and `e.dag -> e.dag * s`
        so that `self -> self * s`.

        Parameters
        ----------
        s : GaugeGroupElement
            A gauge group element which specifies the "s" matrix
            (and it's inverse) used in the above similarity transform.

        typ : { 'prep', 'effect' }
            Which type of SPAM vector is being transformed (see above).

        Returns
        -------
        None
        """
        assert(typ in ('prep', 'effect')), "Invalid `typ` argument: %s" % typ

        from pygsti.models import gaugegroup as _gaugegroup
        if isinstance(s, _gaugegroup.UnitaryGaugeGroupElement) or \
           isinstance(s, _gaugegroup.TPSpamGaugeGroupElement):
            U = s.transform_matrix
            Uinv = s.transform_matrix_inverse

            #Just to this the brute force way for now - there should be a more elegant & faster way!
            U = s.transform_matrix
            Uinv = s.transform_matrix_inverse

            my_superop_mx = _bt.change_basis(_ot.unitary_to_process_mx(self._ptr), 'std', self._basis)  # to_dense()?

            #Note: this code may need to be tweaked to work with sparse matrices
            if typ == "prep":
                my_superop_mx = _mt.safe_dot(Uinv, my_superop_mx)
            else:
                my_superop_mx = _mt.safe_dot(my_superop_mx, U)

            self._ptr[:, :] = _ot.process_mx_to_unitary(_bt.change_basis(my_superop_mx, self._basis, 'std'))
            self._ptr_has_changed()
            self.dirty = True
        else:
            raise ValueError("Invalid transform for this DenseUnitaryOperation: type %s" % str(type(s)))

    def to_memoized_dict(self, mmg_memo):
        """Create a serializable dict with references to other objects in the memo.

        Parameters
        ----------
        mmg_memo: dict
            Memo dict from a ModelMemberGraph, i.e. keys are object ids and values
            are ModelMemberGraphNodes (which contain the serialize_id). This is NOT
            the same as other memos in ModelMember (e.g. copy, allocate_gpindices, etc.).

        Returns
        -------
        mm_dict: dict
            A dict representation of this ModelMember ready for serialization
            This must have at least the following fields:
                module, class, submembers, params, state_space, evotype
            Additional fields may be added by derived classes.
        """
        mm_dict = super().to_memoized_dict(mmg_memo)

        mm_dict['dense_matrix'] = self.to_dense('Hilbert').tolist()
        mm_dict['basis'] = self._basis.to_nice_serialization()

        return mm_dict

    @classmethod
    def _from_memoized_dict(cls, mm_dict, serial_memo):
        m = _np.array(mm_dict['dense_matrix'])
        state_space = _statespace.StateSpace.from_nice_serialization(mm_dict['state_space'])
        basis = _Basis.from_nice_serialization(mm_dict['basis'])
        return cls(m, basis, mm_dict['evotype'], state_space)

    def _oneline_contents(self):
        """ Summarizes the contents of this object in a single line.  Does not summarize submembers. """
        dims = tuple(self.to_dense().shape)
        return "dense %d x %d op matrix" % dims

    def _is_similar(self, other, rtol, atol):
        """ Returns True if `other` model member (which it guaranteed to be the same type as self) has
            the same local structure, i.e., not considering parameter values or submembers """
        return self._ptr.shape == other._ptr.shape  # similar (up to params) if have same data shape
