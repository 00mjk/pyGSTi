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

import numpy as _np
import scipy.sparse as _sps
import copy as _copy
from .linearop import LinearOperator as _LinearOperator

from ...evotypes import Evotype as _Evotype
from ...models import statespace as _statespace
from ...tools import matrixtools as _mt
from ...objects.basis import Basis as _Basis


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

    The object's ._rep must be a *dense* representation (with a
    .base that is a numpy array).

    This class is distinct from DenseOperator because there are some
    operators, e.g. LindbladOp, that *can* but don't *always* have
    a dense representation.  With such types, a base class allows
    a 'dense_rep' argument to its constructor and a derived class
    sets this to True *and* inherits from DenseOperatorInterface.
    If would not be appropriate to inherit from DenseOperator because
    this is a standalone operator with it's own (dense) ._rep, etc.
    """

    def __init__(self):
        pass

    @property
    def _ptr(self):
        return self._rep.base

    def deriv_wrt_params(self, wrt_filter=None):
        """
        The element-wise derivative this operation.

        Constructs a matrix whose columns are the vectorized
        derivatives of the flattened operation matrix with respect to a
        single operation parameter.  Thus, each column is of length
        op_dim^2 and there is one column per operation parameter. An
        empty 2D array in the StaticDenseOp case (num_params == 0).

        Parameters
        ----------
        wrt_filter : list or numpy.ndarray
            List of parameter indices to take derivative with respect to.
            (None means to use all the this operation's parameters.)

        Returns
        -------
        numpy array
            Array of derivatives with shape (dimension^2, num_params)
        """
        return finite_difference_deriv_wrt_params(self, wrt_filter, eps=1e-7)

    def to_dense(self):
        """
        Return this operation as a dense matrix.

        Note: for efficiency, this doesn't copy the underlying data, so
        the caller should copy this data before modifying it.

        Returns
        -------
        numpy.ndarray
        """
        return _np.asarray(self._ptr)
        # *must* be a numpy array for Cython arg conversion

    def to_sparse(self):
        """
        Return the operation as a sparse matrix.

        Returns
        -------
        scipy.sparse.csr_matrix
        """
        return _sps.csr_matrix(self.to_dense())

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
        return self._ptr.__setitem__(key, val)

    def __getattr__(self, attr):
        #use __dict__ so no chance for recursive __getattr__
        ret = getattr(self.__dict__['_rep'].base, attr)
        self.dirty = True
        return ret

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


class BasedDenseOperatorInterface(DenseOperatorInterface):
    """
    A DenseOperatorInterface that uses self.base instead of self._rep.base as the "base pointer" to data.

    This is used by the TPDenseOp class, for example, which has a .base
    that is different from its ._rep.base.
    """
    def __init__(self, base):
        self.base = base

    @property
    def _ptr(self):
        return self.base


class DenseOperator(BasedDenseOperatorInterface, _LinearOperator):
    """
    TODO: update docstring
    An operator that behaves like a dense operation matrix.

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

    def __init__(self, mx, evotype, state_space):
        """ Initialize a new LinearOperator """
        state_space = _statespace.default_space_for_dim(mx.shape[0]) if (state_space is None) \
            else _statespace.StateSpace.cast(state_space)
        evotype = _Evotype.cast(evotype)
        rep = evotype.create_dense_rep(mx, state_space)
        _LinearOperator.__init__(self, rep, evotype)
        BasedDenseOperatorInterface.__init__(self, self._rep.base)
        # "Based" interface requires this and derived classes to have a .base attribute
        # or property that points to the data to interface with.  This gives derived classes
        # flexibility in defining something other than self._rep.base to be used (see TPDenseOp).

    def __str__(self):
        s = "%s with shape %s\n" % (self.__class__.__name__, str(self.base.shape))
        s += _mt.mx_to_string(self.base, width=4, prec=2)
        return s


class DenseUnitaryOperator(BasedDenseOperatorInterface, _LinearOperator):
    """
    TODO: update docstring
    An operator that behaves like a dense operation matrix.

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
        state_space = _statespace.default_space_for_dim(mx.shape[0]) if (state_space is None) \
            else _statespace.StateSpace.cast(state_space)
        basis = _Basis.cast(basis, state_space.dim)  # basis for Hilbert-Schmidt (superop) space
        rep = evotype.create_denseunitary_rep(mx, basis, state_space)
        evotype = _Evotype.cast(evotype)
        _LinearOperator.__init__(self, rep, evotype)
        BasedDenseOperatorInterface.__init__(self, self._rep.base)
        # "Based" interface requires this and derived classes to have a .base attribute
        # or property that points to the data to interface with.  This gives derived classes
        # flexibility in defining something other than self._rep.base to be used (see TPDenseOp).

    def __str__(self):
        s = "%s with shape %s\n" % (self.__class__.__name__, str(self.base.shape))
        s += _mt.mx_to_string(self.base, width=4, prec=2)
        return s
