class ExpErrorgenOp(LinearOperator, _ErrorGeneratorContainer):
    """
    An operation parameterized by the coefficients of an exponentiated sum of Lindblad-like terms.

    The exponentiated terms give the operation's action.

    Parameters
    ----------
    unitary_postfactor : numpy array or SciPy sparse matrix or int
        a square 2D array which specifies a part of the operation action
        to remove before parameterization via Lindblad projections.
        While this is termed a "post-factor" because it occurs to the
        right of the exponentiated Lindblad terms, this means it is applied
        to a state *before* the Lindblad terms (which usually represent
        operation errors).  Typically, this is a target (desired) operation operation.
        If this post-factor is just the identity you can simply pass the
        integer dimension as `unitary_postfactor` instead of a matrix, or
        you can pass `None` and the dimension will be inferred from
        `errorgen`.

    errorgen : LinearOperator
        The error generator for this operator.  That is, the `L` if this
        operator is `exp(L)*unitary_postfactor`.

    dense_rep : bool, optional
        Whether to internally implement this operation as a dense matrix.
        If `True` the error generator is rendered as a dense matrix and
        exponentiation is "exact".  If `False`, then this operation
        implements exponentiation in an approximate way that treats the
        error generator as a sparse matrix and only uses its action (and
        its adjoint's action) on a state.  Setting `dense_rep=False` is
        typically more efficient when `errorgen` has a large dimension,
        say greater than 100.
    """

    @classmethod
    def decomp_paramtype(cls, param_type):
        """
        A utility method for creating LindbladOp objects.

        Decomposes a high-level parameter-type `param_type` (e.g. `"H+S terms"`
        into a "base" type (specifies parameterization without evolution type,
        e.g. "H+S"), an evolution type (i.e. one of "densitymx", "svterm",
        "cterm", or "statevec").  Furthermore, from the base type two "modes"
        - one describing the number (and structure) of the non-Hamiltonian
        Lindblad coefficients and one describing how the Lindblad coefficients
        are converted to/from parameters - are derived.

        The "non-Hamiltonian mode" describes which non-Hamiltonian Lindblad
        coefficients are stored in a LindbladOp, and is one
        of `"diagonal"` (only the diagonal elements of the full coefficient
        matrix as a 1D array), `"diag_affine"` (a 2-by-d array of the diagonal
        coefficients on top of the affine projections), or `"all"` (the entire
        coefficient matrix).

        The "parameter mode" describes how the Lindblad coefficients/projections
        are converted into parameter values.  This can be:
        `"unconstrained"` (coefficients are independent unconstrained parameters),
        `"cptp"` (independent parameters but constrained so map is CPTP),
        `"depol"` (all non-Ham. diagonal coeffs are the *same, positive* value), or
        `"reldepol"` (same as `"depol"` but no positivity constraint).

        Parameters
        ----------
        param_type : str
            The high-level Lindblad parameter type to decompose.  E.g "H+S",
            "H+S+A terms", "CPTP clifford terms".

        Returns
        -------
        basetype : str
        evotype : str
        nonham_mode : str
        param_mode : str
        """
        bTyp, evotype = _gt.split_lindblad_paramtype(param_type)

        if bTyp == "CPTP":
            nonham_mode = "all"; param_mode = "cptp"
        elif bTyp == "H":
            nonham_mode = "all"; param_mode = "cptp"  # these don't matter since there's no non-ham errors
        elif bTyp in ("H+S", "S"):
            nonham_mode = "diagonal"; param_mode = "cptp"
        elif bTyp in ("H+s", "s"):
            nonham_mode = "diagonal"; param_mode = "unconstrained"
        elif bTyp in ("H+S+A", "S+A"):
            nonham_mode = "diag_affine"; param_mode = "cptp"
        elif bTyp in ("H+s+A", "s+A"):
            nonham_mode = "diag_affine"; param_mode = "unconstrained"
        elif bTyp in ("H+D", "D"):
            nonham_mode = "diagonal"; param_mode = "depol"
        elif bTyp in ("H+d", "d"):
            nonham_mode = "diagonal"; param_mode = "reldepol"
        elif bTyp in ("H+D+A", "D+A"):
            nonham_mode = "diag_affine"; param_mode = "depol"
        elif bTyp in ("H+d+A", "d+A"):
            nonham_mode = "diag_affine"; param_mode = "reldepol"

        elif bTyp == "GLND":
            nonham_mode = "all"; param_mode = "unconstrained"
        else:
            raise ValueError("Unrecognized base type in `param_type`=%s" % param_type)

        return bTyp, evotype, nonham_mode, param_mode

    @classmethod
    def from_operation_obj(cls, operation, param_type="GLND", unitary_postfactor=None,
                           proj_basis="pp", mx_basis="pp", truncate=True, lazy=False):
        """
        Creates a LindbladOp from an existing LinearOperator object and some additional information.

        This function is different from `from_operation_matrix` in that it assumes
        that `operation` is a :class:`LinearOperator`-derived object, and if `lazy=True` and
        if `operation` is already a matching LindbladOp, it is
        returned directly.  This routine is primarily used in operation conversion
        functions, where conversion is desired only when necessary.

        Parameters
        ----------
        operation : LinearOperator
            The operation object to "convert" to a `LindbladOp`.

        param_type : str
            The high-level "parameter type" of the operation to create.  This
            specifies both which Lindblad parameters are included and what
            type of evolution is used.  Examples of valid values are
            `"CPTP"`, `"H+S"`, `"S terms"`, and `"GLND clifford terms"`.

        unitary_postfactor : numpy array or SciPy sparse matrix, optional
            a square 2D array of the same dimension of `operation`.  This specifies
            a part of the operation action to remove before parameterization via
            Lindblad projections.  Typically, this is a target (desired) operation
            operation such that only the erroneous part of the operation (i.e. the
            operation relative to the target), which should be close to the identity,
            is parameterized.  If none, the identity is used by default.

        proj_basis : {'std', 'gm', 'pp', 'qt'}, list of matrices, or Basis object
            The basis used to construct the Lindblad-term error generators onto
            which the operation's error generator is projected.  Allowed values are
            Matrix-unit (std), Gell-Mann (gm), Pauli-product (pp),
            and Qutrit (qt), list of numpy arrays, or a custom basis object.

        mx_basis : {'std', 'gm', 'pp', 'qt'} or Basis object
            The source and destination basis, respectively.  Allowed
            values are Matrix-unit (std), Gell-Mann (gm), Pauli-product (pp),
            and Qutrit (qt) (or a custom basis object).

        truncate : bool, optional
            Whether to truncate the projections onto the Lindblad terms in
            order to meet constraints (e.g. to preserve CPTP) when necessary.
            If False, then an error is thrown when the given `operation` cannot
            be realized by the specified set of Lindblad projections.

        lazy : bool, optional
            If True, then if `operation` is already a LindbladOp
            with the requested details (given by the other arguments), then
            `operation` is returned directly and no conversion/copying is performed.
            If False, then a new operation object is always created and returned.

        Returns
        -------
        LindbladOp
        """
        RANK_TOL = 1e-6

        if unitary_postfactor is None:
            #Try to obtain unitary_post by getting the closest unitary
            if isinstance(operation, LindbladDenseOp):
                unitary_postfactor = operation.unitary_postfactor
            elif isinstance(operation, LinearOperator) and operation._evotype == "densitymx":
                J = _jt.fast_jamiolkowski_iso_std(operation.to_dense(), mx_basis)  # Choi mx basis doesn't matter
                if _np.linalg.matrix_rank(J, RANK_TOL) == 1:
                    unitary_postfactor = operation  # when 'operation' is unitary
            # FUTURE: support other operation._evotypes?
            else:
                unitary_postfactor = None

        #Break param_type in to a "base" type and an evotype
        bTyp, evotype, nonham_mode, param_mode = cls.decomp_paramtype(param_type)

        ham_basis = proj_basis if (("H" == bTyp) or ("H+" in bTyp) or bTyp in ("CPTP", "GLND")) else None
        nonham_basis = None if bTyp == "H" else proj_basis

        def beq(b1, b2):
            """ Check if bases have equal names """
            if not isinstance(b1, _Basis):  # b1 may be a string, in which case create a Basis
                b1 = _BuiltinBasis(b1, b2.dim, b2.sparse)  # from b2, which *will* be a Basis
            return b1 == b2

        def normeq(a, b):
            if a is None and b is None: return True
            if a is None or b is None: return False
            return _mt.safe_norm(a - b) < 1e-6  # what about possibility of Clifford operations?

        if lazy and isinstance(operation, LindbladOp) and \
           normeq(operation.unitary_postfactor, unitary_postfactor) and \
           isinstance(operation.errorgen, LindbladErrorgen) \
           and beq(ham_basis, operation.errorgen.ham_basis) and beq(nonham_basis, operation.errorgen.other_basis) \
           and param_mode == operation.errorgen.param_mode and nonham_mode == operation.errorgen.nonham_mode \
           and beq(mx_basis, operation.errorgen.matrix_basis) and operation._evotype == evotype:
            return operation  # no creation necessary!
        else:
            return cls.from_operation_matrix(
                operation, unitary_postfactor, ham_basis, nonham_basis, param_mode,
                nonham_mode, truncate, mx_basis, evotype)

    @classmethod
    def from_operation_matrix(cls, op_matrix, unitary_postfactor=None,
                              ham_basis="pp", nonham_basis="pp", param_mode="cptp",
                              nonham_mode="all", truncate=True, mx_basis="pp",
                              evotype="densitymx"):
        """
        Creates a Lindblad-parameterized operation from a matrix and a basis.

        The basis specifies how to decompose (project) the operation's error generator.

        Parameters
        ----------
        op_matrix : numpy array or SciPy sparse matrix
            a square 2D array that gives the raw operation matrix, assumed to
            be in the `mx_basis` basis, to parameterize.  The shape of this
            array sets the dimension of the operation. If None, then it is assumed
            equal to `unitary_postfactor` (which cannot also be None). The
            quantity `op_matrix inv(unitary_postfactor)` is parameterized via
            projection onto the Lindblad terms.

        unitary_postfactor : numpy array or SciPy sparse matrix, optional
            a square 2D array of the same size of `op_matrix` (if
            not None).  This matrix specifies a part of the operation action
            to remove before parameterization via Lindblad projections.
            Typically, this is a target (desired) operation operation such
            that only the erroneous part of the operation (i.e. the operation
            relative to the target), which should be close to the identity,
            is parameterized.  If none, the identity is used by default.

        ham_basis : {'std', 'gm', 'pp', 'qt'}, list of matrices, or Basis object
            The basis is used to construct the Hamiltonian-type lindblad error
            Allowed values are Matrix-unit (std), Gell-Mann (gm), Pauli-product (pp),
            and Qutrit (qt), list of numpy arrays, or a custom basis object.

        nonham_basis : {'std', 'gm', 'pp', 'qt'}, list of matrices, or Basis object
            The basis is used to construct the non-Hamiltonian (generalized
            Stochastic-type) lindblad error Allowed values are Matrix-unit
            (std), Gell-Mann (gm), Pauli-product (pp), and Qutrit (qt), list of
            numpy arrays, or a custom basis object.

        param_mode : {"unconstrained", "cptp", "depol", "reldepol"}
            Describes how the Lindblad coefficients/projections relate to the
            operation's parameter values.  Allowed values are:
            `"unconstrained"` (coeffs are independent unconstrained parameters),
            `"cptp"` (independent parameters but constrained so map is CPTP),
            `"reldepol"` (all non-Ham. diagonal coeffs take the *same* value),
            `"depol"` (same as `"reldepol"` but coeffs must be *positive*)

        nonham_mode : {"diagonal", "diag_affine", "all"}
            Which non-Hamiltonian Lindblad projections are potentially non-zero.
            Allowed values are: `"diagonal"` (only the diagonal Lind. coeffs.),
            `"diag_affine"` (diagonal coefficients + affine projections), and
            `"all"` (the entire matrix of coefficients is allowed).

        truncate : bool, optional
            Whether to truncate the projections onto the Lindblad terms in
            order to meet constraints (e.g. to preserve CPTP) when necessary.
            If False, then an error is thrown when the given `operation` cannot
            be realized by the specified set of Lindblad projections.

        mx_basis : {'std', 'gm', 'pp', 'qt'} or Basis object
            The source and destination basis, respectively.  Allowed
            values are Matrix-unit (std), Gell-Mann (gm), Pauli-product (pp),
            and Qutrit (qt) (or a custom basis object).

        evotype : {"densitymx","svterm","cterm"}
            The evolution type of the operation being constructed.  `"densitymx"` is
            usual Lioville density-matrix-vector propagation via matrix-vector
            products.  `"svterm"` denotes state-vector term-based evolution
            (action of operation is obtained by evaluating the rank-1 terms up to
            some order).  `"cterm"` is similar but uses Clifford operation action
            on stabilizer states.

        Returns
        -------
        LindbladOp
        """

        #Compute a (errgen, unitary_postfactor) pair from the given
        # (op_matrix, unitary_postfactor) pair.  Works with both
        # dense and sparse matrices.

        if op_matrix is None:
            assert(unitary_postfactor is not None), "arguments cannot both be None"
            op_matrix = unitary_postfactor

        sparseOp = _sps.issparse(op_matrix)
        if unitary_postfactor is None:
            if sparseOp:
                upost = _sps.identity(op_matrix.shape[0], 'd', 'csr')
            else: upost = _np.identity(op_matrix.shape[0], 'd')
        else: upost = unitary_postfactor

        #Init base from error generator: sets basis members and ultimately
        # the parameters in self.paramvals
        if sparseOp:
            #Instead of making error_generator(...) compatible with sparse matrices
            # we require sparse matrices to have trivial initial error generators
            # or we convert to dense:
            if(_mt.safe_norm(op_matrix - upost) < 1e-8):
                errgenMx = _sps.csr_matrix(op_matrix.shape, dtype='d')  # all zeros
            else:
                errgenMx = _sps.csr_matrix(
                    _gt.error_generator(op_matrix.toarray(), upost.toarray(),
                                        mx_basis, "logGTi"), dtype='d')
        else:
            #DB: assert(_np.linalg.norm(op_matrix.imag) < 1e-8)
            #DB: assert(_np.linalg.norm(upost.imag) < 1e-8)
            errgenMx = _gt.error_generator(op_matrix, upost, mx_basis, "logGTi")

        errgen = LindbladErrorgen.from_error_generator(errgenMx, ham_basis,
                                                       nonham_basis, param_mode, nonham_mode,
                                                       mx_basis, truncate, evotype)

        #Use "sparse" matrix exponentiation when given operation matrix was sparse.
        return cls(unitary_postfactor, errgen, dense_rep=not sparseOp)

    def __init__(self, unitary_postfactor, errorgen, dense_rep=False):
        """
        Create a new `LinbladOp` based on an error generator and postfactor.

        Note that if you want to construct a `LinbladOp` from an operation
        matrix, you can use the :method:`from_operation_matrix` class
        method and save youself some time and effort.

        Parameters
        ----------
        unitary_postfactor : numpy array or SciPy sparse matrix or int
            a square 2D array which specifies a part of the operation action
            to remove before parameterization via Lindblad projections.
            While this is termed a "post-factor" because it occurs to the
            right of the exponentiated Lindblad terms, this means it is applied
            to a state *before* the Lindblad terms (which usually represent
            operation errors).  Typically, this is a target (desired) operation operation.
            If this post-factor is just the identity you can simply pass the
            integer dimension as `unitary_postfactor` instead of a matrix, or
            you can pass `None` and the dimension will be inferred from
            `errorgen`.

        errorgen : LinearOperator
            The error generator for this operator.  That is, the `L` if this
            operator is `exp(L)*unitary_postfactor`.

        dense_rep : bool, optional
            Whether to internally implement this operation as a dense matrix.
            If `True` the error generator is rendered as a dense matrix and
            exponentiation is "exact".  If `False`, then this operation
            implements exponentiation in an approximate way that treats the
            error generator as a sparse matrix and only uses its action (and
            its adjoint's action) on a state.  Setting `dense_rep=False` is
            typically more efficient when `errorgen` has a large dimension,
            say greater than 100.
        """

        # Extract superop dimension from 'errorgen'
        d2 = errorgen.dim
        d = int(round(_np.sqrt(d2)))
        assert(d * d == d2), "LinearOperator dim must be a perfect square"

        self.errorgen = errorgen  # don't copy (allow object reuse)

        evotype = self.errorgen._evotype

        #TODO REMOVE
        #if evotype in ("svterm", "cterm"):
        #    dense_rep = True  # we need *dense* unitary postfactors for the term-based processing below
        #self.dense_rep = dense_rep
        #
        ## make unitary postfactor sparse when dense_rep == False and vice versa.
        ## (This doens't have to be the case, but we link these two "sparseness" notions:
        ##  when we perform matrix exponentiation in a "sparse" way we assume the matrices
        ##  are large and so the unitary postfactor (if present) should be sparse).
        ## FUTURE: warn if there is a sparsity mismatch btwn basis and postfactor?
        #if unitary_postfactor is not None:
        #    if self.dense_rep and _sps.issparse(unitary_postfactor):
        #        unitary_postfactor = unitary_postfactor.toarray()  # sparse -> dense
        #    elif not self.dense_rep and not _sps.issparse(unitary_postfactor):
        #        unitary_postfactor = _sps.csr_matrix(_np.asarray(unitary_postfactor))  # dense -> sparse

        #Finish initialization based on evolution type
        if self.dense_rep:
            rep = evotype.create_dense_rep(d2)

            # Cache values - for later work with dense rep
            self.exp_err_gen = None   # used for dense_rep=True mode to cache qty needed in deriv_wrt_params
            self.base_deriv = None
            self.base_hessian = None
        else:
            # "sparse mode" => don't ever compute matrix-exponential explicitly
            rep = evotype.create_experrorgen_rep(self.errorgen._rep)

        LinearOperator.__init__(self, rep, evotype)
        _ErrorGeneratorContainer.__init__(self, self.errorgen)
        self._update_rep()  # updates self._rep
        #Done with __init__(...)

    def submembers(self):
        """
        Get the ModelMember-derived objects contained in this one.

        Returns
        -------
        list
        """
        return [self.errorgen]

    def copy(self, parent=None, memo=None):
        """
        Copy this object.

        Parameters
        ----------
        parent : Model, optional
            The parent model to set for the copy.

        Returns
        -------
        LinearOperator
            A copy of this object.
        """
        # We need to override this method so that error map has its
        # parent reset correctly.
        if memo is not None and id(self) in memo: return memo[id(self)]

        #TODO REMOVE
        #if self.unitary_postfactor is None:
        #    upost = None
        #elif self._evotype == "densitymx":
        #    upost = self.unitary_postfactor
        #else:
        #    #self.unitary_postfactor is actually the *unitary* not the postfactor
        #    termtype = "dense" if self._evotype == "svterm" else "clifford"
        #
        #    # automatically "up-convert" operation to CliffordOp if needed
        #    if termtype == "clifford":
        #        assert(isinstance(self.unitary_postfactor, CliffordOp))  # see __init__
        #        U = self.unitary_postfactor.unitary
        #    else: U = self.unitary_postfactor
        #    op_std = _gt.unitary_to_process_mx(U)
        #    upost = _bt.change_basis(op_std, 'std', self.errorgen.matrix_basis)

        cls = self.__class__  # so that this method works for derived classes too
        copyOfMe = cls(upost, self.errorgen.copy(parent, memo), self.dense_rep)
        return self._copy_gpindices(copyOfMe, parent, memo)

    def _update_rep(self, close=False):
        """
        Updates self._rep as needed after parameters have changed.
        """
        if self.dense_rep:
            # compute matrix-exponential explicitly
            self.exp_err_gen = _spl.expm(self.errorgen.to_dense())  # used in deriv_wrt_params

            #TODO REMOVE
            #if self.unitary_postfactor is not None:
            #    dense = _np.dot(self.exp_err_gen, self.unitary_postfactor)
            #else: dense = self.exp_err_gen
            dense = self.exp_err_gen
            self._rep.base.flags.writeable = True
            self._rep.base[:, :] = dense
            self._rep.base.flags.writeable = False
            self.base_deriv = None
            self.base_hessian = None
        elif not close:
            self._rep.errgenrep_has_changed()

    def set_gpindices(self, gpindices, parent, memo=None):
        """
        Set the parent and indices into the parent's parameter vector that are used by this ModelMember object.

        Parameters
        ----------
        gpindices : slice or integer ndarray
            The indices of this objects parameters in its parent's array.

        parent : Model or ModelMember
            The parent whose parameter array gpindices references.

        memo : dict, optional
            A memo dict used to avoid circular references.

        Returns
        -------
        None
        """
        _modelmember.ModelMember.set_gpindices(self, gpindices, parent, memo)
        self._rep.param_indices_have_changed()

    def to_dense(self):
        """
        Return this operation as a dense matrix.

        Returns
        -------
        numpy.ndarray
        """
        if self.dense_rep:
            # Then self._rep contains a dense version already
            return self._rep.base  # copy() unnecessary since we set to readonly

        else:
            # Construct a dense version from scratch (more time consuming)
            exp_errgen = _spl.expm(self.errorgen.to_dense())

            #TODO REMOVE
            #if self.unitary_postfactor is not None:
            #    if self._evotype in ("svterm", "cterm"):
            #        if self._evotype == "cterm":
            #            assert(isinstance(self.unitary_postfactor, CliffordOp))  # see __init__
            #            U = self.unitary_postfactor.unitary
            #        else: U = self.unitary_postfactor
            #        op_std = _gt.unitary_to_process_mx(U)
            #        upost = _bt.change_basis(op_std, 'std', self.errorgen.matrix_basis)
            #    else:
            #        upost = self.unitary_postfactor
            #
            #    dense = _mt.safe_dot(exp_errgen, upost)
            #else:
            dense = exp_errgen
            return dense

    #FUTURE: maybe remove this function altogether, as it really shouldn't be called
    def to_sparse(self):
        """
        Return the operation as a sparse matrix.

        Returns
        -------
        scipy.sparse.csr_matrix
        """
        _warnings.warn(("Constructing the sparse matrix of a LindbladDenseOp."
                        "  Usually this is *NOT* acutally sparse (the exponential of a"
                        " sparse matrix isn't generally sparse)!"))
        if self.dense_rep:
            return _sps.csr_matrix(self.to_dense())
        else:
            exp_err_gen = _spsl.expm(self.errorgen.to_sparse().tocsc()).tocsr()
            #TODO REMOVE
            #if self.unitary_postfactor is not None:
            #    return exp_err_gen.dot(self.unitary_postfactor)
            #else:
            return exp_err_gen

    #def torep(self):
    #    """
    #    Return a "representation" object for this operation.
    #
    #    Such objects are primarily used internally by pyGSTi to compute
    #    things like probabilities more efficiently.
    #
    #    Returns
    #    -------
    #    OpRep
    #    """
    #    if self._evotype == "densitymx":
    #        if self.sparse_expm:
    #            if self.unitary_postfactor is None:
    #                Udata = _np.empty(0, 'd')
    #                Uindices = Uindptr = _np.empty(0, _np.int64)
    #            else:
    #                assert(_sps.isspmatrix_csr(self.unitary_postfactor)), \
    #                    "Internal error! Unitary postfactor should be a *sparse* CSR matrix!"
    #                Udata = self.unitary_postfactor.data
    #                Uindptr = _np.ascontiguousarray(self.unitary_postfactor.indptr, _np.int64)
    #                Uindices = _np.ascontiguousarray(self.unitary_postfactor.indices, _np.int64)
    #
    #            mu, m_star, s, eta = self.err_gen_prep
    #            errorgen_rep = self.errorgen.torep()
    #            return replib.DMOpRepLindblad(errorgen_rep,
    #                                           mu, eta, m_star, s,
    #                                           Udata, Uindices, Uindptr) # HERE
    #        else:
    #            if self.unitary_postfactor is not None:
    #                dense = _np.dot(self.exp_err_gen, self.unitary_postfactor)
    #            else: dense = self.exp_err_gen
    #            return replib.DMOpRepDense(_np.ascontiguousarray(dense, 'd'))
    #    else:
    #        raise ValueError("Invalid evotype '%s' for %s.torep(...)" %
    #                         (self._evotype, self.__class__.__name__))

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
        if not self.dense_rep:
            raise NotImplementedError("deriv_wrt_params is only implemented for *dense-rep* LindbladOps")
            # because we need self.unitary_postfactor to be a dense operation below (and it helps to
            # have self.exp_err_gen cached)

        if self.base_deriv is None:
            d2 = self.dim

            #Deriv wrt hamiltonian params
            derrgen = self.errorgen.deriv_wrt_params(None)  # apply filter below; cache *full* deriv
            derrgen.shape = (d2, d2, -1)  # separate 1st d2**2 dim to (d2,d2)
            dexpL = _d_exp_x(self.errorgen.to_dense(), derrgen, self.exp_err_gen,
                             self.unitary_postfactor)
            derivMx = dexpL.reshape(d2**2, self.num_params)  # [iFlattenedOp,iParam]

            assert(_np.linalg.norm(_np.imag(derivMx)) < IMAG_TOL), \
                ("Deriv matrix has imaginary part = %s.  This can result from "
                 "evaluating a Model derivative at a 'bad' point where the "
                 "error generator is large.  This often occurs when GST's "
                 "starting Model has *no* stochastic error and all such "
                 "parameters affect error rates at 2nd order.  Try "
                 "depolarizing the seed Model.") % str(_np.linalg.norm(_np.imag(derivMx)))
            # if this fails, uncomment around "DB COMMUTANT NORM" for further debugging.
            derivMx = _np.real(derivMx)
            self.base_deriv = derivMx

            #check_deriv_wrt_params(self, derivMx, eps=1e-7)
            #fd_deriv = finite_difference_deriv_wrt_params(self, wrt_filter, eps=1e-7)
            #derivMx = fd_deriv

        if wrt_filter is None:
            return self.base_deriv.view()
            #view because later setting of .shape by caller can mess with self.base_deriv!
        else:
            return _np.take(self.base_deriv, wrt_filter, axis=1)

    def has_nonzero_hessian(self):
        """
        Whether this operation has a non-zero Hessian with respect to its parameters.

        (i.e. whether it only depends linearly on its parameters or not)

        Returns
        -------
        bool
        """
        return True

    def hessian_wrt_params(self, wrt_filter1=None, wrt_filter2=None):
        """
        Construct the Hessian of this operation with respect to its parameters.

        This function returns a tensor whose first axis corresponds to the
        flattened operation matrix and whose 2nd and 3rd axes correspond to the
        parameters that are differentiated with respect to.

        Parameters
        ----------
        wrt_filter1 : list or numpy.ndarray
            List of parameter indices to take 1st derivatives with respect to.
            (None means to use all the this operation's parameters.)

        wrt_filter2 : list or numpy.ndarray
            List of parameter indices to take 2nd derivatives with respect to.
            (None means to use all the this operation's parameters.)

        Returns
        -------
        numpy array
            Hessian with shape (dimension^2, num_params1, num_params2)
        """
        if not self.dense_rep:
            raise NotImplementedError("hessian_wrt_params is only implemented for *dense-rep* LindbladOps")
            # because we need self.unitary_postfactor to be a dense operation below (and it helps to
            # have self.exp_err_gen cached)

        if self.base_hessian is None:
            d2 = self.dim
            nP = self.num_params
            hessianMx = _np.zeros((d2**2, nP, nP), 'd')

            #Deriv wrt other params
            dEdp = self.errorgen.deriv_wrt_params(None)  # filter later, cache *full*
            d2Edp2 = self.errorgen.hessian_wrt_params(None, None)  # hessian
            dEdp.shape = (d2, d2, nP)  # separate 1st d2**2 dim to (d2,d2)
            d2Edp2.shape = (d2, d2, nP, nP)  # ditto

            series, series2 = _d2_exp_series(self.errorgen.to_dense(), dEdp, d2Edp2)
            term1 = series2
            term2 = _np.einsum("ija,jkq->ikaq", series, series)
            if self.unitary_postfactor is None:
                d2expL = _np.einsum("ikaq,kj->ijaq", term1 + term2,
                                    self.exp_err_gen)
            else:
                d2expL = _np.einsum("ikaq,kl,lj->ijaq", term1 + term2,
                                    self.exp_err_gen, self.unitary_postfactor)
            hessianMx = d2expL.reshape((d2**2, nP, nP))

            #hessian has been made so index as [iFlattenedOp,iDeriv1,iDeriv2]
            assert(_np.linalg.norm(_np.imag(hessianMx)) < IMAG_TOL)
            hessianMx = _np.real(hessianMx)  # d2O block of hessian

            self.base_hessian = hessianMx

            #TODO: check hessian with finite difference here?

        if wrt_filter1 is None:
            if wrt_filter2 is None:
                return self.base_hessian.view()
                #view because later setting of .shape by caller can mess with self.base_hessian!
            else:
                return _np.take(self.base_hessian, wrt_filter2, axis=2)
        else:
            if wrt_filter2 is None:
                return _np.take(self.base_hessian, wrt_filter1, axis=1)
            else:
                return _np.take(_np.take(self.base_hessian, wrt_filter1, axis=1),
                                wrt_filter2, axis=2)

    @property
    def parameter_labels(self):
        """
        An array of labels (usually strings) describing this model member's parameters.
        """
        return self.errorgen.parameter_labels

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this operation.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return self.errorgen.num_params

    def to_vector(self):
        """
        Extract a vector of the underlying operation parameters from this operation.

        Returns
        -------
        numpy array
            a 1D numpy array with length == num_params().
        """
        return self.errorgen.to_vector()

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
        self.errorgen.from_vector(v, close, dirty_value)
        self._update_rep(close)
        self.dirty = dirty_value

    def set_dense(self, m):
        """
        Set the dense-matrix value of this operation.

        Attempts to modify operation parameters so that the specified raw
        operation matrix becomes mx.  Will raise ValueError if this operation
        is not possible.

        Parameters
        ----------
        m : array_like or LinearOperator
            An array of shape (dim, dim) or LinearOperator representing the operation action.

        Returns
        -------
        None
        """

        #TODO: move this function to errorgen?
        if not isinstance(self.errorgen, LindbladErrorgen):
            raise NotImplementedError(("Can only set the value of a LindbladDenseOp that "
                                       "contains a single LindbladErrorgen error generator"))

        tOp = LindbladOp.from_operation_matrix(
            m, self.unitary_postfactor,
            self.errorgen.ham_basis, self.errorgen.other_basis,
            self.errorgen.param_mode, self.errorgen.nonham_mode,
            True, self.errorgen.matrix_basis, self._evotype)

        #Note: truncate=True to be safe
        self.errorgen.from_vector(tOp.errorgen.to_vector())
        self._update_rep()
        self.dirty = True

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
        if isinstance(s, _gaugegroup.UnitaryGaugeGroupElement) or \
           isinstance(s, _gaugegroup.TPSpamGaugeGroupElement):
            U = s.transform_matrix
            Uinv = s.transform_matrix_inverse
            #assert(_np.allclose(U, _np.linalg.inv(Uinv)))

            #just conjugate postfactor and Lindbladian exponent by U:
            if self.unitary_postfactor is not None:
                self.unitary_postfactor = _mt.safe_dot(Uinv, _mt.safe_dot(self.unitary_postfactor, U))
            self.errorgen.transform_inplace(s)
            self._update_rep()  # needed to rebuild exponentiated error gen
            self.dirty = True

            #CHECK WITH OLD (passes) TODO move to unit tests?
            #tMx = _np.dot(Uinv,_np.dot(self.base, U)) #Move above for checking
            #tOp = LindbladDenseOp(tMx,self.unitary_postfactor,
            #                                self.ham_basis, self.other_basis,
            #                                self.cptp,self.nonham_diagonal_only,
            #                                True, self.matrix_basis)
            #assert(_np.linalg.norm(tOp.paramvals - self.paramvals) < 1e-6)
        else:
            raise ValueError("Invalid transform for this LindbladDenseOp: type %s"
                             % str(type(s)))

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

        if isinstance(s, _gaugegroup.UnitaryGaugeGroupElement) or \
           isinstance(s, _gaugegroup.TPSpamGaugeGroupElement):
            U = s.transform_matrix
            Uinv = s.transform_matrix_inverse

            #Note: this code may need to be tweaked to work with sparse matrices
            if typ == "prep":
                tMx = _mt.safe_dot(Uinv, self.to_dense())
            else:
                tMx = _mt.safe_dot(self.to_dense(), U)
            trunc = bool(isinstance(s, _gaugegroup.UnitaryGaugeGroupElement))
            tOp = LindbladOp.from_operation_matrix(tMx, self.unitary_postfactor,
                                                   self.errorgen.ham_basis, self.errorgen.other_basis,
                                                   self.errorgen.param_mode, self.errorgen.nonham_mode,
                                                   trunc, self.errorgen.matrix_basis)
            self.from_vector(tOp.to_vector())
            #Note: truncate=True above for unitary transformations because
            # while this trunctation should never be necessary (unitaries map CPTP -> CPTP)
            # sometimes a unitary transform can modify eigenvalues to be negative beyond
            # the tight tolerances checked when truncate == False. Maybe we should be able
            # to give a tolerance as `truncate` in the future?

            #NOTE: This *doesn't* work as it does in the 'operation' case b/c this isn't a
            # similarity transformation!
            ##just act on postfactor and Lindbladian exponent:
            #if typ == "prep":
            #    if self.unitary_postfactor is not None:
            #        self.unitary_postfactor = _mt.safe_dot(Uinv, self.unitary_postfactor)
            #else:
            #    if self.unitary_postfactor is not None:
            #        self.unitary_postfactor = _mt.safe_dot(self.unitary_postfactor, U)
            #
            #self.errorgen.spam_transform(s, typ)
            #self._update_rep()  # needed to rebuild exponentiated error gen
            #self.dirty = True
        else:
            raise ValueError("Invalid transform for this LindbladDenseOp: type %s"
                             % str(type(s)))

    def __str__(self):
        s = "Lindblad Parameterized operation map with dim = %d, num params = %d\n" % \
            (self.dim, self.num_params)
        return s


