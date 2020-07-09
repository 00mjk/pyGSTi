# XXX rewrite or remove

import numpy as np
from unittest import mock

from ..util import BaseCase

import pygsti.construction as pc
from pygsti.objects import ExplicitOpModel, Label as L
from pygsti.objects import Circuit
from pygsti.objects.forwardsim import ForwardSimulator
from pygsti.objects.mapforwardsim import MapForwardSimulator


def Ls(*args):
    """ Convert args to a tuple to Labels """
    return tuple([L(x) for x in args])


class AbstractForwardSimTester(BaseCase):
    # XXX is it really neccessary to test an abstract base class?
    def setUp(self):
        mock_model = mock.MagicMock()
        mock_model.evotype.return_value = "densitymx"
        mock_model.circuit_outcomes.return_value = ('NA',)
        mock_model.num_params.return_value = 0
        self.fwdsim = ForwardSimulator(mock_model)
        self.circuit = Circuit("GxGx")

    def test_create_layout(self):
        self.fwdsim.create_layout([self.circuit])

    def test_bulk_fill_probs(self):
        layout = self.fwdsim.create_layout([self.circuit])
        with self.assertRaises(NotImplementedError):
            self.fwdsim.bulk_fill_probs(np.zeros(1), layout)

    def test_bulk_fill_dprobs(self):
        layout = self.fwdsim.create_layout([self.circuit])
        with self.assertRaises(NotImplementedError):
            self.fwdsim.bulk_fill_dprobs(np.zeros((1,0)), layout)

    def test_bulk_fill_hprobs(self):
        layout = self.fwdsim.create_layout([self.circuit])
        with self.assertRaises(NotImplementedError):
            self.fwdsim.bulk_fill_hprobs(np.zeros((1,0,0)), layout)

#    def test_bulk_hprobs_by_block(self):
#        with self.assertRaises(NotImplementedError):
#            self.fwdsim.bulk_fill_hprobs(None, None)


