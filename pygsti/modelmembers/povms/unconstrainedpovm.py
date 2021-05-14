"""
Defines the UnconstrainedPOVM class
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from .basepovm import _BasePOVM


class UnconstrainedPOVM(_BasePOVM):
    """
    A POVM that just holds a set of effect vectors, parameterized individually however you want.

    Parameters
    ----------
    effects : dict of SPAMVecs or array-like
        A dict (or list of key,value pairs) of the effect vectors.
    """

    def __init__(self, effects):
        """
        Creates a new POVM object.

        Parameters
        ----------
        effects : dict of SPAMVecs or array-like
            A dict (or list of key,value pairs) of the effect vectors.
        """
        super(UnconstrainedPOVM, self).__init__(effects, preserve_sum=False)

    def __reduce__(self):
        """ Needed for OrderedDict-derived classes (to set dict items) """
        assert(self.complement_label is None)
        effects = [(lbl, effect.copy()) for lbl, effect in self.items()]
        return (UnconstrainedPOVM, (effects,), {'_gpindices': self._gpindices})