class LindbladDenseOp(LindbladOp, DenseOperatorInterface):
    """
    An operation matrix that is parameterized by a Lindblad-form expression.

    Specifically, each parameter multiplies a particular term in the Lindblad
    form that is exponentiated to give the operation matrix up to an optional
    unitary prefactor).  The basis used by the Lindblad form is referred to as
    the "projection basis".

    Parameters
    ----------
    unitary_postfactor : numpy array or SciPy sparse matrix or int
        a square 2D array which specifies a part of the operation action
        to remove before parameterization via Lindblad projections.
        While this is termed a "post-factor" because it occurs to the
        right of the exponentiated Lindblad terms, this means it is applied
        to a state *before* the Lindblad terms (which usually represent
        operation errors).  Typically, this is a target (desired) operation operation.
        If this post-factor is just the identity you can simply pass the
        integer dimension as `unitary_postfactor` instead of a matrix, or
        you can pass `None` and the dimension will be inferred from
        `errorgen`.

    errorgen : LinearOperator
        The error generator for this operator.  That is, the `L` if this
        operator is `exp(L)*unitary_postfactor`.

    dense_rep : bool, optional
        Whether the internal representation is dense.  This currently *must*
        be set to `True`.
    """

    def __init__(self, unitary_postfactor, errorgen, dense_rep=True):
        """
        Create a new LinbladDenseOp based on an error generator and postfactor.

        Note that if you want to construct a `LinbladDenseOp` from an operation
        matrix, you can use the :method:`from_operation_matrix` class method
        and save youself some time and effort.

        Parameters
        ----------
        unitary_postfactor : numpy array or SciPy sparse matrix or int
            a square 2D array which specifies a part of the operation action
            to remove before parameterization via Lindblad projections.
            While this is termed a "post-factor" because it occurs to the
            right of the exponentiated Lindblad terms, this means it is applied
            to a state *before* the Lindblad terms (which usually represent
            operation errors).  Typically, this is a target (desired) operation operation.
            If this post-factor is just the identity you can simply pass the
            integer dimension as `unitary_postfactor` instead of a matrix, or
            you can pass `None` and the dimension will be inferred from
            `errorgen`.

        errorgen : LinearOperator
            The error generator for this operator.  That is, the `L` if this
            operator is `exp(L)*unitary_postfactor`.

        dense_rep : bool, optional
            Whether the internal representation is dense.  This currently *must*
            be set to `True`.
        """
        assert(dense_rep), "LindbladDenseOp must be created with `dense_rep == True`"
        assert(errorgen._evotype == "densitymx"), \
            "LindbladDenseOp objects can only be used for the 'densitymx' evolution type"
        #Note: cannot remove the evotype argument b/c we need to maintain the same __init__
        # signature as LindbladOp so its @classmethods will work on us.

        #Start with base class construction
        LindbladOp.__init__(self, unitary_postfactor, errorgen, dense_rep=True)
        DenseOperatorInterface.__init__(self)


