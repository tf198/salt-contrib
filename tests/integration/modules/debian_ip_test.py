from salt.modules import debian_ip
from salt import exceptions
from unittest import skipIf
import os.path, shutil
import integration

BASE_PATH = os.path.realpath(os.path.dirname(__file__))

TEST_INTERFACES = os.path.join(integration.TMP, 'example_interfaces')

try:
    from mock import patch, call
    has_mock = True
except ImportError:
    has_mock = False

class DebianIPModuleTest(integration.ModuleCase):
    '''
    All these tests are run directly against the module so it doesn't
    matter what system you run them on.
    '''
    
    def tearDown(self):
        debian_ip._clean()
        if os.path.exists(TEST_INTERFACES):
            os.unlink(TEST_INTERFACES)
    
    def _install_interfaces(self):
        shutil.copy(os.path.join(integration.FILES, 'example_interfaces'), TEST_INTERFACES)
    
    def test_interfaces(self):
        self._install_interfaces()
        interfaces = debian_ip.interfaces(TEST_INTERFACES)
        
        self.assertEqual(interfaces['auto'], ['lo', 'eth0'])
    
    def test_get_interface(self):
        self._install_interfaces()
        result = debian_ip.get_interface("eth0", config=TEST_INTERFACES)
        self.assertMultiLineEqual('\n'.join(result), '''
iface eth0 inet static
  address 10.0.0.10
  netmask 255.255.255.0
  gateway 10.0.0.1
  dns-nameservers 8.8.8.8 8.8.8.4
'''.strip())
        
    def test_missing_interfaces(self):
        '''
        This should return just an empty auto list
        '''
        interfaces = debian_ip.interfaces(TEST_INTERFACES)
        self.assertEqual(interfaces, { 'auto': [] })
        
    def test_build_iface_fresh(self):
        result = debian_ip.build_interface('eth0',
                                           'iface',
                                           True,
                                           {'family': 'inet', 'method': 'static', 'up': ['flush-mail', 'do-a-thing'], 'address': '192.168.1.2', 'netmask': '255.255.255.0'}, 
                                           config=TEST_INTERFACES)
        self.assertTrue(os.path.exists(TEST_INTERFACES))
        
        expected = '''
iface eth0 inet static
  address 192.168.1.2
  netmask 255.255.255.0
  up flush-mail
  up do-a-thing
'''.strip()      
        self.assertMultiLineEqual('\n'.join(result), expected)
        
        self.assertMultiLineEqual(open(TEST_INTERFACES, 'r').read(), "auto eth0\n\n{0}\n\n".format(expected))
        
    def test_build_iface_existing(self):
        '''
        Build interface should only update the given named item.
        Other items should be left as-is, eth0 should be removed from the auto list
        '''
        self._install_interfaces()
        result = debian_ip.build_interface('eth0', 
                                           'iface', 
                                           False, 
                                           {'family': 'inet', 'method': 'static', 'up': ['flush-mail', 'do-a-thing'], 'address': '192.168.1.2', 'netmask': '255.255.255.0'}, 
                                           config=TEST_INTERFACES)
        expected = '''
auto lo

iface lo inet loopback

iface eth0 inet static
  address 192.168.1.2
  netmask 255.255.255.0
  up flush-mail
  up do-a-thing

'''.lstrip()
        
        self.assertMultiLineEqual(open(TEST_INTERFACES, 'r').read(), expected)
        
    def test_build_mapping(self):
        result = debian_ip._build_mapping('eth0 eth1', {'script': '/path/to/get-mac-address.sh', 'map': ['11:22:33:44:55:66 lan', 'AA:BB:CC:DD:EE:FF internet']})
        self.assertMultiLineEqual('\n'.join(result), '''
mapping eth0 eth1
  script /path/to/get-mac-address.sh
  map 11:22:33:44:55:66 lan
  map AA:BB:CC:DD:EE:FF internet
'''.strip())
        
    @skipIf(has_mock is False, "Need mock")
    def test_up(self):
        with patch.object(debian_ip, '_cmd_exec', return_value='') as mock:
            debian_ip.up('eth0')
            mock.assert_called_once_with('ifup eth0')
            
    @skipIf(has_mock is False, "Need mock")        
    def test_down(self):
        with patch.object(debian_ip, '_cmd_exec', return_value='') as mock:
            self.assertEqual(debian_ip.down('eth0'), "Brought down eth0")
            mock.assert_called_once_with('ifdown eth0')
    
    @skipIf(has_mock is False, "Need mock")
    def test_already_down(self):
        '''
        Should only complain if unable to bring down the interface
        '''
        with patch.object(debian_ip, '_cmd_exec', side_effect=exceptions.CommandExecutionError("Command returned {0}: {1}".format(1, "Test Error"))) as mock:
            self.assertEqual(debian_ip.down('eth0'), "Failed to bring down eth0")
            mock.assert_called_once_with('ifdown eth0')
            
    @skipIf(has_mock is False, "Need mock")
    def test_clean_up(self):
        '''
        On rebuild a copy of the previous settings is stored for clean restart of the interface
        '''
        self._install_interfaces()
        result = debian_ip.build_interface('eth0', 
                                           'iface', 
                                           False, 
                                           {'family': 'inet', 'method': 'static', 'up': ['flush-mail', 'do-a-thing'], 'address': '192.168.1.2', 'netmask': '255.255.255.0'}, 
                                           config=TEST_INTERFACES)
        temp = debian_ip._previous['eth0']
        
        with patch.object(debian_ip, '_cmd_exec', return_value='') as mock:
            debian_ip.up('eth0')
            #self.assertListEqual(list(mock.call_arg_list), [, 'hello'])
            expected = [call('ifdown -i "{0}" eth0'.format(temp)), call('ifup eth0')]
            self.assertListEqual(expected, mock.call_args_list)
            
        # should have removed temp file
        self.assertFalse(os.path.exists(temp))
        