"""
Base classes for representations.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************


try:
    from .basereps_cython import OpRep, StateRep, EffectRep
except ImportError:
    # If cython is unavailable, just make a pure-python base class to fill in.
    class OpRep:
        pass

    class StateRep:
        pass

    class EffectRep:
        pass

