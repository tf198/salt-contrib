'''
Networking module for Debian based systems (/etc/network/interfaces)

TODO: Hook salt finished to cleanup any previous config files
'''
import logging, copy, shutil, os, sys, tempfile
from collections import OrderedDict
from salt import exceptions

log = logging.getLogger(__name__)

def __virtual__():
    '''
    Only applies to Debian based systems
    '''
    if __grains__['os_family'] == 'Debian':
        return 'ip'
    return False

_OPENING_STANZAS = ( 'iface', 'mapping', 'auto', 'allow-' )

# these maps are so we can correctly order items
_ALLOWED_OPTIONS = {
    'iface': {
        'inet': {
            'global': ( 'pre-up', 'up', 'post-up', 'pre-down', 'down', 'post-down' ),
            'loopback': (),
            'static': ( 'address', 'netmask', 'broadcast', 'network', 'metric', 'gateway', 'pointtopoint', 'media', 'hwaddress', 'mtu' ),
            'manual': (),
            'dhcp': ( 'hostname', 'leasehours', 'leasetime', 'vendor', 'client', 'hwaddress' ),
            'bootp': ( 'bootfile', 'server', 'hwaddr' ),
            'ppp': ( 'provider' ),
            'wvdial': ( 'provider' ),
            'ipv4ll': (),
        }
    },
    'mapping': ( 'script', 'map' ),
}

_INDENT = '  '

_IFACE_ORDER = ( '')

_DEBIAN_INTERFACES_FILE = '/etc/network/interfaces'

_interfaces = {}
_previous = {}

def _clean():
    global _interfaces, _previous
    
    _interfaces = {}
    for x in _previous:
        os.unlink(_previous[x])
    _previous = {}

def _parse_interfaces(path):
    '''
    Partially parses an interfaces file.
    Parses up to stanza level and keys everything by name, except for 'auto'
    which creates a single list.
    '''
    global _interfaces
    
    # cache the parse
    if path in _interfaces: return _interfaces[path]
    
    result = OrderedDict({'auto': []})
    p = None    
    
    if not os.path.exists(path):
        return result
    
    for line in open(path):
        line = line.strip()
        if line != '' and line[0] != '#':
            if line.startswith(_OPENING_STANZAS):
                parts = line.split(' ')
                
                # add the dict if not present
                if not parts[0] in result:
                    result[parts[0]] = {}
                
                # treat auto as special
                if parts[0] == 'auto':
                    result['auto'] += parts[1:]
                    p = None
                else:
                    key = parts[1]
                    if parts[0] == 'mapping': key = ' '.join(parts[1:])
                    
                    result[parts[0]][key] = []
                    p = result[parts[0]][key] 
                    
                    p.append(line)
            else:
                if p is None: raise Exception("Not in a stanza")
                p.append(_INDENT + line)
    
    _interfaces[path] = result
    return result

def _write_file(path, interfaces):
    fout = file(path, 'w')
    
    for stanza,items in interfaces.items():
        if stanza == 'auto':
            if items:
                fout.write("auto %s\n\n" % ' '.join(items))
        else:
            for lines in items.values():
                fout.write('\n'.join(lines))
                fout.write('\n\n')
    fout.close()

def _build_stanza(stanza, settings, options):
    '''
    Builds a stanza using the provided options list to order the items.
    Child elements are indented for easy reading
    '''
    result = [stanza]
    
    log.info(settings)
    
    for k in options:
        if k in settings:
            v = settings[k]
            del(settings[k])
            if isinstance(v, basestring):
                v = [ v ]
            for item in v:
                result.append("%s%s %s" % (_INDENT, k, item))
    
    # add any special options (wireless etc)
    for k,v in settings.items():
        if k[0:1] == '__': continue
        if not hasattr(v, '__iter__'):
            v = [ v ]
        for item in v:
            result.append("%s%s %s" % (_INDENT, k, item))
        
    
    return result

def _build_iface(iface, settings):
    family = settings.pop('family')
    method = settings.pop('method')
    
    options =  _ALLOWED_OPTIONS['iface'][family][method] + _ALLOWED_OPTIONS['iface'][family]['global']
    
    return _build_stanza("iface %s %s %s" % (iface, family, method), settings, options)

def _build_mapping(interfaces, settings):
    options = _ALLOWED_OPTIONS['mapping']
    
    return _build_stanza("mapping %s" % interfaces, settings, options)