class ForwardSimBase(object):
    @classmethod
    def setUpClass(cls):
        ExplicitOpModel._strict = False
        cls.model = pc.create_explicit_model(
            [('Q0',)], ['Gi', 'Gx', 'Gy'],
            ["I(Q0)", "X(pi/8,Q0)", "Y(pi/8,Q0)"]
        )

    def setUp(self):
        self.fwdsim = self.model.sim
        self.layout = self.fwdsim.create_layout([('Gx',), ('Gx', 'Gx')])
        self.nP = self.model.num_params()
        self.nEls = self.layout.num_elements

    def test_bulk_fill_probs(self):
        pmx = np.empty(self.nEls, 'd')
        self.fwdsim.bulk_fill_probs(pmx, self.layout)
        # TODO assert correctness

    def test_bulk_fill_dprobs(self):
        dmx = np.empty((self.nEls, 3), 'd')
        pmx = np.empty(self.nEls, 'd')
        self.fwdsim.bulk_fill_dprobs(dmx, self.layout, pr_array_to_fill=pmx, wrt_filter=[0, 1, 2])
        # TODO assert correctness

    def test_bulk_fill_dprobs_with_block_size(self):
        dmx = np.empty((self.nEls, self.nP), 'd')
        self.fwdsim.bulk_fill_dprobs(dmx, self.layout)
        # TODO assert correctness

    def test_bulk_fill_hprobs(self):
        hmx = np.zeros((self.nEls, 3, 3), 'd')
        dmx = np.zeros((self.nEls, 3), 'd')
        pmx = np.zeros(self.nEls, 'd')
        self.fwdsim.bulk_fill_hprobs(hmx, self.layout,
                                     pr_array_to_fill=pmx, deriv1_array_to_fill=dmx, deriv2_array_to_fill=dmx,
                                     wrt_filter1=[0, 1, 2], wrt_filter2=[0, 1, 2])  # same slice on each deriv
        # TODO assert correctness

        hmx = np.zeros((self.nEls, 3, 2), 'd')
        dmx1 = np.zeros((self.nEls, 3), 'd')
        dmx2 = np.zeros((self.nEls, 2), 'd')
        pmx = np.zeros(self.nEls, 'd')
        self.fwdsim.bulk_fill_hprobs(hmx, self.layout,
                                     pr_array_to_fill=pmx, deriv1_array_to_fill=dmx1, deriv2_array_to_fill=dmx2,
                                     wrt_filter1=[0, 1, 2], wrt_filter2=[2, 3])  # different slices on 1st vs. 2nd deriv
        # TODO assert correctness

    def test_bulk_hprobs_by_block(self):
        # TODO optimize
        mx = np.zeros((self.nEls, self.nP, self.nP), 'd')
        dmx1 = np.zeros((self.nEls, self.nP), 'd')
        dmx2 = np.zeros((self.nEls, self.nP), 'd')
        pmx = np.zeros(self.nEls, 'd')
        self.fwdsim.bulk_fill_hprobs(mx, self.layout, pr_array_to_fill=pmx,
                                     deriv1_array_to_fill=dmx1, deriv2_array_to_fill=dmx2)
        # TODO assert correctness

    #REMOVE
    #def test_prs(self):
    #    
    #    self.fwdsim._prs(L('rho0'), [L('Mdefault_0')], Ls('Gx', 'Gx'), clip_to=(-1, 1))
    #    self.fwdsim._prs(L('rho0'), [L('Mdefault_0')], Ls('Gx', 'Gx'), clip_to=(-1, 1), use_scaling=True)
    #    # TODO assert correctness
    #
    #def test_estimate_cache_size(self):
    #    self.fwdsim._estimate_cache_size(100)
    #    # TODO assert correctness
    #
    #def test_estimate_mem_usage(self):
    #    est = self.fwdsim.estimate_memory_usage(
    #        ["bulk_fill_probs", "bulk_fill_dprobs", "bulk_fill_hprobs"],
    #        cache_size=100, num_subtrees=2, num_subtree_proc_groups=1,
    #        num_param1_groups=1, num_param2_groups=1, num_final_strs=100
    #    )
    #    # TODO assert correctness
    #
    #def test_estimate_mem_usage_raises_on_bad_subcall_key(self):
    #    with self.assertRaises(ValueError):
    #        self.fwdsim.estimate_memory_usage(["foobar"], 1, 1, 1, 1, 1, 1)


class MatrixForwardSimTester(ForwardSimBase, BaseCase):
    def test_doperation(self):
        dg = self.fwdsim._doperation(L('Gx'), flat=False)
        dgflat = self.fwdsim._doperation(L('Gx'), flat=True)
        # TODO assert correctness

    def test_hoperation(self):
        hg = self.fwdsim._hoperation(L('Gx'), flat=False)
        hgflat = self.fwdsim._hoperation(L('Gx'), flat=True)
        # TODO assert correctness

    #REMOVE
    #def test_hproduct(self):
    #    self.fwdsim.hproduct(Ls('Gx', 'Gx'), flat=True, wrt_filter1=[0, 1], wrt_filter2=[1, 2, 3])
    #    # TODO assert correctness
    #def test_hpr(self):
    #    self.fwdsim._hpr(Ls('rho0', 'Mdefault_0'), Ls('Gx', 'Gx'), False, False, clip_to=(-1, 1))
    #    # TODO assert correctness

    def test_rhoE_from_spamTuple(self):
        # XXX does this need to be tested?  EGN: No
        custom_spamTuple = (np.zeros((4, 1), 'd'), np.zeros((4, 1), 'd'))
        self.fwdsim._rho_e_from_spam_tuple(custom_spamTuple)
        # TODO assert correctness


class CPTPMatrixForwardSimTester(MatrixForwardSimTester):
    @classmethod
    def setUpClass(cls):
        super(CPTPMatrixForwardSimTester, cls).setUpClass()
        cls.model = cls.model.copy()
        cls.model.set_all_parameterizations("CPTP")  # so gates have nonzero hessians


class MapForwardSimTester(ForwardSimBase, BaseCase):
    @classmethod
    def setUpClass(cls):
        super(MapForwardSimTester, cls).setUpClass()
        cls.model = cls.model.copy()
        cls.model.sim = MapForwardSimulator()
