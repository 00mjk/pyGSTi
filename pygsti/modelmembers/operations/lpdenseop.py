class LinearlyParameterizedElementTerm(object):
    """
    Encapsulates a single term within a LinearlyParamDenseOp.

    Parameters
    ----------
    coeff : float, optional
        The term's coefficient

    param_indices : list
        A list of integers, specifying which parameters are muliplied
        together (and finally, with `coeff`) to form this term.
    """

    def __init__(self, coeff=1.0, param_indices=[]):
        """
        Create a new LinearlyParameterizedElementTerm

        Parameters
        ----------
        coeff : float, optional
            The term's coefficient

        param_indices : list
            A list of integers, specifying which parameters are muliplied
            together (and finally, with `coeff`) to form this term.
        """
        self.coeff = coeff
        self.paramIndices = param_indices

    def copy(self):
        """
        Copy this term.

        Returns
        -------
        LinearlyParameterizedElementTerm
        """
        return LinearlyParameterizedElementTerm(self.coeff, self.paramIndices[:])


class LinearlyParamDenseOp(DenseOperator):
    """
    An operation matrix parameterized such that each element depends only linearly on any parameter.

    Parameters
    ----------
    basematrix : numpy array
        a square 2D numpy array that acts as the starting point when
        constructin the operation's matrix.  The shape of this array sets
        the dimension of the operation.

    parameter_array : numpy array
        a 1D numpy array that holds the all the parameters for this
        operation.  The shape of this array sets is what is returned by
        value_dimension(...).

    parameter_to_base_indices_map : dict
        A dictionary with keys == index of a parameter
        (i.e. in parameter_array) and values == list of 2-tuples
        indexing potentially multiple operation matrix coordinates
        which should be set equal to this parameter.

    left_transform : numpy array or None, optional
        A 2D array of the same shape as basematrix which left-multiplies
        the base matrix after parameters have been evaluated.  Defaults to
        no transform_inplace.

    right_transform : numpy array or None, optional
        A 2D array of the same shape as basematrix which right-multiplies
        the base matrix after parameters have been evaluated.  Defaults to
        no transform_inplace.

    real : bool, optional
        Whether or not the resulting operation matrix, after all
        parameter evaluation and left & right transforms have
        been performed, should be real.  If True, ValueError will
        be raised if the matrix contains any complex or imaginary
        elements.

    evotype : {"statevec", "densitymx", "auto"}
        The evolution type.  If `"auto"`, then `"statevec"` is used if `real == False`,
        otherwise `"densitymx"` is used.
    """

    def __init__(self, base_matrix, parameter_array, parameter_to_base_indices_map,
                 left_transform=None, right_transform=None, real=False, evotype="auto"):
        """
        Initialize a LinearlyParamDenseOp object.

        Parameters
        ----------
        basematrix : numpy array
            a square 2D numpy array that acts as the starting point when
            constructin the operation's matrix.  The shape of this array sets
            the dimension of the operation.

        parameter_array : numpy array
            a 1D numpy array that holds the all the parameters for this
            operation.  The shape of this array sets is what is returned by
            value_dimension(...).

        parameter_to_base_indices_map : dict
            A dictionary with keys == index of a parameter
            (i.e. in parameter_array) and values == list of 2-tuples
            indexing potentially multiple operation matrix coordinates
            which should be set equal to this parameter.

        left_transform : numpy array or None, optional
            A 2D array of the same shape as basematrix which left-multiplies
            the base matrix after parameters have been evaluated.  Defaults to
            no transform.

        right_transform : numpy array or None, optional
            A 2D array of the same shape as basematrix which right-multiplies
            the base matrix after parameters have been evaluated.  Defaults to
            no transform.

        real : bool, optional
            Whether or not the resulting operation matrix, after all
            parameter evaluation and left & right transforms have
            been performed, should be real.  If True, ValueError will
            be raised if the matrix contains any complex or imaginary
            elements.

        evotype : {"statevec", "densitymx", "auto"}
            The evolution type.  If `"auto"`, then `"statevec"` is used if `real == False`,
            otherwise `"densitymx"` is used.
        """

        base_matrix = _np.array(LinearOperator.convert_to_matrix(base_matrix), 'complex')
        #complex, even if passed all real base matrix

        elementExpressions = {}
        for p, ij_tuples in list(parameter_to_base_indices_map.items()):
            for i, j in ij_tuples:
                assert((i, j) not in elementExpressions)  # only one parameter allowed per base index pair
                elementExpressions[(i, j)] = [LinearlyParameterizedElementTerm(1.0, [p])]

        typ = "d" if real else "complex"
        mx = _np.empty(base_matrix.shape, typ)
        self.baseMatrix = base_matrix
        self.parameterArray = parameter_array
        self.numParams = len(parameter_array)
        self.elementExpressions = elementExpressions
        assert(_np.isrealobj(self.parameterArray)), "Parameter array must be real-valued!"

        I = _np.identity(self.baseMatrix.shape[0], 'd')  # LinearlyParameterizedGates are currently assumed to be real
        self.leftTrans = left_transform if (left_transform is not None) else I
        self.rightTrans = right_transform if (right_transform is not None) else I
        self.enforceReal = real

        if evotype == "auto": evotype = "densitymx" if real else "statevec"
        assert(evotype in ("densitymx", "statevec")), \
            "Invalid evolution type '%s' for %s" % (evotype, self.__class__.__name__)

        #Note: dense op reps *always* own their own data so setting writeable flag is OK
        DenseOperator.__init__(self, mx, evotype)
        self.base.flags.writeable = False  # only _construct_matrix can change array
        self._construct_matrix()  # construct base from the parameters

    def _construct_matrix(self):
        """
        Build the internal operation matrix using the current parameters.
        """
        matrix = self.baseMatrix.copy()
        for (i, j), terms in self.elementExpressions.items():
            for term in terms:
                param_prod = _np.prod([self.parameterArray[p] for p in term.paramIndices])
                matrix[i, j] += term.coeff * param_prod
        matrix = _np.dot(self.leftTrans, _np.dot(matrix, self.rightTrans))

        if self.enforceReal:
            if _np.linalg.norm(_np.imag(matrix)) > IMAG_TOL:
                raise ValueError("Linearly parameterized matrix has non-zero"
                                 "imaginary part (%g)!" % _np.linalg.norm(_np.imag(matrix)))
            matrix = _np.real(matrix)

        #Note: dense op reps *always* own their own data so setting writeable flag is OK
        assert(matrix.shape == (self.dim, self.dim))
        self.base.flags.writeable = True
        self.base[:, :] = matrix
        self.base.flags.writeable = False

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this operation.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return self.numParams

    def to_vector(self):
        """
        Extract a vector of the underlying operation parameters from this operation.

        Returns
        -------
        numpy array
            a 1D numpy array with length == num_params().
        """
        return self.parameterArray

    def from_vector(self, v, close=False, dirty_value=True):
        """
        Initialize the operation using a vector of parameters.

        Parameters
        ----------
        v : numpy array
            The 1D vector of operation parameters.  Length
            must == num_params()

        close : bool, optional
            Whether `v` is close to this operation's current
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
        self.parameterArray[:] = v
        self._construct_matrix()
        self.dirty = dirty_value

    def deriv_wrt_params(self, wrt_filter=None):
        """
        The element-wise derivative this operation.

        Construct a matrix whose columns are the vectorized
        derivatives of the flattened operation matrix with respect to a
        single operation parameter.  Thus, each column is of length
        op_dim^2 and there is one column per operation parameter.

        Parameters
        ----------
        wrt_filter : list or numpy.ndarray
            List of parameter indices to take derivative with respect to.
            (None means to use all the this operation's parameters.)

        Returns
        -------
        numpy array
            Array of derivatives, shape == (dimension^2, num_params)
        """
        derivMx = _np.zeros((self.numParams, self.dim, self.dim), 'complex')
        for (i, j), terms in self.elementExpressions.items():
            for term in terms:
                params_to_mult = [self.parameterArray[p] for p in term.paramIndices]
                for k, p in enumerate(term.paramIndices):
                    param_partial_prod = _np.prod(params_to_mult[0:k] + params_to_mult[k + 1:])  # exclude k-th factor
                    derivMx[p, i, j] += term.coeff * param_partial_prod

        derivMx = _np.dot(self.leftTrans, _np.dot(derivMx, self.rightTrans))  # (d,d) * (P,d,d) * (d,d) => (d,P,d)
        derivMx = _np.rollaxis(derivMx, 1, 3)  # now (d,d,P)
        derivMx = derivMx.reshape([self.dim**2, self.numParams])  # (d^2,P) == final shape

        if self.enforceReal:
            assert(_np.linalg.norm(_np.imag(derivMx)) < IMAG_TOL)
            derivMx = _np.real(derivMx)

        if wrt_filter is None:
            return derivMx
        else:
            return _np.take(derivMx, wrt_filter, axis=1)

    def has_nonzero_hessian(self):
        """
        Whether this operation has a non-zero Hessian with respect to its parameters.

        (i.e. whether it only depends linearly on its parameters or not)

        Returns
        -------
        bool
        """
        return False

    def compose(self, other_op):
        """
        Compose this operation with another :class:`LinearlyParamDenseOp`.

        Create and return a new operation that is the composition of this operation
        followed by other_op, which *must be another LinearlyParamDenseOp*.
        (For more general compositions between different types of operations, use
        the module-level compose function.)  The returned operation's matrix is
        equal to dot(this, other_op).

        Parameters
        ----------
        other_op : LinearlyParamDenseOp
            The operation to compose to the right of this one.

        Returns
        -------
        LinearlyParamDenseOp
        """
        assert(isinstance(other_op, LinearlyParamDenseOp))

        ### Implementation Notes ###
        #
        # Let self == L1 * A * R1, other == L2 * B * R2
        #   where  [A]_ij = a_ij + sum_l c^(ij)_l T^(ij)_l  so that
        #      a_ij == base matrix of self, c's are term coefficients, and T's are parameter products
        #   and similarly [B]_ij = b_ij + sum_l d^(ij)_l R^(ij)_l.
        #
        # We want in the end a gate with matrix:
        #   L1 * A * R1 * L2 * B * R2 == L1 * (A * W * B) * R2,  (where W := R1 * L2 )
        #   which is a linearly parameterized gate with leftTrans == L1, rightTrans == R2
        #   and a parameterized part == (A * W * B) which can be written with implied sum on k,n:
        #
        #  [A * W * B]_ij
        #   = (a_ik + sum_l c^(ik)_l T^(ik)_l) * W_kn * (b_nj + sum_m d^(nj)_m R^(nj)_m)
        #
        #   = a_ik * W_kn * b_nj +
        #     a_ik * W_kn * sum_m d^(nj)_m R^(nj)_m +
        #     sum_l c^(ik)_l T^(ik)_l * W_kn * b_nj +
        #     (sum_l c^(ik)_l T^(ik)_l) * W_kn * (sum_m d^(nj)_m R^(nj)_m)
        #
        #   = aWb_ij   # (new base matrix == a*W*b)
        #     aW_in * sum_m d^(nj)_m R^(nj)_m +   # coeffs w/params of other_op
        #     sum_l c^(ik)_l T^(ik)_l * Wb_kj +   # coeffs w/params of this gate
        #     sum_m,l c^(ik)_l W_kn d^(nj)_m T^(ik)_l R^(nj)_m) # coeffs w/params of both gates
        #

        W = _np.dot(self.rightTrans, other_op.leftTrans)
        baseMx = _np.dot(self.baseMatrix, _np.dot(W, other_op.baseMatrix))  # aWb above
        paramArray = _np.concatenate((self.parameterArray, other_op.parameterArray), axis=0)
        composedOp = LinearlyParamDenseOp(baseMx, paramArray, {},
                                          self.leftTrans, other_op.rightTrans,
                                          self.enforceReal and other_op.enforceReal,
                                          self._evotype)

        # Precompute what we can before the compute loop
        aW = _np.dot(self.baseMatrix, W)
        Wb = _np.dot(W, other_op.baseMatrix)

        kMax, nMax = (self.dim, self.dim)  # W.shape
        offset = len(self.parameterArray)  # amt to offset parameter indices of other_op

        # Compute  [A * W * B]_ij element expression as described above
        for i in range(self.baseMatrix.shape[0]):
            for j in range(other_op.baseMatrix.shape[1]):
                terms = []
                for n in range(nMax):
                    if (n, j) in other_op.elementExpressions:
                        for term in other_op.elementExpressions[(n, j)]:
                            coeff = aW[i, n] * term.coeff
                            paramIndices = [p + offset for p in term.paramIndices]
                            terms.append(LinearlyParameterizedElementTerm(coeff, paramIndices))

                for k in range(kMax):
                    if (i, k) in self.elementExpressions:
                        for term in self.elementExpressions[(i, k)]:
                            coeff = term.coeff * Wb[k, j]
                            terms.append(LinearlyParameterizedElementTerm(coeff, term.paramIndices))

                            for n in range(nMax):
                                if (n, j) in other_op.elementExpressions:
                                    for term2 in other_op.elementExpressions[(n, j)]:
                                        coeff = term.coeff * W[k, n] * term2.coeff
                                        paramIndices = term.paramIndices + [p + offset for p in term2.paramIndices]
                                        terms.append(LinearlyParameterizedElementTerm(coeff, paramIndices))

                composedOp.elementExpressions[(i, j)] = terms

        composedOp._construct_matrix()
        return composedOp

    def __str__(self):
        s = "Linearly Parameterized operation with shape %s, num params = %d\n" % \
            (str(self.base.shape), self.numParams)
        s += _mt.mx_to_string(self.base, width=5, prec=1)
        s += "\nParameterization:"
        for (i, j), terms in self.elementExpressions.items():
            tStr = ' + '.join(['*'.join(["p%d" % p for p in term.paramIndices])
                               for term in terms])
            s += "LinearOperator[%d,%d] = %s\n" % (i, j, tStr)
        return s