def interfaces(config=_DEBIAN_INTERFACES_FILE):
    '''
    Returns raw lines for interface, grouped by type and name
    
    CLI Example::
    
        salt '*' ip.interfaces eth0
    
    '''
    return _parse_interfaces(config)

def get_interface(name, config=_DEBIAN_INTERFACES_FILE):
    '''
    Returns the lines that make up the settings for a specific interface
    Compatible with network.managed
    
    CLI Example::

        salt '*' ip.get_interface eth0
    '''
    interfaces = _parse_interfaces(config)
    
    if name in interfaces['iface']:
        return interfaces['iface'][name]
    
    return ''

def build_interface(iface, iface_type, enabled, settings, config=_DEBIAN_INTERFACES_FILE):
    '''
    Recompiles the network script and returns the interface specific lines
    If <enabled> then it is added to the auto group.  <settings> is a dict
    of options for the 
    
    Compatible with network.managed
    
    CLI Example::
    
        salt '*' ip.build_interface eth0 iface True <settings>
    '''
    # create a deep copy so we can remove things as processed
    settings = copy.deepcopy(settings)
    
    # a bit of a hack to allow for testing with network.managed
    config = settings.pop('config', config)
    
    # parse the current file
    current = _parse_interfaces(config)
    sync = False
    
    # remove the auto added items
    for x in ('state', 'order', 'fun'):
        if x in settings: del settings[x]
    
    testing = settings.pop('test', False)
    
    # add or remove auto items
    if iface_type == 'iface':
        if enabled:
            if not iface in current['auto']:
                current['auto'].append(iface)
                sync = True
        else:
            if iface in current['auto']:
                current['auto'].remove(iface)
                sync = True          
    
    lines = getattr(sys.modules[__name__], '_build_{0}'.format(iface_type))(iface, settings)
    
    if not iface_type in current:
        current[iface_type] = {}
    if not iface in current[iface_type]:
        current[iface_type][iface] = []
    
    if current[iface_type][iface] != lines:
        current[iface_type][iface] = lines
        sync = True
    
    if testing:
        return lines
            
    if sync:
        global _previous
        # make a copy of the previous version so we can cleanly reload it
        if os.path.exists(config):
            fh, temp = tempfile.mkstemp()
            os.close(fh)
            shutil.copyfile(config, temp)
            os.chmod(temp, 0600)
            _previous[iface] = temp
        
        _write_file(config, current)
    
    return lines

def _previous_down(iface):
    global _previous
    
    if iface in _previous:
        previous = _previous[iface]
        
        log.debug("Using previous settings to take down {0}".format(iface))
        # check for malicious usage 
        if os.stat(previous).st_uid != os.getuid():
            raise Exception("Previous file '{0}' not owned by process - possible hijack attempt?".format(previous))
        
        try:
            _cmd_exec('ifdown -i "{0}" {1}'.format(previous, iface))
        except:
            log.warning('Failed to cleanly bring down {0} using previous interface settings'.format(iface))
            
        os.unlink(previous)
        del _previous[iface]
        return True
    
    return False

def _cmd_exec(cmd):
    '''
    Helper to check the return value of shell commands
    There really should be something in the cmdmod module for this
    but it helps with mocking to have it here anyway
    '''
    result = __salt__['cmd.run_all'](cmd)
    
    if result['retcode'] != 0:
        raise exceptions.CommandExecutionError("Command returned {0}: {1}".format(result['retcode'], result['stderr']))
                        
    return result['stdout']

def up(iface, iface_type=None, opts={}):
    '''
    Bring up an interface
    Additional options are to remain compatible with network.managed
    
    CLI Example::

        salt '*' ip.up eth0
    '''
    
    # check for the presence of a previous version
    _previous_down(iface)
    
    cmd = 'ifup {0}'.format(iface)
    if 'config' in opts: cmd += " -i {0}".format(opts['config'])
    return _cmd_exec(cmd)

def down(iface, iface_type=None, opts={}):
    '''
    Bring down an interface
    Additional options are to remain compatible with network.managed
    
    CLI Example::

        salt '*' ip.down eth0
    '''
    # if there was a previous config use that instead
    if _previous_down(iface):
        return "Brought down {0} using previous".format(iface)
    
    try:
        cmd = 'ifdown {0}'.format(iface)
        if 'config' in opts: cmd += " -i {0}".format(opts['config'])
        _cmd_exec(cmd)
        return "Brought down {0}".format(iface);
    except:
        msg = "Failed to bring down {0}".format(iface)
        log.exception(msg)
        return msg
    
