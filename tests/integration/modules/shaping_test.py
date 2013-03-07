'''
Created on 03/03/2013

@author: tris
'''
import integration, yaml, os.path, shutil, subprocess
from saltunittest import skipIf
from salt.modules import shaping

try:
    from mock import MagicMock, patch
    has_mock = True
except ImportError:
    has_mock = False

SCRIPT_FILE = os.path.join(integration.TMP, 'tc_script_eth0')

class ShapingModuleTest(integration.ModuleCase):
    
    def tearDown(self):
        if os.path.exists(SCRIPT_FILE):
            os.unlink(SCRIPT_FILE)
    
    def _install_script(self):
        shutil.copyfile(os.path.join(integration.FILES, 'tc_script_eth0'), SCRIPT_FILE)
        
    def test_get_tc_script(self):
        
        self.assertEqual(self.run_function('tc.get_script', ['eth0', SCRIPT_FILE]), [])
        
        self._install_script()
        
        with open(SCRIPT_FILE, 'r') as f:
            expected = f.readlines()
        self.assertEqual(self.run_function('tc.get_script', ['eth0', SCRIPT_FILE]), expected)
    
    def test_build_tc_script(self):
        
        result = self.run_function('tc.build_script', ['eth0', {'type': 'prio'}, SCRIPT_FILE])
        self.assertTrue(os.path.exists(SCRIPT_FILE))
        
        self.assertEqual(len(result), 6)
        
        written = open(SCRIPT_FILE, 'r').readlines()
        self.assertListEqual(result, written)
        self.assertEqual(result[5], 'tc qdisc add dev eth0 root handle 1: prio\n')
        
    def test_enable(self):
        
        e = self.run_function('tc.enable', ['eth0', SCRIPT_FILE])
        self.assertRegexpMatches(e, "ERROR: Script for eth0 has not yet been built")
        
        self._install_script()
        
        if not has_mock:
            self.skipTest("Need mock")
            
        with patch.object(shaping, '_cmd_exec', return_value='') as mock:
            self.assertEqual(shaping.enable('eth0', SCRIPT_FILE), '')
            mock.assert_called_once_with(SCRIPT_FILE)
    
    @skipIf(has_mock is False, "Need mock")
    def test_disable(self):
        with patch.object(shaping, '_cmd_exec', return_value='') as mock:
            self.assertEqual(shaping.disable('eth0'), '')
            mock.assert_called_once_with('tc qdisc del dev eth0 root')
        