def _d_exp_series(x, dx):
    TERM_TOL = 1e-12
    tr = len(dx.shape)  # tensor rank of dx; tr-2 == # of derivative dimensions
    assert((tr - 2) in (1, 2)), "Currently, dx can only have 1 or 2 derivative dimensions"
    #assert( len( (_np.isnan(dx)).nonzero()[0] ) == 0 ) # NaN debugging
    #assert( len( (_np.isnan(x)).nonzero()[0] ) == 0 ) # NaN debugging
    series = dx.copy()  # accumulates results, so *need* a separate copy
    last_commutant = term = dx; i = 2

    #take d(matrix-exp) using series approximation
    while _np.amax(_np.abs(term)) > TERM_TOL:  # _np.linalg.norm(term)
        if tr == 3:
            #commutant = _np.einsum("ik,kja->ija",x,last_commutant) - \
            #            _np.einsum("ika,kj->ija",last_commutant,x)
            commutant = _np.tensordot(x, last_commutant, (1, 0)) - \
                _np.transpose(_np.tensordot(last_commutant, x, (1, 0)), (0, 2, 1))
        elif tr == 4:
            #commutant = _np.einsum("ik,kjab->ijab",x,last_commutant) - \
            #        _np.einsum("ikab,kj->ijab",last_commutant,x)
            commutant = _np.tensordot(x, last_commutant, (1, 0)) - \
                _np.transpose(_np.tensordot(last_commutant, x, (1, 0)), (0, 3, 1, 2))

        term = 1 / _np.math.factorial(i) * commutant

        #Uncomment some/all of this when you suspect an overflow due to x having large norm.
        #print("DB COMMUTANT NORM = ",_np.linalg.norm(commutant)) # sometimes this increases w/iter -> divergence => NaN
        #assert(not _np.isnan(_np.linalg.norm(term))), \
        #    ("Haddamard series = NaN! Probably due to trying to differentiate "
        #     "exp(x) where x has a large norm!")

        #DEBUG
        #if not _np.isfinite(_np.linalg.norm(term)): break # DEBUG high values -> overflow for nqubit operations
        #if len( (_np.isnan(term)).nonzero()[0] ) > 0: # NaN debugging
        #    #WARNING: stopping early b/c of NaNs!!! - usually caused by infs
        #    break

        series += term  # 1/_np.math.factorial(i) * commutant
        last_commutant = commutant; i += 1
    return series


