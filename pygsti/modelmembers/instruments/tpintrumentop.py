class TPInstrumentOp(DenseOperator):
    """
    An element of a :class:`TPInstrument`.

    A partial implementation of :class:`LinearOperator` which encapsulates an
    element of a :class:`TPInstrument`.  Instances rely on their parent being a
    `TPInstrument`.

    Parameters
    ----------
    param_ops : list of LinearOperator objects
        A list of the underlying operation objects which constitute a simple
        parameterization of a :class:`TPInstrument`.  Namely, this is
        the list of [MT,D1,D2,...Dn] operations which parameterize *all* of the
        `TPInstrument`'s elements.

    index : int
        The index indicating which element of the `TPInstrument` the
        constructed object is.  Must be in the range
        `[0,len(param_ops)-1]`.
    """

    def __init__(self, param_ops, index):
        """
        Initialize a TPInstrumentOp object.

        Parameters
        ----------
        param_ops : list of LinearOperator objects
            A list of the underlying operation objects which constitute a simple
            parameterization of a :class:`TPInstrument`.  Namely, this is
            the list of [MT,D1,D2,...Dn] operations which parameterize *all* of the
            `TPInstrument`'s elements.

        index : int
            The index indicating which element of the `TPInstrument` the
            constructed object is.  Must be in the range
            `[0,len(param_ops)-1]`.
        """
        self.param_ops = param_ops
        self.index = index
        DenseOperator.__init__(self, _np.identity(param_ops[0].dim, 'd'),
                               "densitymx")  # Note: sets self.gpindices; TP assumed real
        self._construct_matrix()

        #Set our own parent and gpindices based on param_ops
        # (this breaks the usual paradigm of having the parent object set these,
        #  but the exception is justified b/c the parent has set these members
        #  of the underlying 'param_ops' operations)
        self.dependents = [0, index + 1] if index < len(param_ops) - 1 \
            else list(range(len(param_ops)))
        #indices into self.param_ops of the operations this operation depends on
        self.set_gpindices(_slct.list_to_slice(
            _np.concatenate([param_ops[i].gpindices_as_array()
                             for i in self.dependents], axis=0), True, False),
                           param_ops[0].parent)  # use parent of first param operation
        # (they should all be the same)

    def _construct_matrix(self):
        """
        Mi = Di + MT for i = 1...(n-1)
           = -(n-2)*MT-sum(Di) = -(n-2)*MT-[(MT-Mi)-n*MT] for i == (n-1)
        """
        nEls = len(self.param_ops)
        self.base.flags.writeable = True
        if self.index < nEls - 1:
            self.base[:, :] = _np.asarray(self.param_ops[self.index + 1]
                                          + self.param_ops[0])
        else:
            assert(self.index == nEls - 1), \
                "Invalid index %d > %d" % (self.index, nEls - 1)
            self.base[:, :] = _np.asarray(-sum(self.param_ops)
                                          - (nEls - 3) * self.param_ops[0])

        assert(self.base.shape == (self.dim, self.dim))
        self.base.flags.writeable = False

    def deriv_wrt_params(self, wrt_filter=None):
        """
        The element-wise derivative this operation.

        Construct a matrix whose columns are the vectorized
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
        Np = self.num_params
        derivMx = _np.zeros((self.dim**2, Np), 'd')
        Nels = len(self.param_ops)

        off = 0
        if self.index < Nels - 1:  # matrix = Di + MT = param_ops[index+1] + param_ops[0]
            for i in [0, self.index + 1]:
                Np = self.param_ops[i].num_params
                derivMx[:, off:off + Np] = self.param_ops[i].deriv_wrt_params()
                off += Np

        else:  # matrix = -(nEls-2)*MT-sum(Di)
            Np = self.param_ops[0].num_params
            derivMx[:, off:off + Np] = -(Nels - 2) * self.param_ops[0].deriv_wrt_params()
            off += Np

            for i in range(1, Nels):
                Np = self.param_ops[i].num_params
                derivMx[:, off:off + Np] = -self.param_ops[i].deriv_wrt_params()
                off += Np

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

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this operation.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return len(self.gpindices_as_array())

    def to_vector(self):
        """
        Get the operation parameters as an array of values.

        Returns
        -------
        numpy array
            The operation parameters as a 1D array with length num_params().
        """
        raise ValueError(("TPInstrumentOp.to_vector() should never be called"
                          " - use TPInstrument.to_vector() instead"))

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
        #Rely on the Instrument ordering of it's elements: if we're being called
        # to init from v then this is within the context of a TPInstrument's operations
        # having been simplified and now being initialized from a vector (within a
        # calculator).  We rely on the Instrument elements having their
        # from_vector() methods called in self.index order.

        if self.index < len(self.param_ops) - 1:  # final element doesn't need to init any param operations
            for i in self.dependents:  # re-init all my dependents (may be redundant)
                if i == 0 and self.index > 0: continue  # 0th param-operation already init by index==0 element
                paramop_local_inds = _modelmember._decompose_gpindices(
                    self.gpindices, self.param_ops[i].gpindices)
                self.param_ops[i].from_vector(v[paramop_local_inds], close, dirty_value)

        self._construct_matrix()
