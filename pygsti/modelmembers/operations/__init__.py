"""
Sub-package holding model operation objects.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from .composederrorgen import ComposedErrorgen
from .composedop import ComposedOp, ComposedDenseOp
from .denseop import DenseOperator, DenseOperatorInterface
from .depolarizeop import DepolarizeOp
from .eigpdenseop import EigenvalueParamDenseOp
from .embeddederrorgen import EmbeddedErrorgen
from .embeddedop import EmbeddedOp, EmbeddedDenseOp
from .experrorgenop import ExpErrorgenOp, ExpErrorgenDenseOp
from .fulldenseop import FullDenseOp
from .fullunitaryop import FullUnitaryOp
from .lindbladerrorgen import LindbladErrorgen
from .linearop import LinearOperator
from .lpdenseop import LinearlyParamDenseOp
from .staticdenseop import StaticDenseOp
from .staticstdop import StaticStandardOp
from .stochasticop import StochasticNoiseOp
from .tpdenseop import TPDenseOp


import numpy as _np
from ...tools import basistools as _bt
from ...tools import optools as _ot


def convert(operation, to_type, basis, extra=None):
    """
    Convert operation to a new type of parameterization.

    This potentially creates a new LinearOperator object, and
    Raises ValueError for invalid conversions.

    Parameters
    ----------
    operation : LinearOperator
        LinearOperator to convert

    to_type : {"full","TP","static","static unitary","clifford",LINDBLAD}
        The type of parameterizaton to convert to.  "LINDBLAD" is a placeholder
        for the various Lindblad parameterization types.  See
        :method:`Model.set_all_parameterizations` for more details.

    basis : {'std', 'gm', 'pp', 'qt'} or Basis object
        The basis for `operation`.  Allowed values are Matrix-unit (std),
        Gell-Mann (gm), Pauli-product (pp), and Qutrit (qt)
        (or a custom basis object).

    extra : object, optional
        Additional information for conversion.

    Returns
    -------
    LinearOperator
        The converted operation, usually a distinct
        object from the operation object passed as input.
    """
    if to_type == "full":
        if isinstance(operation, FullDenseOp):
            return operation  # no conversion necessary
        else:
            return FullDenseOp(operation.to_dense())

    elif to_type == "TP":
        if isinstance(operation, TPDenseOp):
            return operation  # no conversion necessary
        else:
            return TPDenseOp(operation.to_dense())
            # above will raise ValueError if conversion cannot be done

    elif to_type == "linear":
        if isinstance(operation, LinearlyParamDenseOp):
            return operation  # no conversion necessary
        elif isinstance(operation, StaticDenseOp):
            real = _np.isclose(_np.linalg.norm(operation.imag), 0)
            return LinearlyParamDenseOp(operation.to_dense(), _np.array([]), {}, real)
        else:
            raise ValueError("Cannot convert type %s to LinearlyParamDenseOp"
                             % type(operation))

    elif to_type == "static":
        if isinstance(operation, StaticDenseOp):
            return operation  # no conversion necessary
        else:
            return StaticDenseOp(operation.to_dense())

    elif to_type == "static unitary":
        op_std = _bt.change_basis(operation, basis, 'std')
        unitary = _ot.process_mx_to_unitary(op_std)
        return StaticDenseOp(unitary, "statevec")

    elif _ot.is_valid_lindblad_paramtype(to_type):
        # e.g. "H+S terms","H+S clifford terms"

        _, evotype = _ot.split_lindblad_paramtype(to_type)
        LindbladOpType = LindbladOp \
            if evotype in ("svterm", "cterm") else \
            LindbladDenseOp

        nQubits = _np.log2(operation.dim) / 2.0
        bQubits = bool(abs(nQubits - round(nQubits)) < 1e-10)  # integer # of qubits?
        proj_basis = "pp" if (basis == "pp" or bQubits) else basis

        #FUTURE: do something like this to get a guess for the post-op unitary factor
        #  (this commented code doesn't seem to work quite right).  Such intelligence should
        #  help scenarios where the assertion below fails.
        #if isinstance(operation, DenseOperator):
        #    J = _jt.jamiolkowski_iso(operation.to_dense(), opMxBasis=basis, choiMxBasis="std")
        #    ev, U = _np.linalg.eig(operation.to_dense())
        #    imax = _np.argmax(ev)
        #    J_unitary = _np.kron(U[:,imax:imax+1], U[:,imax:imax+1].T)
        #    postfactor = _jt.jamiolkowski_iso_inv(J_unitary, choiMxBasis="std", opMxBasis=basis)
        #    unitary = _ot.process_mx_to_unitary(postfactor)
        #else:
        postfactor = None

        ret = LindbladOpType.from_operation_obj(operation, to_type, postfactor, proj_basis,
                                                basis, truncate=True, lazy=True)
        if ret.dim <= 16:  # only do this for up to 2Q operations, otherwise to_dense is too expensive
            assert(_np.linalg.norm(operation.to_dense() - ret.to_dense()) < 1e-6), \
                "Failure to create CPTP operation (maybe due the complex log's branch cut?)"
        return ret

    elif to_type == "clifford":
        if isinstance(operation, CliffordOp):
            return operation  # no conversion necessary

        # assume operation represents a unitary op (otherwise
        #  would need to change Model dim, which isn't allowed)
        return Cliffordop(Operation)

    else:
        raise ValueError("Invalid to_type argument: %s" % to_type)


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