def _d2_exp_series(x, dx, d2x):
    TERM_TOL = 1e-12
    tr = len(dx.shape)  # tensor rank of dx; tr-2 == # of derivative dimensions
    tr2 = len(d2x.shape)  # tensor rank of dx; tr-2 == # of derivative dimensions
    assert((tr - 2, tr2 - 2) in [(1, 2), (2, 4)]), "Current support for only 1 or 2 derivative dimensions"

    series = dx.copy()  # accumulates results, so *need* a separate copy
    series2 = d2x.copy()  # accumulates results, so *need* a separate copy
    term = last_commutant = dx
    last_commutant2 = term2 = d2x
    i = 2

    #take d(matrix-exp) using series approximation
    while _np.amax(_np.abs(term)) > TERM_TOL or _np.amax(_np.abs(term2)) > TERM_TOL:
        if tr == 3:
            commutant = _np.einsum("ik,kja->ija", x, last_commutant) - \
                _np.einsum("ika,kj->ija", last_commutant, x)
            commutant2A = _np.einsum("ikq,kja->ijaq", dx, last_commutant) - \
                _np.einsum("ika,kjq->ijaq", last_commutant, dx)
            commutant2B = _np.einsum("ik,kjaq->ijaq", x, last_commutant2) - \
                _np.einsum("ikaq,kj->ijaq", last_commutant2, x)

        elif tr == 4:
            commutant = _np.einsum("ik,kjab->ijab", x, last_commutant) - \
                _np.einsum("ikab,kj->ijab", last_commutant, x)
            commutant2A = _np.einsum("ikqr,kjab->ijabqr", dx, last_commutant) - \
                _np.einsum("ikab,kjqr->ijabqr", last_commutant, dx)
            commutant2B = _np.einsum("ik,kjabqr->ijabqr", x, last_commutant2) - \
                _np.einsum("ikabqr,kj->ijabqr", last_commutant2, x)

        term = 1 / _np.math.factorial(i) * commutant
        term2 = 1 / _np.math.factorial(i) * (commutant2A + commutant2B)
        series += term
        series2 += term2
        last_commutant = commutant
        last_commutant2 = (commutant2A + commutant2B)
        i += 1
    return series, series2


