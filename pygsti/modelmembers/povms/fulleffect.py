
from .conjugatedeffect import ConjugatedStatePOVMEffect as _ConjugatedStatePOVMEffect
from ..states.fullstate import FullState as _FullState


class FullPOVMEffect(_ConjugatedStatePOVMEffect):
    """
    A "fully parameterized" effect vector where each element is an independent parameter.

    Parameters
    ----------
    vec : array_like or POVMEffect
        a 1D numpy array representing the SPAM operation.  The
        shape of this array sets the dimension of the SPAM op.

    evotype : Evotype or str, optional
        The evolution type.  The special value `"default"` is equivalent
        to specifying the value of `pygsti.evotypes.Evotype.default_evotype`.

    state_space : StateSpace, optional
        The state space for this POVM effect.  If `None` a default state space
        with the appropriate number of qubits is used.
    """

    def __init__(self, vec, evotype="default", state_space=None):
        _ConjugatedStatePOVMEffect.__init__(self, _FullState(vec, evotype, state_space))

    def set_dense(self, vec):
        """
        Set the dense-vector value of this SPAM vector.

        Attempts to modify this SPAM vector's parameters so that the raw
        SPAM vector becomes `vec`.  Will raise ValueError if this operation
        is not possible.

        Parameters
        ----------
        vec : array_like or SPAMVec
            A numpy array representing a SPAM vector, or a SPAMVec object.

        Returns
        -------
        None
        """
        self.state.set_dense(vec)
        self.dirty = True
