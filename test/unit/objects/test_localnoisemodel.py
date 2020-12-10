import numpy as np

from ..util import BaseCase

from pygsti.objects.circuit import Circuit
from pygsti.objects.localnoisemodel import LocalNoiseModel


class LocalNoiseModelInstanceTester(BaseCase):
    def test_indep_localnoise(self):
        nQubits = 2
        mdl_local = LocalNoiseModel.from_parameterization(
            nQubits, ('Gx', 'Gy', 'Gcnot'), geometry="line",
            qubit_labels=['qb{}'.format(i) for i in range(nQubits)],
            parameterization='H+S', independent_gates=True,
            ensure_composed_gates=False, global_idle=None)

        assert(set(mdl_local.operation_blks['gates'].keys()) == set(
            [('Gx', 'qb0'), ('Gx', 'qb1'), ('Gy', 'qb0'), ('Gy', 'qb1'), ('Gcnot', 'qb0', 'qb1'), ('Gcnot', 'qb1', 'qb0')]))
        assert(set(mdl_local.operation_blks['layers'].keys()) == set(
            [('Gx', 'qb0'), ('Gx', 'qb1'), ('Gy', 'qb0'), ('Gy', 'qb1'), ('Gcnot', 'qb0', 'qb1'), ('Gcnot', 'qb1', 'qb0')]))
        test_circuit = ([('Gx', 'qb0'), ('Gy', 'qb1')], ('Gcnot', 'qb0', 'qb1'), [('Gx', 'qb1'), ('Gy', 'qb0')])
        self.assertAlmostEqual(sum(mdl_local.probabilities(test_circuit).values()), 1.0)
        self.assertEqual(mdl_local.num_params, 108)

    def test_dep_localnoise(self):
        nQubits = 2
        mdl_local = LocalNoiseModel.from_parameterization(
            nQubits, ('Gx', 'Gy', 'Gcnot'), geometry="line",
            qubit_labels=['qb{}'.format(i) for i in range(nQubits)],
            parameterization='H+S', independent_gates=False,
            ensure_composed_gates=False, global_idle=None)

        assert(set(mdl_local.operation_blks['gates'].keys()) == set(["Gx", "Gy", "Gcnot"]))
        assert(set(mdl_local.operation_blks['layers'].keys()) == set(
            [('Gx', 'qb0'), ('Gx', 'qb1'), ('Gy', 'qb0'), ('Gy', 'qb1'), ('Gcnot', 'qb0', 'qb1'), ('Gcnot', 'qb1', 'qb0')]))
        test_circuit = ([('Gx', 'qb0'), ('Gy', 'qb1')], ('Gcnot', 'qb0', 'qb1'), [('Gx', 'qb1'), ('Gy', 'qb0')])
        self.assertAlmostEqual(sum(mdl_local.probabilities(test_circuit).values()), 1.0)
        self.assertEqual(mdl_local.num_params, 66)

    def test_localnoise_with1Qidle(self):
        nQubits = 2
        noisy_idle = np.array([[1, 0, 0, 0],
                               [0, 0.9, 0, 0],
                               [0, 0, 0.9, 0],
                               [0, 0, 0, 0.9]], 'd')

        mdl_local = LocalNoiseModel.from_parameterization(
            nQubits, ('Gx', 'Gy', 'Gcnot'), geometry="line",
            qubit_labels=['qb{}'.format(i) for i in range(nQubits)],
            parameterization='static', independent_gates=False,
            ensure_composed_gates=False, global_idle=noisy_idle)

        assert(set(mdl_local.operation_blks['gates'].keys()) == set(["Gx", "Gy", "Gcnot", "1QIdle"]))
        assert(set(mdl_local.operation_blks['layers'].keys()) == set(
            [('Gx', 'qb0'), ('Gx', 'qb1'), ('Gy', 'qb0'), ('Gy', 'qb1'), ('Gcnot', 'qb0', 'qb1'), ('Gcnot', 'qb1', 'qb0'), 'globalIdle']))
        test_circuit = (('Gx', 'qb0'), ('Gcnot', 'qb0', 'qb1'), [], [('Gx', 'qb1'), ('Gy', 'qb0')])
        self.assertAlmostEqual(sum(mdl_local.probabilities(test_circuit).values()), 1.0)
        self.assertAlmostEqual(mdl_local.probabilities(test_circuit)['00'], 0.3576168)
        self.assertEqual(mdl_local.num_params, 0)

    def test_localnoise_withNQidle(self):
        nQubits = 2
        noisy_idle = 0.9 * np.identity(4**nQubits, 'd')
        noisy_idle[0, 0] = 1.0

        mdl_local = LocalNoiseModel.from_parameterization(
            nQubits, ('Gx', 'Gy', 'Gcnot'), geometry="line",
            qubit_labels=['qb{}'.format(i) for i in range(nQubits)],
            parameterization='H+S+A', independent_gates=False,
            ensure_composed_gates=False, global_idle=noisy_idle)

        assert(set(mdl_local.operation_blks['gates'].keys()) == set(["Gx", "Gy", "Gcnot"]))
        assert(set(mdl_local.operation_blks['layers'].keys()) == set(
            [('Gx', 'qb0'), ('Gx', 'qb1'), ('Gy', 'qb0'), ('Gy', 'qb1'), ('Gcnot', 'qb0', 'qb1'), ('Gcnot', 'qb1', 'qb0'), 'globalIdle']))
        test_circuit = (('Gx', 'qb0'), ('Gcnot', 'qb0', 'qb1'), [], [('Gx', 'qb1'), ('Gy', 'qb0')])
        self.assertAlmostEqual(sum(mdl_local.probabilities(test_circuit).values()), 1.0)
        self.assertAlmostEqual(mdl_local.probabilities(test_circuit)['00'], 0.414025)
        self.assertEqual(mdl_local.num_params, 144)

    def test_marginalized_povm(self):
        nQubits = 4
        # TODO: This fails if custom qubit labels are used (as in above tests)
        # Somehow the marginalization code doesn't handle custom sslbls well?
        mdl_local = LocalNoiseModel.from_parameterization(
            nQubits, ('Gx', 'Gy', 'Gcnot'), geometry="line",
            parameterization='H+S', independent_gates=True,
            ensure_composed_gates=False, global_idle=None)

        c = Circuit( [('Gx',0),('Gx',1),('Gx',2),('Gx',3)], num_lines=4)
        prob = mdl_local.probabilities(c)
        self.assertEqual(len(prob), 16) # Full 4 qubit space

        c2 = Circuit( [('Gx',0),('Gx',1)], num_lines=2)
        prob2 = mdl_local.probabilities(c2)
        self.assertEqual(len(prob2), 4) # Full 4 qubit space

        c3 = Circuit( [('Gx',0),('Gx',1)], num_lines=4)
        prob3 = mdl_local.probabilities(c3)
        self.assertEqual(len(prob3), 16) # Full 16 qubit space