def _d_exp_x(x, dx, exp_x=None, postfactor=None):
    """
    Computes the derivative of the exponential of x(t) using
    the Haddamard lemma series expansion.

    Parameters
    ----------
    x : ndarray
        The 2-tensor being exponentiated

    dx : ndarray
        The derivative of x; can be either a 3- or 4-tensor where the
        3rd+ dimensions are for (multi-)indexing the parameters which
        are differentiated w.r.t.  For example, in the simplest case
        dx is a 3-tensor s.t. dx[i,j,p] == d(x[i,j])/dp.

    exp_x : ndarray, optional
        The value of `exp(x)`, which can be specified in order to save
        a call to `scipy.linalg.expm`.  If None, then the value is
        computed internally.

    postfactor : ndarray, optional
        A 2-tensor of the same shape as x that post-multiplies the
        result.

    Returns
    -------
    ndarray
        The derivative of `exp(x)*postfactor` given as a tensor with the
        same shape and axes as `dx`.
    """
    tr = len(dx.shape)  # tensor rank of dx; tr-2 == # of derivative dimensions
    assert((tr - 2) in (1, 2)), "Currently, dx can only have 1 or 2 derivative dimensions"

    series = _d_exp_series(x, dx)
    if exp_x is None: exp_x = _spl.expm(x)

    if tr == 3:
        #dExpX = _np.einsum('ika,kj->ija', series, exp_x)
        dExpX = _np.transpose(_np.tensordot(series, exp_x, (1, 0)), (0, 2, 1))
        if postfactor is not None:
            #dExpX = _np.einsum('ila,lj->ija', dExpX, postfactor)
            dExpX = _np.transpose(_np.tensordot(dExpX, postfactor, (1, 0)), (0, 2, 1))
    elif tr == 4:
        #dExpX = _np.einsum('ikab,kj->ijab', series, exp_x)
        dExpX = _np.transpose(_np.tensordot(series, exp_x, (1, 0)), (0, 3, 1, 2))
        if postfactor is not None:
            #dExpX = _np.einsum('ilab,lj->ijab', dExpX, postfactor)
            dExpX = _np.transpose(_np.tensordot(dExpX, postfactor, (1, 0)), (0, 3, 1, 2))

    return dExpX
